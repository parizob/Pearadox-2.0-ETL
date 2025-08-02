# ArXiv AI Papers ETL Pipeline with AI Summarization

A comprehensive ETL (Extract, Transform, Load) pipeline that extracts AI science papers from arXiv API, loads them into a Supabase database, and generates AI-powered summaries using Google's Gemini API. This pipeline is designed to run daily and capture **ONLY** the latest AI research papers from **YESTERDAY** (arXiv's publication pattern).

## Features

- **Yesterday's Papers Only**: Extracts papers from **YESTERDAY ONLY** (arXiv's standard publication cycle)
- **Automated Daily Extraction**: Fetches AI papers from arXiv API daily for yesterday's date
- **Comprehensive AI Coverage**: Targets multiple AI categories (cs.AI, cs.LG, cs.CV, cs.CL, etc.)
- **Category Name Translation**: Translates category IDs to full names using taxonomy.json
- **AI-Powered Summarization**: Uses Google Gemini API to generate four types of summaries
- **PDF Processing**: Downloads and extracts text from research papers
- **Strict Date Filtering**: Additional post-processing to ensure only target date papers are included
- **Duplicate Prevention**: Avoids inserting duplicate papers
- **Robust Error Handling**: Comprehensive logging and error recovery
- **Flexible Scheduling**: Can be run manually, scheduled, or as a one-time job
- **Database Integration**: Direct integration with Supabase

## AI Summarization Features

The pipeline now includes advanced AI summarization using Google's Gemini 2.5 Flash Lite API:

### Four Types of Summaries Generated:
1. **Easy Title**: Simplified, engaging title for general audience
2. **Intermediate Title**: Moderately technical title for readers with some background
3. **Beginner Summary**: Plain-language explanation for anyone to understand
4. **Intermediate Summary**: Detailed technical summary for educated readers

### PDF Processing:
- Downloads PDFs temporarily (not stored permanently)
- Extracts text content from first 10 pages
- Combines with title and abstract for comprehensive analysis
- Respects API rate limits and handles errors gracefully

### Rate Limiting for Free Tier:
- **Model**: Gemini 2.5 Flash Lite (free tier)
- **Limits**: 15 requests per minute, 1000 requests per day
- **Built-in Protection**: Automatic rate limiting to stay within free limits
- **Default Processing**: 5 papers per run (adjustable with `--limit` parameter)

### Database Storage:
- Summaries stored in separate `summary_papers` table
- Links to original papers via foreign key relationship
- Tracks processing status and error handling
- Prevents duplicate summarization

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
- **public.v_arxiv_categories view**: Supabase view with columns `category_code` and `category_name` for category mappings
- **Dynamic Loading**: Category mappings are loaded from Supabase at runtime
- **Extensible**: Easy to add new categories by updating the underlying data

## Category Mapping Source

The pipeline loads category mappings from the **`public.v_arxiv_categories`** view in your Supabase database:

```sql
-- Example v_arxiv_categories view structure
SELECT category_code, category_name FROM public.v_arxiv_categories;
-- Returns: category_code (e.g., "cs.AI", "cs.LG"), category_name (e.g., "Artificial Intelligence", "Machine Learning")
```

### Benefits of Using Supabase View:
- **Centralized**: All category data accessible through one view
- **Dynamic**: Updates to categories are immediately available
- **Optimized**: Views can provide pre-processed or filtered data
- **No File Dependencies**: No need to maintain local JSON files

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

Update your `.env` file with the required credentials:

```env
SUPABASE_URL=https://ullqyuvcyvaaiihmntnw.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key
GEMINI_API_KEY=your_gemini_api_key_here
```

**Get your Gemini API key from**: https://makersuite.google.com/app/apikey

### 3. Database Setup

Create the tables by running these SQL scripts in your Supabase SQL editor:

```bash
# Create the main papers table
cat create_table.sql

# Create the summaries table (new installations)
cat create_summary_papers_table.sql

# OR if you have an existing summary_papers table, run the migration instead:
cat migrate_summary_papers_table.sql
```

