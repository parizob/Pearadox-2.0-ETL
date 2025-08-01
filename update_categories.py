#!/usr/bin/env python3
"""
Standalone script to update existing arxiv_papers records with category names.
This joins the categories column with the v_arxiv_categories view to populate categories_name.
"""

import sys
import logging
from arxiv_etl import ArxivETL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('update_categories.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def main():
    """Main function to update categories_name for existing papers."""
    try:
        logger.info("Starting category name update for existing papers")
        
        etl = ArxivETL()
        updated_count = etl.update_categories_names()
        
        print(f"Successfully updated {updated_count} papers with category names.")
        logger.info(f"Category update completed. Updated {updated_count} papers.")
        
        return 0
        
    except Exception as e:
        logger.error(f"Category update failed: {str(e)}")
        print(f"Update failed: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 