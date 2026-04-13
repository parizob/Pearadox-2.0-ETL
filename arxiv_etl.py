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
    """
    Rate limiter for Gemini API to stay within free tier limits.
    
    Implements a strict sliding window: You must wait 60 seconds from the FIRST request
    in the window before making request #11. For example:
    - Request 1 at 10:00:30
    - Requests 2-10 at 10:00:31-10:00:39
    - Request 11 can only happen at 10:01:30 (60s after request 1)
    """
    
    def __init__(self, max_requests_per_minute=10):
        self.max_requests_per_minute = max_requests_per_minute
        self.requests_made = []
        self.lock = threading.Lock()
    
    def wait_if_needed(self):
        """Wait if necessary to respect rate limits using strict sliding window."""
        with self.lock:
            now = datetime.now()
            
            # Remove requests older than 60 seconds
            cutoff_time = now - timedelta(seconds=60)
            self.requests_made = [req_time for req_time in self.requests_made 
                                if req_time > cutoff_time]
            
            # If we're at the limit, wait until 60 seconds have passed since the FIRST request
            if len(self.requests_made) >= self.max_requests_per_minute:
                # Find the oldest (first) request in the current window
                oldest_request = min(self.requests_made)
                # Calculate how long until 60 seconds have passed since that first request
                elapsed_since_first = (now - oldest_request).total_seconds()
                wait_time = 60 - elapsed_since_first
                
                if wait_time > 0:
                    logger.info(f"Rate limit reached ({len(self.requests_made)}/{self.max_requests_per_minute} requests). "
                              f"Waiting {wait_time:.1f}s until 60s have passed since first request in window...")
                    time.sleep(wait_time + 0.1)  # Add 100ms buffer for safety
                    
                    # Clean up again after waiting
                    now = datetime.now()
                    cutoff_time = now - timedelta(seconds=60)
                    self.requests_made = [req_time for req_time in self.requests_made 
                                        if req_time > cutoff_time]
            
            # Record this request
            self.requests_made.append(now)
            logger.debug(f"API requests in current 60s window: {len(self.requests_made)}/{self.max_requests_per_minute}")

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
                # Initialize rate limiter for free tier: 10 requests per minute
                self.rate_limiter = RateLimiter(max_requests_per_minute=10)
                logger.info("Gemini 2.5 Flash Lite configured successfully with rate limiting (10 req/min)")
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
        
        # Commercial relevance keywords for filtering papers
        # These indicate papers with practical/commercial applications vs purely theoretical
        self.commercial_keywords = {
            # High-value keywords (weight 3) - direct commercial/practical applications
            'high': [
                'production', 'deploy', 'deployment', 'real-world', 'real world', 'industry',
                'enterprise', 'commercial', 'product', 'application', 'practical', 'scalable',
                'efficient', 'cost-effective', 'low-latency', 'real-time', 'realtime',
                'edge device', 'mobile', 'on-device', 'lightweight', 'fast inference',
                'api', 'saas', 'platform', 'tool', 'framework', 'library', 'sdk',
                'startup', 'business', 'customer', 'user experience', 'ux',
                'healthcare', 'medical', 'clinical', 'diagnosis', 'drug discovery',
                'finance', 'trading', 'fraud detection', 'risk', 'fintech',
                'autonomous', 'self-driving', 'robotics', 'drone', 'manufacturing',
                'e-commerce', 'recommendation', 'personalization', 'search engine',
                'chatbot', 'virtual assistant', 'conversational', 'dialogue',
                'code generation', 'copilot', 'developer tools', 'automation',
                'security', 'cybersecurity', 'privacy', 'federated learning',
                'energy efficient', 'green ai', 'sustainable', 'carbon',
                'multimodal', 'vision-language', 'text-to-image', 'image-to-text',
                'speech recognition', 'text-to-speech', 'voice', 'audio',
                'video generation', 'video understanding', 'streaming',
            ],
            # Medium-value keywords (weight 2) - promising research directions
            'medium': [
                'benchmark', 'state-of-the-art', 'sota', 'outperform', 'surpass',
                'improvement', 'better than', 'faster than', 'more efficient',
                'fine-tuning', 'fine tuning', 'transfer learning', 'pretrained',
                'instruction tuning', 'rlhf', 'alignment', 'safety',
                'reasoning', 'chain-of-thought', 'cot', 'planning', 'agent',
                'retrieval', 'rag', 'knowledge base', 'grounding',
                'compression', 'quantization', 'pruning', 'distillation',
                'open source', 'open-source', 'reproducible', 'dataset',
                'evaluation', 'metric', 'leaderboard', 'competition',
                'human evaluation', 'user study', 'ablation',
                'zero-shot', 'few-shot', 'in-context learning',
                'long context', 'context window', 'memory',
                'hallucination', 'factual', 'truthful', 'reliable',
                'robust', 'adversarial', 'attack', 'defense',
                'interpretable', 'explainable', 'xai', 'transparent',
                'bias', 'fairness', 'ethical', 'responsible ai',
            ],
            # Low-value keywords (weight 1) - general AI terms that add some relevance
            'low': [
                'novel', 'new', 'propose', 'introduce', 'present',
                'model', 'architecture', 'network', 'layer',
                'training', 'optimization', 'learning rate', 'convergence',
                'accuracy', 'performance', 'results', 'experiments',
                'language model', 'vision model', 'foundation model',
                'attention', 'self-attention', 'cross-attention',
                'encoder', 'decoder', 'embedding', 'representation',
            ]
        }
        
        # Maximum number of papers to process (due to Gemini rate limits)
        self.max_papers_to_process = 50
    
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
    
    def score_paper_commercial_relevance(self, paper: Dict[str, Any]) -> int:
        """
        Score a paper's commercial relevance based on title and abstract keywords.
        This is a cheap, fast operation that doesn't require any API calls.
        
        Args:
            paper: Paper dict with 'title' and 'abstract' fields
            
        Returns:
            Integer score (higher = more commercially relevant)
        """
        title = paper.get('title', '').lower()
        abstract = paper.get('abstract', '').lower()
        
        # Combine title and abstract for searching
        # Title matches are weighted 2x more than abstract matches
        text_to_search = abstract
        
        score = 0
        matched_keywords = []
        
        # Check high-value keywords (weight 3)
        for keyword in self.commercial_keywords['high']:
            keyword_lower = keyword.lower()
            # Title match = 6 points (3 * 2)
            if keyword_lower in title:
                score += 6
                matched_keywords.append(f"{keyword}(title)")
            # Abstract match = 3 points
            elif keyword_lower in text_to_search:
                score += 3
                matched_keywords.append(keyword)
        
        # Check medium-value keywords (weight 2)
        for keyword in self.commercial_keywords['medium']:
            keyword_lower = keyword.lower()
            # Title match = 4 points (2 * 2)
            if keyword_lower in title:
                score += 4
                matched_keywords.append(f"{keyword}(title)")
            # Abstract match = 2 points
            elif keyword_lower in text_to_search:
                score += 2
                matched_keywords.append(keyword)
        
        # Check low-value keywords (weight 1)
        for keyword in self.commercial_keywords['low']:
            keyword_lower = keyword.lower()
            # Title match = 2 points (1 * 2)
            if keyword_lower in title:
                score += 2
                matched_keywords.append(f"{keyword}(title)")
            # Abstract match = 1 point
            elif keyword_lower in text_to_search:
                score += 1
                matched_keywords.append(keyword)
        
        # Store matched keywords for debugging
        paper['_commercial_score'] = score
        paper['_matched_keywords'] = matched_keywords[:10]  # Limit for logging
        
        return score
    
    def filter_papers_by_commercial_relevance(self, papers: List[Dict[str, Any]], max_papers: int = None) -> List[Dict[str, Any]]:
        """
        Filter papers to only include the most commercially relevant ones.
        This is a cheap pre-filtering step that scans titles/abstracts without using any API.
        
        Args:
            papers: List of paper dicts from arXiv
            max_papers: Maximum number of papers to return (default: self.max_papers_to_process)
            
        Returns:
            List of top N most commercially relevant papers, sorted by score
        """
        if max_papers is None:
            max_papers = self.max_papers_to_process
        
        if not papers:
            return []
        
        logger.info(f"Pre-filtering {len(papers)} papers for commercial relevance...")
        
        # Score all papers
        for paper in papers:
            self.score_paper_commercial_relevance(paper)
        
        # Sort by commercial relevance score (descending)
        sorted_papers = sorted(papers, key=lambda p: p.get('_commercial_score', 0), reverse=True)
        
        # Log score distribution
        scores = [p.get('_commercial_score', 0) for p in sorted_papers]
        if scores:
            avg_score = sum(scores) / len(scores)
            max_score = max(scores)
            min_score = min(scores)
            logger.info(f"Score distribution - Max: {max_score}, Min: {min_score}, Avg: {avg_score:.1f}")
        
        # Take top N papers
        selected_papers = sorted_papers[:max_papers]
        
        # Log the selection
        if selected_papers:
            selected_scores = [p.get('_commercial_score', 0) for p in selected_papers]
            cutoff_score = min(selected_scores)
            logger.info(f"Selected top {len(selected_papers)} papers (score cutoff: {cutoff_score})")
            
            # Log top 5 papers for visibility
            logger.info("Top 5 commercially relevant papers:")
            for i, paper in enumerate(selected_papers[:5], 1):
                score = paper.get('_commercial_score', 0)
                keywords = paper.get('_matched_keywords', [])[:5]
                logger.info(f"  {i}. [{score}pts] {paper.get('arxiv_id')}: {paper.get('title', '')[:60]}...")
                if keywords:
                    logger.info(f"      Keywords: {', '.join(keywords)}")
        
        # Clean up temporary scoring fields before returning
        for paper in selected_papers:
            paper.pop('_commercial_score', None)
            paper.pop('_matched_keywords', None)
        
        rejected_count = len(papers) - len(selected_papers)
        if rejected_count > 0:
            logger.info(f"Filtered out {rejected_count} papers with lower commercial relevance")
        
        return selected_papers
    
    def get_today_date_range(self) -> tuple:
        """Get the date range for papers from the previous publication day."""
        from datetime import timedelta
        
        today = datetime.now()
        
        # Determine target date based on day of week
        # If Monday (weekday 0), get Friday's papers (3 days ago)
        # Otherwise, get yesterday's papers (1 day ago)
        if today.weekday() == 0:  # Monday
            target_date = today - timedelta(days=3)  # Friday
            day_description = "FRIDAY'S PUBLICATIONS (weekend skip)"
        else:
            target_date = today - timedelta(days=1)  # Yesterday
            day_description = "PREVIOUS DAY'S PUBLICATIONS"
        
        # Set date range for target date (00:00 to 23:59)
        start_date = target_date.strftime('%Y%m%d0000')
        end_date = target_date.strftime('%Y%m%d2359')
        
        logger.info(f"Fetching papers from {day_description}: {target_date.strftime('%Y-%m-%d')}")
        logger.info(f"Date range: {start_date} to {end_date}")
        return start_date, end_date
    
    def is_paper_in_date_range(self, paper_date: str) -> bool:
        """Check if a paper is from the target date (yesterday or Friday if Monday)."""
        from datetime import timedelta
        try:
            # Parse the paper's published date
            paper_dt = datetime.strptime(paper_date, '%Y-%m-%dT%H:%M:%SZ')
            paper_date_only = paper_dt.date()
            
            # Determine target date based on day of week
            today = datetime.now()
            if today.weekday() == 0:  # Monday
                target_date = (today - timedelta(days=3)).date()  # Friday
            else:
                target_date = (today - timedelta(days=1)).date()  # Yesterday
            
            return paper_date_only == target_date
        except Exception as e:
            logger.warning(f"Could not parse date {paper_date}: {str(e)}")
            return False
    
    def build_arxiv_query(self, start_date: str, end_date: str, max_results: int = 2000) -> str:
        """Build arXiv API query for AI papers from today."""
        # Build category query for AI-related categories
        category_query = ' OR '.join([f'cat:{cat}' for cat in self.ai_categories])
        
        # Query for papers in the specified date range
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
        
        arxiv_headers = {
            'User-Agent': 'PearadoxETL/2.0 (https://github.com/pearadox; mailto:pearadox@example.com)',
            'Accept': 'application/atom+xml, application/xml, text/xml',
        }
        
        max_retries = 5
        backoff = 10  # seconds

        try:
            # Make request to arXiv API with retries and exponential backoff
            response = None
            for attempt in range(1, max_retries + 1):
                try:
                    response = requests.get(query_url, headers=arxiv_headers, timeout=60)
                    response.raise_for_status()
                    break
                except requests.HTTPError as http_err:
                    status = http_err.response.status_code if http_err.response is not None else None
                    if status in (429, 503) or (status and status >= 500):
                        wait = backoff * (2 ** (attempt - 1))
                        logger.warning(f"arXiv returned {status} on attempt {attempt}/{max_retries}. Retrying in {wait}s...")
                        time.sleep(wait)
                    else:
                        raise
                except requests.ConnectionError as conn_err:
                    wait = backoff * (2 ** (attempt - 1))
                    logger.warning(f"Connection error on attempt {attempt}/{max_retries}: {conn_err}. Retrying in {wait}s...")
                    time.sleep(wait)
            else:
                raise RuntimeError(f"arXiv API failed after {max_retries} attempts")
            
            if response is None:
                raise RuntimeError("No response received from arXiv API")
            
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
            
            # Try to extract PDF URL from links first
            if hasattr(entry, 'links'):
                for link in entry.links:
                    if link.type == 'application/pdf':
                        pdf_url = link.href
                        break
            
            # If PDF URL not found in links, construct it from arxiv_id
            # arXiv PDF URLs follow a predictable pattern: https://arxiv.org/pdf/{arxiv_id}.pdf
            if not pdf_url:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                logger.debug(f"Constructed PDF URL for {arxiv_id}: {pdf_url}")
            
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
        """Run the ETL pipeline to extract papers from previous publication day.
        
        Due to Gemini API rate limits, we now:
        1. Fetch ALL papers from arXiv for the target date
        2. Pre-filter using cheap keyword matching on titles/abstracts
        3. Only load the top 50 most commercially relevant papers to Supabase
        """
        from datetime import timedelta
        
        today = datetime.now()
        if today.weekday() == 0:  # Monday
            target_date = today - timedelta(days=3)  # Friday
            logger.info(f"Starting daily arXiv ETL pipeline for FRIDAY'S PUBLICATIONS (weekend skip): {target_date.strftime('%Y-%m-%d')}")
        else:
            target_date = today - timedelta(days=1)  # Yesterday
            logger.info(f"Starting daily arXiv ETL pipeline for PREVIOUS DAY'S PUBLICATIONS: {target_date.strftime('%Y-%m-%d')}")
        
        try:
            # Get target date range
            start_date, end_date = self.get_today_date_range()
            
            # Extract ALL papers from arXiv for the target date
            all_papers = self.extract_papers_from_arxiv(start_date, end_date, start_date[:8])
            
            if not all_papers:
                logger.info("No papers found for today")
                # Still try to update existing papers' categories_name
                updated_count = self.update_categories_names()
                logger.info(f"Updated {updated_count} existing papers with category names")
                
                return updated_count
            
            # Pre-filter papers by commercial relevance (cheap keyword-based filtering)
            # This reduces the number of papers we send to the LLM
            logger.info(f"Total papers extracted from arXiv: {len(all_papers)}")
            papers = self.filter_papers_by_commercial_relevance(all_papers, max_papers=self.max_papers_to_process)
            logger.info(f"Papers after commercial relevance filtering: {len(papers)} (max: {self.max_papers_to_process})")
            
            # Create table if needed
            self.create_papers_table_if_not_exists()
            
            # Load only the filtered papers to Supabase
            inserted_count = self.load_papers_to_supabase(papers)
            
            # Update existing papers' categories_name field
            updated_count = self.update_categories_names()
            
            # Log completion message with target date
            from datetime import timedelta
            today = datetime.now()
            if today.weekday() == 0:  # Monday
                target_date = today - timedelta(days=3)  # Friday
                date_desc = f"Friday's papers ({target_date.strftime('%Y-%m-%d')})"
            else:
                target_date = today - timedelta(days=1)  # Yesterday
                date_desc = f"previous day's papers ({target_date.strftime('%Y-%m-%d')})"
            
            logger.info(f"ETL pipeline completed successfully for {date_desc}.")
            logger.info(f"Filtered {len(all_papers)} papers down to {len(papers)} by commercial relevance.")
            logger.info(f"Inserted {inserted_count} new papers, updated {updated_count} papers with category names.")
            logger.info(f"Run process_summaries.py to generate AI summaries for these papers.")
            
            return inserted_count + updated_count
            
        except Exception as e:
            logger.error(f"ETL pipeline failed: {str(e)}")
            raise

    def clean_text_for_utf8(self, text: str) -> str:
        """Clean text to handle UTF-8 encoding issues and surrogates."""
        if not text:
            return ""
        
        try:
            # Remove surrogates and invalid UTF-8 characters
            cleaned_text = text.encode("utf-8", "ignore").decode("utf-8", "ignore")
            
            # Remove any remaining problematic characters
            cleaned_text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', cleaned_text)
            
            # Normalize whitespace
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
            
            return cleaned_text.strip()
        except Exception as e:
            logger.warning(f"Error cleaning text: {str(e)}")
            # Fallback: try to return a basic cleaned version
            try:
                return ''.join(char for char in text if ord(char) < 127)
            except:
                return "Text cleaning failed"

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
                try:
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text:
                        # Clean each page's text for UTF-8 issues
                        cleaned_page_text = self.clean_text_for_utf8(page_text)
                        text_content += cleaned_page_text + "\n"
                except Exception as e:
                    logger.warning(f"Error extracting text from page {page_num}: {str(e)}")
                    continue
            
            if not text_content.strip():
                logger.warning("No text extracted from PDF")
                return None
            
            # Final cleanup of the combined text
            text_content = self.clean_text_for_utf8(text_content)
            
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
                
                # Clean all input text to prevent UTF-8 encoding issues
                cleaned_title = self.clean_text_for_utf8(paper_title)
                cleaned_abstract = self.clean_text_for_utf8(abstract)
                cleaned_pdf_text = self.clean_text_for_utf8(pdf_text) if pdf_text else ""
                
                # Prepare the content for Gemini (combine title, abstract, and PDF text)
                # Limit PDF text to avoid token limits
                max_pdf_length = 15000  # Adjust based on token limits
                truncated_pdf = cleaned_pdf_text[:max_pdf_length] if cleaned_pdf_text else ""
                
                content = f"""
Title: {cleaned_title}

Abstract: {cleaned_abstract}

Paper Content (First part): {truncated_pdf}

You are an exceptional science writer who makes research come alive with emotional resonance. Your goal is to make readers FEEL something powerful about this research—whether that's awe, excitement, and wonder for breakthroughs that could transform lives, or genuine concern, urgency, and alarm for research with potentially harmful implications.

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

**EMOTIONAL IMPACT GUIDELINES:**

First, assess the research's potential impact:
- **Positive/Beneficial Impact**: Research that could save lives, solve major problems, democratize technology, enhance human capabilities, or improve quality of life should evoke AWE, EXCITEMENT, and AMAZEMENT. Use language that makes readers feel inspired, hopeful, and energized about the future.
- **Negative/Concerning Impact**: Research that could enable surveillance, manipulation, job displacement, environmental harm, weapons, bias amplification, or concentration of power should evoke CONCERN, URGENCY, and THOUGHTFUL ALARM. Use language that makes readers feel the weight of these implications and the need for caution.
- **Mixed Impact**: Many papers have both positive potential and risks—acknowledge both sides with appropriate emotional weight.

**CONTENT REQUIREMENTS:**

1. BEGINNER_TITLE: Create a vivid, emotionally resonant title that captures the human stakes of this research. For beneficial research, use words that spark wonder (e.g., "breakthrough," "revolutionary," "remarkable"). For concerning research, use words that convey gravity (e.g., "raises alarms," "critical questions," "troubling implications"). Avoid jargon but pack emotional punch.

2. INTERMEDIATE_TITLE: Create a moderately technical title that still conveys emotional weight. Balance precision with impact—let the significance shine through even for technical readers.

3. BEGINNER_OVERVIEW: Write exactly ONE SENTENCE that immediately hooks readers emotionally. For beneficial research, make them feel the excitement of possibility. For concerning research, make them feel why this matters urgently. This sentence should make someone stop scrolling and read more.

4. INTERMEDIATE_OVERVIEW: Write exactly ONE SENTENCE that conveys both the technical substance and the emotional stakes for readers with technical knowledge. **Do not skip this section.**

5. BEGINNER_SUMMARY: Write a 150-200 word summary that triggers powerful emotional responses. This is your chance to make readers FEEL something profound:

   **FOR BENEFICIAL/EXCITING RESEARCH - Evoke AWE, EXCITEMENT, AMAZEMENT:**
   - Start with a mind-blowing hook: "What if...?" or "For the first time in history..."
   - Use vivid imagery that sparks wonder and imagination
   - Show the human impact with specific, relatable scenarios
   - Build to a crescendo of possibility and hope
   - Use emotionally charged words: "remarkable," "astonishing," "game-changing," "breathtaking," "finally"
   - Make readers feel like they're witnessing history being made
   - End with an inspiring vision of the future this enables

   **FOR CONCERNING/RISKY RESEARCH - Evoke CONCERN, ANXIETY, URGENCY:**
   - Start with a wake-up call: "Here's what keeps researchers up at night..."
   - Make the threat feel real and immediate, not abstract
   - Use visceral language that creates genuine unease
   - Show what's at stake for ordinary people
   - Use words that convey gravity: "alarming," "troubling," "urgent," "we need to talk about," "before it's too late"
   - Create a sense that action or awareness is needed NOW
   - End with a call for vigilance or thoughtful consideration

   Keep it conversational and jargon-free. The reader should finish with their heart racing—either from excitement or concern. Target exactly 150-200 words.

6. INTERMEDIATE_SUMMARY: Write a 150-200 word summary for technical readers that still creates emotional impact. Even experts deserve to feel something:

   **FOR BENEFICIAL/EXCITING RESEARCH - Make experts feel the thrill:**
   - Frame the technical achievement as genuinely impressive, even to those who understand the difficulty
   - Highlight what makes this a breakthrough, not just an incremental improvement
   - Use confident, energized language: "remarkably," "elegantly solves," "opens entirely new possibilities"
   - Show implications that would excite a researcher in the field
   - Convey that this could reshape how we approach the problem

   **FOR CONCERNING/RISKY RESEARCH - Make experts feel the weight:**
   - Frame the technical capability in terms of its dual-use potential
   - Be direct about security, ethical, or societal implications
   - Use sobering language: "raises serious questions," "demands careful consideration," "the implications are concerning"
   - Acknowledge the sophistication while questioning the safeguards
   - Convey that the research community needs to grapple with this

   Use appropriate technical terminology but write with conviction. Technical accuracy and emotional resonance are not mutually exclusive. Target exactly 150-200 words.

**EXAMPLE OF CORRECT FORMAT (Beneficial Research):**
BEGINNER_TITLE: Scientists Crack Code That Could End Cancer's Deadly Grip Forever

INTERMEDIATE_TITLE: Groundbreaking Protein Folding Discovery Opens Unprecedented Cancer Treatment Pathways

BEGINNER_OVERVIEW: In a discovery that could save millions of lives, researchers have found a way to predict exactly how cancer cells protect themselves—and how to destroy that protection.

INTERMEDIATE_OVERVIEW: This landmark study demonstrates a novel computational approach to predicting oncogenic protein conformations with 94% accuracy, potentially revolutionizing targeted therapy development.

BEGINNER_SUMMARY: What if we could see exactly how cancer hides from our immune system—and finally strip away its defenses? That's precisely what researchers have achieved in this remarkable breakthrough. For decades, scientists have been fighting blind, unable to predict how cancer cells shape their protective proteins. Now, using artificial intelligence, they've cracked the code. Imagine a future where doctors can design treatments tailored to attack YOUR specific cancer's weak points. Where chemotherapy's brutal side effects become a thing of the past. Where a diagnosis isn't a death sentence but the start of a precisely targeted counterattack. The results are stunning: the AI predicted protein shapes with 94% accuracy, turning months of laboratory guesswork into seconds of computation. This isn't incremental progress—it's a quantum leap. For the 10 million people who die from cancer each year, and the millions more who love them, this research represents something extraordinary: hope, backed by hard science. The war on cancer just got a powerful new weapon.

INTERMEDIATE_SUMMARY: This study represents a watershed moment in computational oncology. The researchers developed a transformer-based architecture that predicts oncogenic protein conformational states with 94% accuracy—a remarkable improvement over existing methods that struggle to exceed 70%. What makes this technically impressive isn't just the accuracy; it's the model's ability to generalize across mutation types without task-specific fine-tuning. The implications for drug discovery are profound. Current targeted therapy development is bottlenecked by expensive, time-consuming crystallography studies. This approach could compress years of structural biology work into computational predictions, dramatically accelerating the pipeline from mutation identification to therapeutic candidate. The model's attention mechanisms reveal interpretable binding site predictions, enabling rational drug design rather than brute-force screening. Limitations exist—the training set underrepresents rare cancer subtypes, and experimental validation remains essential. But the paradigm shift is clear: we're moving from reactive to predictive oncology. For researchers who've spent careers fighting protein folding complexity, this work demonstrates that the problem is finally yielding to modern deep learning approaches.

**EXAMPLE OF CORRECT FORMAT (Concerning Research):**
BEGINNER_TITLE: New AI Can Fake Anyone's Voice Perfectly—And Researchers Are Worried

INTERMEDIATE_TITLE: Zero-Shot Voice Cloning Breakthrough Raises Urgent Questions About Digital Identity

BEGINNER_OVERVIEW: A new AI system can clone anyone's voice from just three seconds of audio, and experts say we're not ready for what comes next.

INTERMEDIATE_OVERVIEW: This study presents a zero-shot voice synthesis model achieving human-indistinguishable output, amplifying critical concerns about authentication security and synthetic media proliferation.

BEGINNER_SUMMARY: Here's a scenario that should make you uncomfortable: Someone calls your elderly parent, sounding exactly like you, asking for emergency money. The voice is perfect. The panic sounds real. And it's completely fake. This is now possible, and it's terrifyingly easy. Researchers have created an AI that needs just three seconds of anyone's voice to create a flawless clone. Three seconds—that's a voicemail greeting, a video clip, a podcast snippet. Your voice is no longer yours alone. The implications are chilling. Phone scams could become undetectable. Political leaders could be impersonated saying things they never said. Evidence in court cases could be fabricated. Your voice could authorize bank transfers you never made. While the researchers focused on legitimate uses like helping people who've lost their voices, they've also opened Pandora's box. There are currently no reliable ways to detect these fakes. No regulations to prevent misuse. No safeguards in place. This isn't a future threat—it's happening now, and we're not ready.

INTERMEDIATE_SUMMARY: This paper presents a technically impressive and deeply concerning advancement in voice synthesis. The zero-shot approach eliminates the traditional requirement for speaker-specific training data, achieving human-indistinguishable output from just three seconds of reference audio. The architecture combines a neural codec with a diffusion-based prosody model, enabling natural intonation patterns that defeat current detection systems. From a security perspective, this research is alarming. Voice authentication systems—used by banks, government agencies, and enterprises—were already vulnerable; this makes them essentially obsolete. The 0.8% equal error rate for human detection means listeners cannot reliably identify synthetic speech. The authors acknowledge dual-use concerns but offer only suggestions for future watermarking research. The responsible disclosure debate is relevant here: by publishing full methodology, the researchers have democratized a capability previously limited to well-resourced actors. Detection countermeasures are now in an arms race with synthesis advances. The research community and policymakers must urgently address the authentication crisis this creates before the inevitable wave of sophisticated voice-based fraud and disinformation.

**NOW PROVIDE YOUR RESPONSE IN THE EXACT FORMAT ABOVE:**
"""

                attempt_msg = f" (attempt {attempt + 1}/{max_retries + 1})" if attempt > 0 else ""
                logger.info(f"Generating summaries with Gemini 2.5 Flash Lite{attempt_msg}")
                
                # Additional safety: ensure content is properly encoded
                try:
                    content_bytes = content.encode('utf-8', 'ignore')
                    content = content_bytes.decode('utf-8', 'ignore')
                except Exception as encoding_error:
                    logger.warning(f"Content encoding issue: {str(encoding_error)}")
                
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
            logger.info(f"Processing up to {limit} papers (rate limited to 10 req/min for free tier)")
            
            # Get papers that need summarization with retry logic for timeout issues
            papers_response = None
            max_retries = 3
            
            for attempt in range(max_retries):
                try:
                    papers_response = self.supabase.table('v_papers_needing_summaries').select('*').limit(limit).execute()
                    break  # Success, exit retry loop
                except Exception as e:
                    error_msg = str(e)
                    if 'timeout' in error_msg.lower() or '57014' in error_msg:
                        logger.warning(f"Query timeout on attempt {attempt + 1}/{max_retries}, retrying...")
                        time.sleep(2 * (attempt + 1))  # Exponential backoff: 2s, 4s, 6s
                        if attempt == max_retries - 1:
                            logger.error(f"Query failed after {max_retries} attempts due to timeout")
                            return 0
                    else:
                        raise  # Re-raise non-timeout errors
            
            if not papers_response or not papers_response.data:
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