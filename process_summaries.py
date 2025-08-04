#!/usr/bin/env python3
"""
Standalone script to process arXiv papers for AI summarization using Gemini 2.5 Flash Lite.
Downloads PDFs, extracts text, and generates summaries with rate limiting for free tier.
Processes papers continuously until all are completed.
"""

import sys
import argparse
import logging
import time
from datetime import datetime
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
    parser.add_argument('--limit', type=int, default=15,
                        help='Maximum number of papers to process per batch (default: 15, matches free tier limits)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--single-batch', action='store_true',
                        help='Process only one batch and exit (useful for testing)')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        print("🚀 Starting continuous paper summarization process")
        etl = ArxivETL()
        if not etl.gemini_enabled:
            print("❌ Gemini AI is not configured. Please set GEMINI_API_KEY in your .env file.")
            return 1

        # Check total remaining papers
        remaining_response = etl.supabase.table('v_papers_needing_summaries').select('count', count='exact').execute()
        total_remaining = remaining_response.count
        print(f"📊 Total papers remaining to summarize: {total_remaining}")
        
        if total_remaining == 0:
            print("🎉 All papers already have summaries!")
            return 0

        batch_size = args.limit
        total_processed = 0
        batch_num = 1
        
        print(f"🔄 Processing in batches of {batch_size} papers with 1-minute intervals")
        print(f"⏱️  Rate limit: 15 requests per minute (free tier)")
        
        while True:
            batch_start_time = time.time()
            print(f"\n{'='*60}")
            print(f"🔄 Starting batch {batch_num} at {datetime.now().strftime('%H:%M:%S')}")
            print(f"📋 Processing up to {batch_size} papers...")
            
            # Process batch
            processed_count = etl.process_papers_for_summarization(limit=batch_size)
            total_processed += processed_count
            
            print(f"✅ Batch {batch_num} completed: {processed_count} papers processed")
            print(f"📈 Total processed so far: {total_processed}")
            
            # Check if we're done
            if processed_count == 0:
                print("🎉 All papers completed! No more papers need summarization.")
                break
            
            # Check remaining papers
            remaining_response = etl.supabase.table('v_papers_needing_summaries').select('count', count='exact').execute()
            current_remaining = remaining_response.count
            
            if current_remaining == 0:
                print("🎉 All papers completed! Database shows no papers needing summaries.")
                break
            
            print(f"📊 Papers remaining: {current_remaining}")
            
            # Exit if single batch mode
            if args.single_batch:
                print(f"🛑 Single batch mode: Processed {processed_count} papers and exiting")
                break
            
            # Calculate wait time to ensure we don't exceed rate limits
            batch_end_time = time.time()
            batch_duration = batch_end_time - batch_start_time
            
            # Wait for the full minute to pass (60 seconds) minus batch processing time
            wait_time = max(0, 60 - batch_duration)
            
            if wait_time > 0:
                print(f"⏱️  Batch took {batch_duration:.1f}s, waiting {wait_time:.1f}s more to complete 1-minute interval...")
                print(f"💤 Next batch will start at {datetime.now().strftime('%H:%M:%S')} + {wait_time:.0f}s")
                time.sleep(wait_time)
            else:
                print(f"⚡ Batch took {batch_duration:.1f}s (>60s), starting next batch immediately")
            
            batch_num += 1

        print(f"\n{'='*60}")
        print(f"🏁 Summarization process completed!")
        print(f"📊 Total papers processed: {total_processed}")
        print(f"🕐 Total batches: {batch_num - 1}")
        logger.info(f"Summarization process completed. Processed {total_processed} papers in {batch_num - 1} batches.")
        return 0
        
    except KeyboardInterrupt:
        print(f"\n⏹️  Process interrupted by user")
        print(f"📊 Total papers processed before interruption: {total_processed}")
        return 0
    except Exception as e:
        logger.error(f"Summarization process failed: {str(e)}")
        print(f"❌ Process failed: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 