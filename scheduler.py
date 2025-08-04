#!/usr/bin/env python3
"""
Daily Scheduler for ArXiv ETL Pipeline
Runs the ETL pipeline daily at a specified time.
"""

import schedule
import time
import logging
from datetime import datetime
from arxiv_etl import ArxivETL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scheduler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def run_etl_job():
    """Run the ETL job with error handling."""
    logger.info("Starting scheduled ETL job")
    try:
        etl = ArxivETL()
        result = etl.run_daily_etl()
        logger.info(f"Scheduled ETL job completed successfully. Processed {result} papers (new + updated + summarized).")
        return result
    except Exception as e:
        logger.error(f"Scheduled ETL job failed: {str(e)}")
        return 0

def main():
    """Main scheduler function."""
    logger.info("Starting ArXiv ETL scheduler")
    logger.info("Note: ETL is weekday-aware - fetches Friday papers on Monday, previous day otherwise")
    
    # Schedule the job to run daily at 9:00 AM
    schedule.every().day.at("09:00").do(run_etl_job)
    
    # Alternative schedules (uncomment as needed):
    # schedule.every().day.at("06:00").do(run_etl_job)  # 6 AM
    # schedule.every().hour.do(run_etl_job)  # Every hour
    # schedule.every(6).hours.do(run_etl_job)  # Every 6 hours
    
    logger.info("Scheduler configured to run daily at 09:00")
    logger.info("ArXiv publishes papers Monday-Friday only")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Scheduler error: {str(e)}")

if __name__ == "__main__":
    main() 