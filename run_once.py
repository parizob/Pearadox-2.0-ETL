#!/usr/bin/env python3
"""
One-time runner for ArXiv ETL Pipeline
Use this script to test the ETL pipeline or run it manually.
"""

import sys
import argparse
from datetime import datetime, timedelta
from arxiv_etl import ArxivETL

def main():
    """Main function with command line argument support."""
    parser = argparse.ArgumentParser(description='Run ArXiv ETL pipeline')
    parser.add_argument('--test', action='store_true', 
                       help='Run in test mode (fetch papers from last 7 days)')
    parser.add_argument('--days-back', type=int, default=0,
                       help='Number of days back to fetch papers (default: 0 for yesterday only)')
    parser.add_argument('--specific-date', type=str,
                       help='Fetch papers for a specific date (format: YYYY-MM-DD)')
    parser.add_argument('--yesterday-only', action='store_true', default=True,
                       help='Only fetch papers from yesterday (arXiv default behavior)')
    parser.add_argument('--update-categories', action='store_true',
                       help='Update existing papers with category names (no new paper extraction)')
    
    args = parser.parse_args()
    
    try:
        etl = ArxivETL()
        
        if args.update_categories:
            # Just update existing papers' categories_name field
            print("Updating existing papers with category names...")
            updated_count = etl.update_categories_names()
            print(f"Successfully updated {updated_count} papers with category names.")
            return 0
            
        elif args.specific_date:
            # Fetch papers for a specific date
            try:
                target_date = datetime.strptime(args.specific_date, '%Y-%m-%d')
                start_str = target_date.strftime('%Y%m%d0000')
                end_str = target_date.strftime('%Y%m%d2359')
                target_str = target_date.strftime('%Y%m%d')
                
                print(f"Fetching papers for specific date: {target_date.strftime('%Y-%m-%d')}")
                
                papers = etl.extract_papers_from_arxiv(start_str, end_str, target_str)
                etl.create_papers_table_if_not_exists()
                result = etl.load_papers_to_supabase(papers)
                
                # Update categories for all papers
                updated_count = etl.update_categories_names()
                
                print(f"ETL completed. Inserted {result} new papers and updated {updated_count} papers with category names.")
                
            except ValueError:
                print("Invalid date format. Please use YYYY-MM-DD")
                return 1
                
        elif args.test or args.days_back > 0:
            # Custom date range - but still filter for individual dates
            days_back = 7 if args.test else args.days_back
            end_date = datetime.now() - timedelta(days=1)  # Start from yesterday
            start_date = end_date - timedelta(days=days_back)
            
            start_str = start_date.strftime('%Y%m%d0000')
            end_str = end_date.strftime('%Y%m%d2359')
            
            print(f"Fetching papers from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            print("Note: Will still filter to only include papers from each individual date")
            
            # For range queries, we don't specify a target date (will use current date filter)
            papers = etl.extract_papers_from_arxiv(start_str, end_str)
            etl.create_papers_table_if_not_exists()
            result = etl.load_papers_to_supabase(papers)
            
            # Update categories for all papers
            updated_count = etl.update_categories_names()
            
            print(f"ETL completed. Inserted {result} new papers and updated {updated_count} papers with category names.")
        else:
            # Run normal daily ETL - yesterday's papers (arXiv default)
            yesterday = datetime.now() - timedelta(days=1)
            print(f"Fetching papers from yesterday: {yesterday.strftime('%Y-%m-%d')} (arXiv's latest publications)")
            result = etl.run_daily_etl()
            print(f"Daily ETL completed. Processed {result} papers total (new + updated).")
        
        return 0
        
    except Exception as e:
        print(f"ETL failed: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 