#!/usr/bin/env python3
"""
ArXiv AI Papers ETL Pipeline
Extracts AI science papers from arXiv API and loads them into Supabase database.
"""

import os
import sys
import logging
import feedparser
import requests
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from supabase import create_client, Client
from dotenv import load_dotenv
import time
import re

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

class ArxivETL:
    """ETL pipeline for extracting AI papers from arXiv and loading to Supabase."""
    
    def __init__(self):
        """Initialize the ETL pipeline with Supabase client and arXiv API configuration."""
        # Supabase configuration
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_ANON_KEY')
        
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("Missing Supabase credentials in environment variables")
        
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
        
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
        """Get the date range for yesterday's papers (arXiv publishes papers the day before)."""
        yesterday = datetime.now() - timedelta(days=1)
        # Use yesterday's date since arXiv publishes papers the day before
        start_date = yesterday.strftime('%Y%m%d0000')  # Start of yesterday
        end_date = yesterday.strftime('%Y%m%d2359')   # End of yesterday
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
        """Run the complete ETL pipeline for yesterday's papers (arXiv's latest publications)."""
        yesterday = datetime.now() - timedelta(days=1)
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        logger.info(f"Starting daily arXiv ETL pipeline for YESTERDAY'S PUBLICATIONS: {yesterday_str}")
        logger.info("Note: arXiv publishes papers the day before they appear on the site")
        
        try:
            # Get yesterday's date range
            start_date, end_date = self.get_today_date_range()
            
            # Extract papers from arXiv (will be filtered to yesterday only)
            papers = self.extract_papers_from_arxiv(start_date, end_date, start_date[:8])
            
            if not papers:
                logger.info(f"No papers found for yesterday ({yesterday_str})")
                # Still try to update existing papers' categories_name
                updated_count = self.update_categories_names()
                logger.info(f"Updated {updated_count} existing papers with category names")
                return updated_count
            
            # Create table if needed
            self.create_papers_table_if_not_exists()
            
            # Load papers to Supabase
            inserted_count = self.load_papers_to_supabase(papers)
            
            # Update existing papers' categories_name field
            updated_count = self.update_categories_names()
            
            logger.info(f"ETL pipeline completed successfully for {yesterday_str}. Inserted {inserted_count} new papers and updated {updated_count} existing papers with category names.")
            return inserted_count + updated_count
            
        except Exception as e:
            logger.error(f"ETL pipeline failed: {str(e)}")
            raise

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