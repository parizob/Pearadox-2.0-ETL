#!/usr/bin/env python3
"""
ArXiv Summaries to Google Sheets
Retrieves 5 summarized AI papers from Supabase and writes them to a Google Sheet.
"""

import os
import sys
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from supabase import create_client, Client
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('arxiv_gsheet.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class ArxivToGSheet:
    """Export ArXiv summarized papers to Google Sheets."""
    
    def __init__(self):
        """Initialize the Google Sheets exporter."""
        # Supabase configuration
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_ANON_KEY')
        
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("Missing Supabase credentials in environment variables")
        
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
        
        # Google Sheets configuration
        self.google_credentials_path = os.getenv('GOOGLE_CREDENTIALS_PATH', 'credentials.json')
        self.spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
        self.worksheet_name = os.getenv('GOOGLE_WORKSHEET_NAME', 'ArXiv Summaries')
        
        if not self.spreadsheet_id:
            raise ValueError("Missing GOOGLE_SPREADSHEET_ID in environment variables")
        
        # Initialize Google Sheets client
        self.gc = None
        self.worksheet = None
        self._init_google_sheets()
    
    def _init_google_sheets(self):
        """Initialize Google Sheets client and worksheet."""
        try:
            # Define the scope for Google Sheets API
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            # Load credentials
            if os.path.exists(self.google_credentials_path):
                credentials = Credentials.from_service_account_file(
                    self.google_credentials_path, 
                    scopes=scope
                )
            else:
                # Try to load from environment variable (JSON string)
                google_creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
                if not google_creds_json:
                    raise ValueError(f"Google credentials not found at {self.google_credentials_path} and GOOGLE_CREDENTIALS_JSON not set")
                
                import json
                creds_dict = json.loads(google_creds_json)
                credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
            
            # Initialize gspread client
            self.gc = gspread.authorize(credentials)
            
            # Open the spreadsheet
            spreadsheet = self.gc.open_by_key(self.spreadsheet_id)
            
            # Get or create the worksheet
            try:
                self.worksheet = spreadsheet.worksheet(self.worksheet_name)
                logger.info(f"Found existing worksheet: {self.worksheet_name}")
            except gspread.WorksheetNotFound:
                logger.info(f"Creating new worksheet: {self.worksheet_name}")
                self.worksheet = spreadsheet.add_worksheet(
                    title=self.worksheet_name, 
                    rows=1000, 
                    cols=20
                )
            
            logger.info("Google Sheets client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets: {str(e)}")
            raise
    
    def get_latest_summaries(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the latest summarized papers from Supabase."""
        try:
            logger.info(f"Retrieving {limit} latest summarized papers from Supabase")
            
            # Query the summary_papers table joined with arxiv_papers for complete data
            response = self.supabase.table('summary_papers').select(
                """
                *,
                arxiv_papers!inner(
                    arxiv_id,
                    title,
                    authors,
                    categories_name,
                    published_date,
                    abstract,
                    pdf_url,
                    abstract_url
                )
                """
            ).eq('processing_status', 'completed').order('created_at', desc=True).limit(limit).execute()
            
            if not response.data:
                logger.warning("No summarized papers found in database")
                return []
            
            logger.info(f"Retrieved {len(response.data)} summarized papers")
            return response.data
            
        except Exception as e:
            logger.error(f"Error retrieving summaries from Supabase: {str(e)}")
            raise
    
    def format_paper_data(self, papers: List[Dict[str, Any]]) -> List[List[str]]:
        """Format paper data for Google Sheets."""
        try:
            logger.info("Formatting paper data for Google Sheets")
            
            # Header row
            headers = [
                'ArXiv ID',
                'Original Title',
                'Beginner Title',
                'Intermediate Title',
                'Published Date',
                'Authors',
                'Categories',
                'Beginner Overview',
                'Intermediate Overview', 
                'Beginner Summary',
                'Intermediate Summary',
                'Abstract',
                'PDF URL',
                'ArXiv URL',
                'Processing Date'
            ]
            
            formatted_data = [headers]
            
            for paper in papers:
                arxiv_paper = paper.get('arxiv_papers', {})
                
                # Format authors list
                authors = arxiv_paper.get('authors', [])
                authors_str = ', '.join(authors[:3])  # Limit to first 3 authors
                if len(authors) > 3:
                    authors_str += ' et al.'
                
                # Format categories
                categories = arxiv_paper.get('categories_name', [])
                categories_str = ', '.join(categories[:3])  # Limit to first 3 categories
                
                # Format published date
                published_date = arxiv_paper.get('published_date', '')
                if published_date:
                    try:
                        dt = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
                        published_date = dt.strftime('%Y-%m-%d')
                    except:
                        pass
                
                # Format processing date
                processing_date = paper.get('created_at', '')
                if processing_date:
                    try:
                        dt = datetime.fromisoformat(processing_date.replace('Z', '+00:00'))
                        processing_date = dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        pass
                
                # Truncate long text fields for better sheet readability
                def truncate_text(text, max_length=500):
                    if not text:
                        return ''
                    return text[:max_length] + '...' if len(text) > max_length else text
                
                row = [
                    arxiv_paper.get('arxiv_id', ''),
                    truncate_text(arxiv_paper.get('title', ''), 100),
                    truncate_text(paper.get('beginner_title', ''), 100),
                    truncate_text(paper.get('intermediate_title', ''), 100),
                    published_date,
                    authors_str,
                    categories_str,
                    truncate_text(paper.get('beginner_overview', ''), 200),
                    truncate_text(paper.get('intermediate_overview', ''), 200),
                    truncate_text(paper.get('beginner_summary', '')),
                    truncate_text(paper.get('intermediate_summary', '')),
                    truncate_text(arxiv_paper.get('abstract', '')),
                    arxiv_paper.get('pdf_url', ''),
                    arxiv_paper.get('abstract_url', ''),
                    processing_date
                ]
                
                formatted_data.append(row)
            
            logger.info(f"Formatted {len(formatted_data) - 1} papers for Google Sheets")
            return formatted_data
            
        except Exception as e:
            logger.error(f"Error formatting paper data: {str(e)}")
            raise
    
    def write_to_sheet(self, data: List[List[str]], append_mode: bool = False):
        """Write data to Google Sheet."""
        try:
            if append_mode:
                logger.info("Appending data to existing Google Sheet")
                # Get existing data to avoid duplicate headers
                existing_data = self.worksheet.get_all_values()
                
                if existing_data:
                    # Remove header row from new data if sheet already has headers
                    data_to_append = data[1:] if data else []
                    if data_to_append:
                        # Find the next empty row
                        next_row = len(existing_data) + 1
                        # Append the data
                        for i, row in enumerate(data_to_append):
                            self.worksheet.insert_row(row, next_row + i)
                        logger.info(f"Appended {len(data_to_append)} rows to Google Sheet")
                    else:
                        logger.info("No new data to append")
                else:
                    # Sheet is empty, write all data including headers
                    self.worksheet.update('A1', data)
                    logger.info(f"Added {len(data)} rows to empty Google Sheet")
            else:
                logger.info("Overwriting Google Sheet with new data")
                # Clear existing data and write new data
                self.worksheet.clear()
                self.worksheet.update('A1', data)
                logger.info(f"Wrote {len(data)} rows to Google Sheet")
            
            # Format the header row
            if data:
                self.worksheet.format('A1:O1', {
                    'backgroundColor': {'red': 0.8, 'green': 0.8, 'blue': 0.8},
                    'textFormat': {'bold': True}
                })
            
            logger.info("Successfully updated Google Sheet")
            
        except Exception as e:
            logger.error(f"Error writing to Google Sheet: {str(e)}")
            raise
    
    def get_sheet_url(self) -> str:
        """Get the URL of the Google Sheet."""
        return f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit#gid={self.worksheet.id}"
    
    def export_summaries_to_sheet(self, limit: int = 5, append_mode: bool = True):
        """Main method to export summaries to Google Sheet."""
        try:
            logger.info(f"Starting export of {limit} summarized papers to Google Sheets")
            
            # Get latest summaries
            papers = self.get_latest_summaries(limit)
            
            if not papers:
                logger.warning("No papers to export")
                return 0
            
            # Format data for sheets
            formatted_data = self.format_paper_data(papers)
            
            # Write to Google Sheet
            self.write_to_sheet(formatted_data, append_mode)
            
            # Log success with sheet URL
            sheet_url = self.get_sheet_url()
            logger.info(f"Successfully exported {len(papers)} papers to Google Sheet")
            logger.info(f"View the sheet at: {sheet_url}")
            
            return len(papers)
            
        except Exception as e:
            logger.error(f"Export failed: {str(e)}")
            raise

def main():
    """Main function to run the export."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Export ArXiv summaries to Google Sheets')
    parser.add_argument('--limit', type=int, default=5, help='Number of papers to export (default: 5)')
    parser.add_argument('--append', action='store_true', help='Append to existing data instead of overwriting')
    
    args = parser.parse_args()
    
    try:
        exporter = ArxivToGSheet()
        exported_count = exporter.export_summaries_to_sheet(limit=args.limit, append_mode=args.append)
        
        print(f"Successfully exported {exported_count} papers to Google Sheets")
        return 0
        
    except Exception as e:
        logger.error(f"Export failed: {str(e)}")
        print(f"Export failed: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())