-- Migration script to update existing summary_papers table structure
-- Changes from layman/university to beginner/intermediate terminology
-- Adds intermediate_title field

-- First, add the new intermediate_title column
ALTER TABLE summary_papers 
ADD COLUMN IF NOT EXISTS intermediate_title TEXT;

-- If you have existing data with the old column names, migrate the data
-- Step 1: Rename old columns to new names (if they exist)
DO $$ 
BEGIN
    -- Check if old column exists and rename it
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'summary_papers' AND column_name = 'layman_summary') THEN
        ALTER TABLE summary_papers RENAME COLUMN layman_summary TO beginner_summary;
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'summary_papers' AND column_name = 'university_summary') THEN
        ALTER TABLE summary_papers RENAME COLUMN university_summary TO intermediate_summary;
    END IF;
END $$;

-- Step 2: Add beginner_summary and intermediate_summary columns if they don't exist
ALTER TABLE summary_papers 
ADD COLUMN IF NOT EXISTS beginner_summary TEXT;

ALTER TABLE summary_papers 
ADD COLUMN IF NOT EXISTS intermediate_summary TEXT;

-- Step 3: Set default values for intermediate_title if it's empty
UPDATE summary_papers 
SET intermediate_title = 'Intermediate title pending regeneration'
WHERE intermediate_title IS NULL OR intermediate_title = '';

-- Step 4: Make the new fields NOT NULL (after setting defaults)
ALTER TABLE summary_papers 
ALTER COLUMN intermediate_title SET NOT NULL;

ALTER TABLE summary_papers 
ALTER COLUMN beginner_summary SET NOT NULL;

ALTER TABLE summary_papers 
ALTER COLUMN intermediate_summary SET NOT NULL;

-- Update the views to include the new field structure
CREATE OR REPLACE VIEW v_papers_with_summaries AS
SELECT 
    ap.id as paper_id,
    ap.arxiv_id,
    ap.title as original_title,
    ap.abstract,
    ap.authors,
    ap.categories,
    ap.categories_name,
    ap.published_date,
    ap.pdf_url,
    sp.easy_title,
    sp.intermediate_title,
    sp.beginner_summary,
    sp.intermediate_summary,
    sp.processing_status,
    sp.gemini_model,
    sp.created_at as summary_created_at
FROM arxiv_papers ap
LEFT JOIN summary_papers sp ON ap.id = sp.arxiv_paper_id
ORDER BY ap.published_date DESC;

-- Note: Papers with old 3-field summaries will need to be regenerated to get intermediate_title
-- You can identify them with: SELECT * FROM summary_papers WHERE intermediate_title = 'Intermediate title pending regeneration';
-- Then run the summarization process again for those papers 