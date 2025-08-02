#!/usr/bin/env python3
"""
Standalone script to process arXiv papers for AI summarization using Gemini 2.5 Flash Lite.
Downloads PDFs, extracts text, and generates summaries with rate limiting for free tier.
"""

import sys
import argparse
import logging
from arxiv_etl import ArxivETL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('process_summaries.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def main():
    """Main function to process papers for summarization."""
    parser = argparse.ArgumentParser(description='Process arXiv papers for AI summarization using Gemini 2.5 Flash Lite')
    parser.add_argument('--limit', type=int, default=5,
                       help='Maximum number of papers to process (default: 5, respects free tier rate limits)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        logger.info("Starting paper summarization process with Gemini 2.5 Flash Lite")
        logger.info(f"Processing up to {args.limit} papers (rate limited to 15 requests/minute)")
        
        etl = ArxivETL()
        
        if not etl.gemini_enabled:
            print("Gemini AI is not configured. Please set GEMINI_API_KEY in your .env file.")
            return 1
        
        processed_count = etl.process_papers_for_summarization(limit=args.limit)
        
        print(f"Successfully processed {processed_count} papers for summarization.")
        logger.info(f"Summarization process completed. Processed {processed_count} papers.")
        
        return 0
        
    except Exception as e:
        logger.error(f"Summarization process failed: {str(e)}")
        print(f"Process failed: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 