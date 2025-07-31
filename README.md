# ArXiv AI Papers ETL Pipeline

A comprehensive ETL (Extract, Transform, Load) pipeline that extracts AI science papers from the arXiv API and loads them into a Supabase database. This pipeline is designed to run daily and capture **ONLY** the latest AI research papers from **YESTERDAY** (arXiv's publication pattern).

## Features

- **Yesterday's Papers Only**: Extracts papers from **YESTERDAY ONLY** (arXiv's standard publication cycle)
- **Automated Daily Extraction**: Fetches AI papers from arXiv API daily for yesterday's date
- **Comprehensive AI Coverage**: Targets multiple AI categories (cs.AI, cs.LG, cs.CV, cs.CL, etc.)
- **Category Name Translation**: Translates category IDs to full names using taxonomy.json
- **Strict Date Filtering**: Additional post-processing to ensure only target date papers are included
- **Duplicate Prevention**: Avoids inserting duplicate papers
- **Robust Error Handling**: Comprehensive logging and error recovery
- **Flexible Scheduling**: Can be run manually, scheduled, or as a one-time job
- **Database Integration**: Direct integration with Supabase

## Important: arXiv Publication Pattern

🚨 **arXiv publishes papers the day before they appear on the site**. This pipeline is configured to fetch **YESTERDAY's papers** by default, which represents the latest available publications from arXiv.

**Why Yesterday?** arXiv follows this pattern:
- Papers are submitted and processed
- They are published the next day on the arXiv site
- So "today's" latest papers are actually from yesterday's date

## Category Translation

The pipeline includes automatic category translation:
- **categories**: Stores original arXiv category IDs (e.g., "cs.AI", "cs.LG")
- **categories_name**: Stores human-readable names (e.g., "Artificial Intelligence", "Machine Learning")
- **taxonomy.json**: Contains the mapping from IDs to full names
- **Extensible**: Easy to add new categories or modify existing translations

The pipeline uses multiple layers of filtering:

1. **API Query Filtering**: Limits arXiv query to yesterday's date range
2. **Post-Processing Filtering**: Additional verification that papers are from target date
3. **Logging**: Clear indication of how many papers were filtered out from other dates

## AI Categories Covered

- `cs.AI` - Artificial Intelligence
- `cs.LG` - Machine Learning  
- `cs.CV` - Computer Vision and Pattern Recognition
- `cs.CL` - Computation and Language (NLP)
- `cs.NE` - Neural and Evolutionary Computing
- `stat.ML` - Machine Learning (Statistics)
- `cs.RO` - Robotics
- `cs.IR` - Information Retrieval

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment Configuration

The `.env` file is already configured with your Supabase credentials:

```env
SUPABASE_URL=https://ullqyuvcyvaaiihmntnw.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 3. Database Setup

The table will be created automatically on first run, but you can also manually create it using the provided SQL schema:

```bash
# Run the SQL in your Supabase SQL editor
cat create_table.sql
```

## Usage

### Manual One-time Run

```bash
# Run ETL for YESTERDAY'S papers (default - arXiv's latest publications)
python run_once.py

# Fetch papers for a specific date
python run_once.py --specific-date 2025-01-15

# Test mode - fetch papers from last 7 days (ending yesterday)
python run_once.py --test

# Fetch papers from last N days (ending yesterday)
python run_once.py --days-back 3
```

### Scheduled Daily Run

```bash
# Start the scheduler (runs daily at 9:00 AM for yesterday's publications)
python scheduler.py
```

### Direct ETL Run

```bash
# Run the main ETL script directly (yesterday's papers)
python arxiv_etl.py
```

## arXiv Publication Pattern & Filtering

The pipeline now implements **arXiv-aware date filtering**:

- **Default**: Extracts papers from yesterday's date (arXiv's latest available)
- **API Query**: Limits search to target date range  
- **Post-Processing**: Additional filtering to ensure papers are from exact target date
- **Logging**: Shows how many papers were filtered out from other dates
- **Test Mode**: Even when using `--test` or `--days-back`, papers are still filtered by individual dates

**Why This Matters**: arXiv's publication cycle means that running the pipeline daily will capture each day's new publications automatically, without missing papers or getting duplicates.

## Database Schema

The pipeline creates an `arxiv_papers` table with the following structure:

```sql
CREATE TABLE arxiv_papers (
    id BIGSERIAL PRIMARY KEY,
    arxiv_id VARCHAR(50) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT NOT NULL,
    authors TEXT[] NOT NULL,
    categories TEXT[] NOT NULL,
    categories_name TEXT[] NOT NULL,
    published_date TIMESTAMPTZ NOT NULL,
    updated_date TIMESTAMPTZ NOT NULL,
    pdf_url TEXT,
    abstract_url TEXT NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Key Fields:
- **categories**: Original arXiv category IDs (e.g., ["cs.AI", "cs.LG"])
- **categories_name**: Human-readable category names (e.g., ["Artificial Intelligence", "Machine Learning"])
- **taxonomy.json**: Source file for category ID to name translations

## Migration for Existing Tables

If you already have the table without the `categories_name` column, run this migration:

```sql
-- Add the categories_name column
ALTER TABLE arxiv_papers 
ADD COLUMN IF NOT EXISTS categories_name TEXT[] NOT NULL DEFAULT '{}';

-- Create index for better performance
CREATE INDEX IF NOT EXISTS idx_arxiv_papers_categories_name ON arxiv_papers USING GIN(categories_name);
```

## Logging

All operations are logged to:
- `arxiv_etl.log` - Main ETL pipeline logs
- `scheduler.log` - Scheduler logs
- Console output for real-time monitoring

## Error Handling

The pipeline includes comprehensive error handling:
- Network timeouts and retries
- API rate limiting respect
- Database connection issues
- Data parsing errors
- Graceful degradation for partial failures

## Performance

- Batch inserts for efficient database operations
- Duplicate detection to avoid redundant data
- Optimized queries with proper indexing
- Rate limiting to respect arXiv API guidelines

## Monitoring

Check the logs regularly to ensure the pipeline is running smoothly:

```
```