**For Existing Installations**: If you already have a `summary_papers` table with the old field names (`layman_summary`, `university_summary`), use the migration script to update to the new structure with beginner/intermediate terminology and add the `intermediate_title` field.

## Usage

### Manual One-time Run

```bash
# Run ETL for YESTERDAY'S papers with AI summarization (default)
python run_once.py

# Update existing papers with category names (no new paper extraction)
python run_once.py --update-categories

# Fetch papers for a specific date (includes summarization)
python run_once.py --specific-date 2025-01-15

# Test mode - fetch papers from last 7 days (includes summarization)
python run_once.py --test

# Fetch papers from last N days (includes summarization)
python run_once.py --days-back 3
```

### AI Summarization

```bash
# Process papers for AI summarization (standalone) - respects free tier limits
python process_summaries.py

# Process up to 3 papers for summarization (custom limit)
python process_summaries.py --limit 3

# Enable debug logging for summarization
python process_summaries.py --debug

# Summarization happens automatically during regular ETL runs (5 papers max per run)
python run_once.py  # Includes paper extraction + summarization
```

**Rate Limiting Notes:**
- Free tier allows 15 requests/minute, 1000/day
- Default limit is 5 papers per run to stay well within limits
- Pipeline automatically waits between requests to respect rate limits
- Processing time scales with number of papers due to rate limiting

### Category Name Updates

```bash
# Standalone script to update existing papers with category names
python update_categories.py

# Update categories as part of regular ETL run (happens automatically)
python run_once.py  # Updates existing papers after inserting new ones
```

### Scheduled Daily Run

```bash
# Start the scheduler (runs daily with full pipeline including AI summarization)
python scheduler.py
```

### Direct ETL Run

```bash
# Run the main ETL script directly (papers + categories + AI summaries)
python arxiv_etl.py
```

## AI Summarization Workflow

The complete workflow now includes:

1. **Paper Extraction**: Download papers from arXiv for target date
2. **Category Translation**: Convert category IDs to human-readable names  
3. **Database Storage**: Save papers to `arxiv_papers` table
4. **PDF Processing**: Download and extract text from PDFs (temporary)
5. **AI Summarization**: Generate summaries using Gemini API
6. **Summary Storage**: Save summaries to `summary_papers` table

### Processing Limits:
- **Daily ETL**: Processes up to 5 papers for summarization per run (respects free tier)
- **Standalone**: Configurable limit with `--limit` parameter (default: 5)
- **Rate Limiting**: Automatic 15 requests/minute limit enforcement
- **Free Tier Protection**: Built-in safeguards to stay within 1000 requests/day
- **Error Handling**: Failed summaries logged and marked in database

## arXiv Publication Pattern & Filtering

The pipeline now implements **arXiv-aware date filtering**:

- **Default**: Extracts papers from yesterday's date (arXiv's latest available)
- **API Query**: Limits search to target date range  
- **Post-Processing**: Additional filtering to ensure papers are from exact target date
- **Logging**: Shows how many papers were filtered out from other dates
- **Test Mode**: Even when using `--test` or `--days-back`, papers are still filtered by individual dates

**Why This Matters**: arXiv's publication cycle means that running the pipeline daily will capture each day's new publications automatically, without missing papers or getting duplicates.

## Category Name Update Process

The ETL pipeline now includes an automatic update process that:

1. **Identifies Papers**: Finds all papers with empty or missing `categories_name` fields
2. **Joins Data**: Uses the `categories` column to look up names in `v_arxiv_categories` view
3. **Updates Records**: Populates the `categories_name` field with translated category names
4. **Batch Processing**: Processes updates in batches of 50 for optimal performance

This ensures that:
- **New papers** get category names during insertion
- **Existing papers** get updated with category names if missing
- **Historical data** can be backfilled with category translations

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
- **public.v_arxiv_categories view**: Source view in Supabase for category ID to name translations

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