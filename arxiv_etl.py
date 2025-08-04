#!/usr/bin/env python3
"""
ArXiv AI Papers ETL Pipeline
Extracts AI science papers from arXiv API, loads them into Supabase database,
and generates AI summaries using Gemini API.
"""

import os
import sys
import logging
import feedparser
import requests
import json
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv
import time
import re
import threading

# PDF processing imports
import PyPDF2
from io import BytesIO

# Gemini AI imports
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('arxiv_etl.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class RateLimiter:
    """Rate limiter for Gemini API to stay within free tier limits."""
    
    def __init__(self, max_requests_per_minute=15):
        self.max_requests_per_minute = max_requests_per_minute
        self.requests_made = []
        self.lock = threading.Lock()
    
    def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        with self.lock:
            now = datetime.now()
            
            # Remove requests older than 1 minute
            self.requests_made = [req_time for req_time in self.requests_made 
                                if (now - req_time).total_seconds() < 60]
            
            # If we're at the limit, wait until we can make another request
            if len(self.requests_made) >= self.max_requests_per_minute:
                oldest_request = min(self.requests_made)
                wait_time = 60 - (now - oldest_request).total_seconds()
                if wait_time > 0:
                    logger.info(f"Rate limit reached. Waiting {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
                    # Clean up again after waiting
                    now = datetime.now()
                    self.requests_made = [req_time for req_time in self.requests_made 
                                        if (now - req_time).total_seconds() < 60]
            
            # Record this request
            self.requests_made.append(now)
            logger.debug(f"API requests in last minute: {len(self.requests_made)}/{self.max_requests_per_minute}")

class ArxivETL:
    """ETL pipeline for extracting AI papers from arXiv, loading to Supabase, and generating AI summaries."""
    
    def __init__(self):
        """Initialize the ETL pipeline with Supabase client and arXiv API configuration."""
        # Supabase configuration
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_ANON_KEY')
        
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("Missing Supabase credentials in environment variables")
        
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
        
        # Gemini AI configuration with rate limiting
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        if not self.gemini_api_key or self.gemini_api_key == 'your_gemini_api_key_here':
            logger.warning("Gemini API key not configured. PDF summarization will be skipped.")
            self.gemini_enabled = False
        else:
            try:
                genai.configure(api_key=self.gemini_api_key)
                # Use Gemini 2.5 Flash Lite model (free tier)
                self.gemini_model = genai.GenerativeModel('gemini-2.5-flash-lite')
                self.gemini_enabled = True
                # Initialize rate limiter for free tier: 15 requests per minute
                self.rate_limiter = RateLimiter(max_requests_per_minute=15)
                logger.info("Gemini 2.5 Flash Lite configured successfully with rate limiting (15 req/min)")
            except Exception as e:
                logger.error(f"Failed to configure Gemini AI: {str(e)}")
                self.gemini_enabled = False
        
        # Load taxonomy for category name translation from Supabase
        self.taxonomy = self.load_taxonomy_from_supabase()
        
        # ArXiv API configuration
        self.arxiv_base_url = "http://export.arxiv.org/api/query"
        
        # AI-related categories and keywords
        self.ai_categories = [
            'cs.AI',  # Artificial Intelligence
            'cs.LG',  # Machine Learning
            'cs.CV',  # Computer Vision and Pattern Recognition
            'cs.CL',  # Computation and Language (NLP)
            'cs.NE',  # Neural and Evolutionary Computing
            'stat.ML',  # Machine Learning (Statistics)
            'cs.RO',  # Robotics
            'cs.IR',  # Information Retrieval
        ]
        
        # Additional AI-related keywords for broader coverage
        self.ai_keywords = [
            'neural network', 'deep learning', 'machine learning', 'artificial intelligence',
            'natural language processing', 'computer vision', 'reinforcement learning',
            'transformer', 'attention mechanism', 'generative model', 'large language model',
            'llm', 'gpt', 'bert', 'diffusion model', 'gan', 'autoencoder'
        ]
    
    def load_taxonomy_from_supabase(self) -> Dict[str, str]:
        """Load category mappings from the public.v_arxiv_categories view in Supabase."""
        try:
            logger.info("Loading category taxonomy from Supabase public.v_arxiv_categories view")
            response = self.supabase.table('v_arxiv_categories').select('category_code, category_name').execute()
            
            if not response.data:
                logger.warning("No category data found in public.v_arxiv_categories view")
                return {}
            
            # Convert to dictionary mapping category_code -> category_name
            taxonomy = {row['category_code']: row['category_name'] for row in response.data}
            logger.info(f"Loaded taxonomy with {len(taxonomy)} category mappings from Supabase")
            return taxonomy
            
        except Exception as e:
            logger.error(f"Error loading taxonomy from Supabase: {str(e)}")
            logger.info("Falling back to empty taxonomy - original category IDs will be used")
            return {}
    
    def load_taxonomy(self) -> Dict[str, str]:
        """Deprecated: Load the taxonomy.json file for category name translation."""
        logger.warning("load_taxonomy() is deprecated. Now using load_taxonomy_from_supabase()")
        return self.load_taxonomy_from_supabase()
    
    def translate_categories(self, category_ids: List[str]) -> List[str]:
        """Translate category IDs to full names using taxonomy."""
        if not self.taxonomy:
            logger.warning("No taxonomy loaded, returning original category IDs")
            return category_ids
        
        category_names = []
        for cat_id in category_ids:
            if cat_id in self.taxonomy:
                category_names.append(self.taxonomy[cat_id])
            else:
                # Keep original ID if not found in taxonomy
                category_names.append(cat_id)
                logger.debug(f"Category ID '{cat_id}' not found in taxonomy")
        
        return category_names
    
    def get_today_date_range(self) -> tuple:
        """Get the date range for the latest published papers (arXiv only publishes on weekdays)."""
        today = datetime.now()
        
        # arXiv only publishes papers Monday through Friday
        # On Monday, we want Friday's papers (3 days back)
        # On other days, we want the previous day's papers
        if today.weekday() == 0:  # Monday = 0
            target_date = today - timedelta(days=3)  # Friday
            logger.info("Monday detected: fetching Friday's publications")
        else:
            target_date = today - timedelta(days=1)  # Previous day
        
        # Use target date since arXiv publishes papers the day before they appear
        start_date = target_date.strftime('%Y%m%d0000')  # Start of target date
        end_date = target_date.strftime('%Y%m%d2359')   # End of target date
        return start_date, end_date
    
    def is_paper_from_today(self, paper_date: str) -> bool:
        """Check if a paper is actually from today's date."""
        try:
            # Parse the paper's published date
            paper_dt = datetime.strptime(paper_date, '%Y-%m-%dT%H:%M:%SZ')
            today = datetime.now().date()
            paper_date_only = paper_dt.date()
            
            return paper_date_only == today
        except Exception as e:
            logger.warning(f"Could not parse date {paper_date}: {str(e)}")
            return False
    
    def build_arxiv_query(self, start_date: str, end_date: str, max_results: int = 2000) -> str:
        """Build arXiv API query for AI papers submitted today only."""
        # Build category query - more restrictive for today only
        category_query = ' OR '.join([f'cat:{cat}' for cat in self.ai_categories])
        
        # For current date, we'll be more restrictive and rely on post-filtering
        # Use only the main AI categories for the query
        query = f"({category_query}) AND submittedDate:[{start_date} TO {end_date}]"
        
        # Build full URL - increase max_results since we'll filter more aggressively
        params = {
            'search_query': query,
            'start': 0,
            'max_results': max_results,
            'sortBy': 'submittedDate',
            'sortOrder': 'descending'
        }
        
        param_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        return f"{self.arxiv_base_url}?{param_string}"
    
    def extract_papers_from_arxiv(self, start_date: str, end_date: str, target_date: str = None) -> List[Dict[str, Any]]:
        """Extract papers from arXiv API for the given date range, filtered for target date only."""
        logger.info(f"Extracting papers from arXiv for date range: {start_date} to {end_date}")
        
        # Determine target date for filtering
        if target_date:
            filter_date = datetime.strptime(target_date, '%Y%m%d').date()
        else:
            filter_date = datetime.now().date()
        
        query_url = self.build_arxiv_query(start_date, end_date)
        logger.info(f"ArXiv query URL: {query_url}")
        
        try:
            # Make request to arXiv API
            response = requests.get(query_url, timeout=30)
            response.raise_for_status()
            
            # Parse the Atom feed
            feed = feedparser.parse(response.content)
            
            papers = []
            filtered_count = 0
            
            for entry in feed.entries:
                try:
                    paper = self.parse_arxiv_entry(entry)
                    if paper:
                        # Additional filtering: only include papers from target date
                        paper_dt = datetime.fromisoformat(paper['published_date'].replace('Z', '+00:00'))
                        paper_date = paper_dt.date()
                        
                        if paper_date == filter_date:
                            papers.append(paper)
                        else:
                            filtered_count += 1
                            logger.debug(f"Filtered out paper from {paper_date}: {paper['arxiv_id']}")
                            
                except Exception as e:
                    logger.error(f"Error parsing entry {entry.get('id', 'unknown')}: {str(e)}")
                    continue
            
            logger.info(f"Successfully extracted {len(papers)} papers from target date ({filter_date})")
            logger.info(f"Filtered out {filtered_count} papers from other dates")
            return papers
            
        except requests.RequestException as e:
            logger.error(f"Error fetching data from arXiv: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error parsing arXiv response: {str(e)}")
            raise
    
    def parse_arxiv_entry(self, entry) -> Optional[Dict[str, Any]]:
        """Parse a single arXiv entry into our paper format."""
        try:
            # Extract arXiv ID
            arxiv_id = entry.id.split('/')[-1].replace('abs/', '')
            
            # Extract basic information
            title = entry.title.strip()
            abstract = entry.summary.strip()
            
            # Extract authors
            authors = []
            if hasattr(entry, 'authors'):
                authors = [author.name for author in entry.authors]
            elif hasattr(entry, 'author'):
                authors = [entry.author]
            
            # Extract categories
            categories = []
            if hasattr(entry, 'tags'):
                categories = [tag.term for tag in entry.tags]
            
            # Translate category IDs to full names
            categories_name = self.translate_categories(categories)
            
            # Extract dates
            published_date = entry.published
            updated_date = getattr(entry, 'updated', published_date)
            
            # Convert to datetime objects
            published_dt = datetime.strptime(published_date, '%Y-%m-%dT%H:%M:%SZ')
            updated_dt = datetime.strptime(updated_date, '%Y-%m-%dT%H:%M:%SZ')
            
            # Extract links
            pdf_url = None
            abstract_url = entry.id
            
            if hasattr(entry, 'links'):
                for link in entry.links:
                    if link.type == 'application/pdf':
                        pdf_url = link.href
                        break
            
            # Build paper object
            paper = {
                'arxiv_id': arxiv_id,
                'title': title,
                'abstract': abstract,
                'authors': authors,
                'categories': categories,
                'categories_name': categories_name,
                'published_date': published_dt.isoformat(),
                'updated_date': updated_dt.isoformat(),
                'pdf_url': pdf_url,
                'abstract_url': abstract_url,
                'extracted_at': datetime.now().isoformat()
            }
            
            return paper
            
        except Exception as e:
            logger.error(f"Error parsing entry: {str(e)}")
            return None
    
    def create_papers_table_if_not_exists(self):
        """Create the papers table in Supabase if it doesn't exist."""
        try:
            # Try to query the table to see if it exists
            result = self.supabase.table('arxiv_papers').select('*').limit(1).execute()
            logger.info("Papers table already exists")
        except Exception as e:
            logger.info("Papers table doesn't exist, will be created automatically on first insert")
    
    def load_papers_to_supabase(self, papers: List[Dict[str, Any]]) -> int:
        """Load papers to Supabase database."""
        if not papers:
            logger.info("No papers to load")
            return 0
        
        logger.info(f"Loading {len(papers)} papers to Supabase")
        
        try:
            # Check for existing papers to avoid duplicates
            existing_ids = set()
            if papers:
                arxiv_ids = [paper['arxiv_id'] for paper in papers]
                existing_result = self.supabase.table('arxiv_papers').select('arxiv_id').in_('arxiv_id', arxiv_ids).execute()
                existing_ids = {row['arxiv_id'] for row in existing_result.data}
            
            # Filter out existing papers
            new_papers = [paper for paper in papers if paper['arxiv_id'] not in existing_ids]
            
            if not new_papers:
                logger.info("All papers already exist in database")
                return 0
            
            logger.info(f"Inserting {len(new_papers)} new papers")
            
            # Insert papers in batches
            batch_size = 100
            inserted_count = 0
            
            for i in range(0, len(new_papers), batch_size):
                batch = new_papers[i:i + batch_size]
                try:
                    result = self.supabase.table('arxiv_papers').insert(batch).execute()
                    inserted_count += len(batch)
                    logger.info(f"Inserted batch of {len(batch)} papers")
                    time.sleep(0.5)  # Small delay between batches
                except Exception as e:
                    logger.error(f"Error inserting batch: {str(e)}")
                    # Continue with next batch
                    continue
            
            logger.info(f"Successfully loaded {inserted_count} new papers to Supabase")
            return inserted_count
            
        except Exception as e:
            logger.error(f"Error loading papers to Supabase: {str(e)}")
            raise
    
    def update_categories_names(self) -> int:
        """Update existing arxiv_papers records to populate categories_name field by joining with v_arxiv_categories."""
        try:
            logger.info("Starting update of categories_name field for existing papers")
            
            # Get all papers that don't have categories_name populated or have empty arrays
            papers_response = self.supabase.table('arxiv_papers').select('id, categories').or_('categories_name.is.null,categories_name.eq.{}').execute()
            
            if not papers_response.data:
                logger.info("No papers found that need categories_name updates")
                return 0
            
            logger.info(f"Found {len(papers_response.data)} papers that need categories_name updates")
            
            # Load taxonomy for translation
            if not self.taxonomy:
                logger.warning("No taxonomy loaded, cannot update categories_name")
                return 0
            
            updated_count = 0
            batch_size = 50
            
            # Process papers in batches
            for i in range(0, len(papers_response.data), batch_size):
                batch = papers_response.data[i:i + batch_size]
                
                for paper in batch:
                    try:
                        paper_id = paper['id']
                        categories = paper.get('categories', [])
                        
                        if not categories:
                            continue
                        
                        # Translate categories to names
                        categories_names = self.translate_categories(categories)
                        
                        # Update the paper with translated category names
                        update_response = self.supabase.table('arxiv_papers').update({
                            'categories_name': categories_names
                        }).eq('id', paper_id).execute()
                        
                        if update_response.data:
                            updated_count += 1
                            
                    except Exception as e:
                        logger.error(f"Error updating paper ID {paper.get('id', 'unknown')}: {str(e)}")
                        continue
                
                # Small delay between batches
                time.sleep(0.1)
                logger.info(f"Processed batch {i//batch_size + 1}, updated {updated_count} papers so far")
            
            logger.info(f"Successfully updated categories_name for {updated_count} papers")
            return updated_count
            
        except Exception as e:
            logger.error(f"Error updating categories_name: {str(e)}")
            return 0
    
    def run_daily_etl(self):
        """Run the complete ETL pipeline for the latest published papers (weekday-aware)."""
        today = datetime.now()
        
        # Determine target date based on weekday logic
        if today.weekday() == 0:  # Monday
            target_date = today - timedelta(days=3)  # Friday
            date_description = "FRIDAY'S PUBLICATIONS (weekend skip)"
        else:
            target_date = today - timedelta(days=1)  # Previous day
            date_description = "PREVIOUS DAY'S PUBLICATIONS"
        
        target_str = target_date.strftime('%Y-%m-%d')
        logger.info(f"Starting daily arXiv ETL pipeline for {date_description}: {target_str}")
        logger.info("Note: arXiv only publishes papers Monday through Friday")
        
        try:
            # Get target date range
            start_date, end_date = self.get_today_date_range()
            
            # Extract papers from arXiv (will be filtered to target date only)
            papers = self.extract_papers_from_arxiv(start_date, end_date, start_date[:8])
            
            if not papers:
                logger.info(f"No papers found for target date ({target_str})")
                # Still try to update existing papers' categories_name and process summaries
                updated_count = self.update_categories_names()
                logger.info(f"Updated {updated_count} existing papers with category names")
                
                # Process papers for summarization (rate limited to 5 papers for free tier)
                summarized_count = self.process_papers_for_summarization()
                logger.info(f"Generated summaries for {summarized_count} papers")
                
                return updated_count + summarized_count
            
            # Create table if needed
            self.create_papers_table_if_not_exists()
            
            # Load papers to Supabase
            inserted_count = self.load_papers_to_supabase(papers)
            
            # Update existing papers' categories_name field
            updated_count = self.update_categories_names()
            
            # Process papers for summarization (rate limited to 5 papers for free tier)
            summarized_count = self.process_papers_for_summarization()
            
            logger.info(f"ETL pipeline completed successfully for {target_str}.")
            logger.info(f"Inserted {inserted_count} new papers, updated {updated_count} papers with category names, and generated summaries for {summarized_count} papers.")
            
            return inserted_count + updated_count + summarized_count
            
        except Exception as e:
            logger.error(f"ETL pipeline failed: {str(e)}")
            raise

    def download_pdf(self, pdf_url: str) -> Optional[str]:
        """Download PDF from URL and return the text content."""
        try:
            logger.debug(f"Downloading PDF from: {pdf_url}")
            
            # Download PDF with timeout and headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; ArxivETL/1.0; +https://example.com/bot)'
            }
            response = requests.get(pdf_url, headers=headers, timeout=30, stream=True)
            response.raise_for_status()
            
            # Read PDF content
            pdf_content = BytesIO(response.content)
            pdf_reader = PyPDF2.PdfReader(pdf_content)
            
            # Extract text from all pages (limit to first 10 pages for efficiency)
            text_content = ""
            max_pages = min(10, len(pdf_reader.pages))
            
            for page_num in range(max_pages):
                page = pdf_reader.pages[page_num]
                text_content += page.extract_text() + "\n"
            
            if not text_content.strip():
                logger.warning("No text extracted from PDF")
                return None
            
            # Clean up the text
            text_content = re.sub(r'\s+', ' ', text_content)  # Normalize whitespace
            text_content = text_content.strip()
            
            logger.debug(f"Extracted {len(text_content)} characters from PDF")
            return text_content
            
        except Exception as e:
            logger.error(f"Error downloading/processing PDF {pdf_url}: {str(e)}")
            return None
    
    def generate_summaries_with_gemini(self, paper_title: str, abstract: str, pdf_text: str, max_retries: int = 2) -> Optional[Dict[str, str]]:
        """Generate summaries using Gemini AI with retry logic for parsing failures."""
        if not self.gemini_enabled:
            logger.warning("Gemini AI not enabled, skipping summarization")
            return None
        
        for attempt in range(max_retries + 1):
            try:
                # Wait if needed to respect rate limits
                self.rate_limiter.wait_if_needed()
                
                # Prepare the content for Gemini (combine title, abstract, and PDF text)
                # Limit PDF text to avoid token limits
                max_pdf_length = 15000  # Adjust based on token limits
                truncated_pdf = pdf_text[:max_pdf_length] if pdf_text else ""
                
                content = f"""
Title: {paper_title}

Abstract: {abstract}

Paper Content (First part): {truncated_pdf}

Please analyze this research paper and provide six outputs with specific requirements:

**CRITICAL FORMATTING INSTRUCTIONS:**
- You MUST include all 6 sections below, in the exact order, with the exact section headers.
- Each section MUST start on a new line with the exact header format shown below.
- Never skip any section, even if you have to repeat or rephrase content.
- If you cannot generate a section, write: Not provided
- If you skip a section or use wrong formatting, the response will be rejected.
- DO NOT merge sections together or include section content within other sections.

**REQUIRED EXACT FORMAT:**

BEGINNER_TITLE: [your beginner title here]

INTERMEDIATE_TITLE: [your intermediate title here]

BEGINNER_OVERVIEW: [your one-sentence beginner overview here]

INTERMEDIATE_OVERVIEW: [your one-sentence intermediate overview here]

BEGINNER_SUMMARY: [your 150-200 word beginner summary here]

INTERMEDIATE_SUMMARY: [your 150-200 word intermediate summary here]

**CONTENT REQUIREMENTS:**

1. BEGINNER_TITLE: Create a simple, engaging title that anyone can understand. Make it accessible and interesting for a general audience without technical jargon.

2. INTERMEDIATE_TITLE: Create a moderately technical title that captures the essence of the research while being accessible to readers with some technical background.

3. BEGINNER_OVERVIEW: Write exactly ONE SENTENCE that explains what this research is about in the simplest terms possible. This should be clear and engaging for anyone to understand.

4. INTERMEDIATE_OVERVIEW: Write exactly ONE SENTENCE that summarizes the research for readers with technical knowledge, including key technical concepts but keeping it concise. **Do not skip this section.**

5. BEGINNER_SUMMARY: Write a 150-200 word summary that explains this research in simple terms. Focus on:
   - What problem they're trying to solve
   - What they did (in simple terms)
   - What they found
   - Why it matters to everyday people
   Keep it conversational and avoid technical jargon. Target exactly 150-200 words.

6. INTERMEDIATE_SUMMARY: Write a 150-200 word summary for readers with post-university education or technical knowledge. Include:
   - The specific research problem and methodology
   - Key technical findings and contributions
   - Implications for the field
   - Limitations and future work
   Use appropriate technical terminology but keep it accessible. Target exactly 150-200 words.

**EXAMPLE OF CORRECT FORMAT:**
BEGINNER_TITLE: Scientists Create Smart Computer That Learns Like Humans

INTERMEDIATE_TITLE: Novel Neural Architecture Demonstrates Human-Like Learning Patterns

BEGINNER_OVERVIEW: Researchers built a computer program that learns new tasks the same way people do.

INTERMEDIATE_OVERVIEW: This study presents a neural network architecture that mimics human cognitive learning mechanisms through attention-based feature selection.

BEGINNER_SUMMARY: [150-200 words explaining in simple terms]

INTERMEDIATE_SUMMARY: [150-200 words with technical details]

**NOW PROVIDE YOUR RESPONSE IN THE EXACT FORMAT ABOVE:**
"""

                attempt_msg = f" (attempt {attempt + 1}/{max_retries + 1})" if attempt > 0 else ""
                logger.info(f"Generating summaries with Gemini 2.5 Flash Lite{attempt_msg}")
                response = self.gemini_model.generate_content(content)
                
                if not response.text:
                    logger.error("Empty response from Gemini API")
                    if attempt < max_retries:
                        logger.info(f"Retrying due to empty response...")
                        continue
                    return None
                
                # Parse the response
                summaries = self.parse_gemini_response(response.text)
                if summaries:
                    success_msg = f"Successfully generated summaries with Gemini 2.5 Flash Lite"
                    if attempt > 0:
                        success_msg += f" on attempt {attempt + 1}"
                    logger.info(success_msg)
                    return summaries
                else:
                    if attempt < max_retries:
                        logger.warning(f"Parsing failed on attempt {attempt + 1}, retrying...")
                        continue
                    return None
                    
            except Exception as e:
                logger.error(f"Error generating summaries with Gemini (attempt {attempt + 1}): {str(e)}")
                if attempt < max_retries:
                    logger.info(f"Retrying due to exception...")
                    continue
                return None
        
        return None
    
    def parse_gemini_response(self, response_text: str) -> Optional[Dict[str, str]]:
        """Parse Gemini AI response to extract the six summaries with improved error handling."""
        try:
            # Clean up the response text
            response_text = response_text.strip()
            
            # More flexible regex patterns that handle various formatting
            patterns = {
                'beginner_title': [
                    r'BEGINNER_TITLE:\s*(.*?)(?=\n\s*INTERMEDIATE_TITLE:|$)',
                    r'BEGINNER_TITLE:\s*(.*?)(?=\n\n|\nINTERMEDIATE)',
                    r'BEGINNER_TITLE:\s*(.*?)(?=INTERMEDIATE_TITLE:)',
                    r'BEGINNER_TITLE:\s*(.*?)(?=\n)',  # Fallback: just get the line
                ],
                'intermediate_title': [
                    r'INTERMEDIATE_TITLE:\s*(.*?)(?=\n\s*BEGINNER_OVERVIEW:|$)',
                    r'INTERMEDIATE_TITLE:\s*(.*?)(?=\n\n|\nBEGINNER_OVERVIEW)',
                    r'INTERMEDIATE_TITLE:\s*(.*?)(?=BEGINNER_OVERVIEW:)',
                    r'INTERMEDIATE_TITLE:\s*(.*?)(?=\n)',  # Fallback: just get the line
                ],
                'beginner_overview': [
                    r'BEGINNER_OVERVIEW:\s*(.*?)(?=\n\s*INTERMEDIATE_OVERVIEW:|$)',
                    r'BEGINNER_OVERVIEW:\s*(.*?)(?=\n\n|\nINTERMEDIATE_OVERVIEW)',
                    r'BEGINNER_OVERVIEW:\s*(.*?)(?=INTERMEDIATE_OVERVIEW:)',
                    r'BEGINNER_OVERVIEW:\s*(.*?)(?=\n)',  # Fallback: just get the line
                ],
                'intermediate_overview': [
                    r'INTERMEDIATE_OVERVIEW:\s*(.*?)(?=\n\s*BEGINNER_SUMMARY:|$)',
                    r'INTERMEDIATE_OVERVIEW:\s*(.*?)(?=\n\n|\nBEGINNER_SUMMARY)',
                    r'INTERMEDIATE_OVERVIEW:\s*(.*?)(?=BEGINNER_SUMMARY:)',
                    r'INTERMEDIATE_OVERVIEW:\s*(.*?)(?=\n)',  # Fallback: just get the line
                    # Alternative formats Gemini might use
                    r'INTERMEDIATE OVERVIEW:\s*(.*?)(?=\n\s*BEGINNER_SUMMARY:|$)',
                    r'Intermediate Overview:\s*(.*?)(?=\n\s*BEGINNER_SUMMARY:|$)',
                ],
                'beginner_summary': [
                    r'BEGINNER_SUMMARY:\s*(.*?)(?=\n\s*INTERMEDIATE_SUMMARY:|$)',
                    r'BEGINNER_SUMMARY:\s*(.*?)(?=\n\n|\nINTERMEDIATE_SUMMARY)',
                    r'BEGINNER_SUMMARY:\s*(.*?)(?=INTERMEDIATE_SUMMARY:)',
                    # Try with different spacing and formatting
                    r'BEGINNER_SUMMARY:\s*(.*?)(?=\n\s*INTERMEDIATE)',
                ],
                'intermediate_summary': [
                    r'INTERMEDIATE_SUMMARY:\s*(.*?)(?:\n\n|$)',
                    r'INTERMEDIATE_SUMMARY:\s*(.*?)$',
                    # Since this is usually last, try to get everything after the header
                    r'INTERMEDIATE_SUMMARY:\s*(.*)',
                ]
            }
            
            summaries = {}
            
            # Try multiple regex patterns for each field
            for field_name, regex_list in patterns.items():
                extracted_content = None
                
                for regex_pattern in regex_list:
                    match = re.search(regex_pattern, response_text, re.DOTALL | re.IGNORECASE)
                    if match:
                        extracted_content = match.group(1).strip()
                        if extracted_content and len(extracted_content) > 10:  # Valid content
                            break
                
                # Special handling for intermediate_overview which seems to be the problem
                if not extracted_content and field_name == 'intermediate_overview':
                    # Try alternative searches for this specific field
                    alternative_patterns = [
                        r'(?:INTERMEDIATE_OVERVIEW|INTERMEDIATE OVERVIEW|Intermediate Overview):\s*(.*?)(?=\n\s*(?:BEGINNER_SUMMARY|Beginner Summary)|$)',
                        r'(?:INTERMEDIATE_OVERVIEW|INTERMEDIATE OVERVIEW|Intermediate Overview):\s*(.*?)(?=\n)',
                        # Look for content between beginner_overview and beginner_summary
                        r'BEGINNER_OVERVIEW:.*?\n\s*(.*?)(?=\n\s*(?:BEGINNER_SUMMARY|Beginner Summary))',
                    ]
                    
                    for alt_pattern in alternative_patterns:
                        match = re.search(alt_pattern, response_text, re.DOTALL | re.IGNORECASE)
                        if match:
                            extracted_content = match.group(1).strip()
                            # Clean up the content if it contains headers
                            if extracted_content.startswith(('INTERMEDIATE', 'Intermediate')):
                                # Extract just the content after any header
                                content_match = re.search(r'(?:INTERMEDIATE_OVERVIEW|INTERMEDIATE OVERVIEW|Intermediate Overview):\s*(.*)', extracted_content, re.DOTALL)
                                if content_match:
                                    extracted_content = content_match.group(1).strip()
                            if extracted_content and len(extracted_content) > 10:
                                logger.info(f"Found {field_name} using alternative pattern")
                                break
                
                if not extracted_content:
                    logger.error(f"Could not extract {field_name} from Gemini response")
                    logger.debug(f"Full response for debugging:\n{response_text}")
                    return None
                
                summaries[field_name] = extracted_content
            
            # Final validation
            for key, value in summaries.items():
                if not value or len(value) < 10:
                    logger.error(f"Generated {key} is too short or empty: '{value}'")
                    return None
            
            logger.info(f"Successfully parsed all 6 sections from Gemini response")
            return summaries
            
        except Exception as e:
            logger.error(f"Error parsing Gemini response: {str(e)}")
            logger.debug(f"Response text length: {len(response_text)}")
            logger.debug(f"Response preview: {response_text[:500]}...")
            return None
    
    def save_summary_to_database(self, paper_id: int, arxiv_id: str, summaries: Dict[str, str]) -> bool:
        """Save generated summaries to the summary_papers table."""
        try:
            summary_data = {
                'arxiv_paper_id': paper_id,
                'arxiv_id': arxiv_id,
                'beginner_title': summaries['beginner_title'],
                'intermediate_title': summaries['intermediate_title'],
                'beginner_overview': summaries['beginner_overview'],
                'intermediate_overview': summaries['intermediate_overview'],
                'beginner_summary': summaries['beginner_summary'],
                'intermediate_summary': summaries['intermediate_summary'],
                'processing_status': 'completed',
                'gemini_model': 'gemini-2.5-flash-lite'
            }
            
            response = self.supabase.table('summary_papers').insert(summary_data).execute()
            
            if response.data:
                logger.info(f"Successfully saved summary for paper {arxiv_id}")
                return True
            else:
                logger.error(f"Failed to save summary for paper {arxiv_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error saving summary to database: {str(e)}")
            # Try to save error status
            try:
                error_data = {
                    'arxiv_paper_id': paper_id,
                    'arxiv_id': arxiv_id,
                    'beginner_title': 'Error during processing',
                    'intermediate_title': 'Error during processing',
                    'beginner_overview': 'Error during processing',
                    'intermediate_overview': 'Error during processing',
                    'beginner_summary': 'Summary generation failed',
                    'intermediate_summary': 'Summary generation failed',
                    'processing_status': 'error',
                    'processing_error': str(e),
                    'gemini_model': 'gemini-2.5-flash-lite'
                }
                self.supabase.table('summary_papers').insert(error_data).execute()
            except:
                pass  # If we can't even save the error, just log it
            return False
    
    def process_papers_for_summarization(self, limit: int = 5) -> int:
        """Process papers that need summarization with Gemini AI."""
        if not self.gemini_enabled:
            logger.info("Gemini AI not enabled, skipping paper summarization")
            return 0
        
        try:
            logger.info("Finding papers that need summarization")
            logger.info(f"Processing up to {limit} papers (rate limited to 15 req/min for free tier)")
            
            # Get papers that need summarization
            papers_response = self.supabase.table('v_papers_needing_summaries').select('*').limit(limit).execute()
            
            if not papers_response.data:
                logger.info("No papers found that need summarization")
                return 0
            
            logger.info(f"Found {len(papers_response.data)} papers to process")
            processed_count = 0
            retry_count = 0
            
            for i, paper in enumerate(papers_response.data, 1):
                try:
                    paper_id = paper['id']
                    arxiv_id = paper['arxiv_id']
                    title = paper['title']
                    abstract = paper['abstract']
                    pdf_url = paper['pdf_url']
                    
                    logger.info(f"Processing paper {i}/{len(papers_response.data)}: {arxiv_id}")
                    
                    # Download and extract PDF text
                    pdf_text = self.download_pdf(pdf_url)
                    if not pdf_text:
                        logger.warning(f"Could not extract text from PDF for {arxiv_id}, using abstract only")
                        pdf_text = ""
                    
                    # Generate summaries with Gemini (includes retry logic)
                    summaries = self.generate_summaries_with_gemini(title, abstract, pdf_text, max_retries=2)
                    
                    if summaries:
                        # Save to database
                        if self.save_summary_to_database(paper_id, arxiv_id, summaries):
                            processed_count += 1
                            logger.info(f"✅ Successfully processed paper {arxiv_id}")
                        else:
                            logger.error(f"❌ Failed to save summary for paper {arxiv_id}")
                    else:
                        logger.error(f"❌ Failed to generate summaries for paper {arxiv_id}")
                    
                    # Progress update
                    if i % 5 == 0:
                        logger.info(f"Progress: {i}/{len(papers_response.data)} papers processed, {processed_count} successful")
                    
                except Exception as e:
                    logger.error(f"Error processing paper {paper.get('arxiv_id', 'unknown')}: {str(e)}")
                    continue
            
            success_rate = (processed_count / len(papers_response.data)) * 100
            logger.info(f"Successfully processed {processed_count}/{len(papers_response.data)} papers ({success_rate:.1f}% success rate)")
            
            if processed_count < len(papers_response.data):
                failed_count = len(papers_response.data) - processed_count
                logger.warning(f"{failed_count} papers failed processing - check logs for details")
            
            return processed_count
            
        except Exception as e:
            logger.error(f"Error in process_papers_for_summarization: {str(e)}")
            return 0

def main():
    """Main function to run the ETL pipeline."""
    try:
        etl = ArxivETL()
        result = etl.run_daily_etl()
        print(f"ETL completed successfully. Inserted {result} new papers.")
        return 0
    except Exception as e:
        logger.error(f"ETL failed: {str(e)}")
        print(f"ETL failed: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 