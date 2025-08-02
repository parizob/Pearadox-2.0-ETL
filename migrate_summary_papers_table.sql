-- Migration script to update existing summary_papers table structure
-- Adds beginner/intermediate overviews and renames easy_title to beginner_title

-- Step 1: Add new overview columns
ALTER TABLE summary_papers
ADD COLUMN IF NOT EXISTS beginner_overview TEXT;

ALTER TABLE summary_papers
ADD COLUMN IF NOT EXISTS intermediate_overview TEXT;

-- Step 2: Rename easy_title to beginner_title if it exists
DO $$
BEGIN
    -- Check if old column exists and rename it
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'summary_papers' AND column_name = 'easy_title') THEN
        ALTER TABLE summary_papers RENAME COLUMN easy_title TO beginner_title;
    END IF;
    
    -- Ensure beginner_title exists (in case it was already renamed)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'summary_papers' AND column_name = 'beginner_title') THEN
        ALTER TABLE summary_papers ADD COLUMN beginner_title TEXT;
    END IF;

    -- Check if old column names exist and rename them
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'summary_papers' AND column_name = 'layman_summary') THEN
        ALTER TABLE summary_papers RENAME COLUMN layman_summary TO beginner_summary;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'summary_papers' AND column_name = 'university_summary') THEN
        ALTER TABLE summary_papers RENAME COLUMN university_summary TO intermediate_summary;
    END IF;
END $$;

-- Step 3: Add missing columns if they don't exist
ALTER TABLE summary_papers
ADD COLUMN IF NOT EXISTS intermediate_title TEXT;

ALTER TABLE summary_papers
ADD COLUMN IF NOT EXISTS beginner_summary TEXT;

ALTER TABLE summary_papers
ADD COLUMN IF NOT EXISTS intermediate_summary TEXT;

-- Step 4: Set default values for new overview fields
UPDATE summary_papers
SET beginner_overview = 'Overview pending regeneration'
WHERE beginner_overview IS NULL OR beginner_overview = '';

UPDATE summary_papers
SET intermediate_overview = 'Overview pending regeneration'
WHERE intermediate_overview IS NULL OR intermediate_overview = '';

-- Step 5: Set default values for other fields if they're empty
UPDATE summary_papers
SET beginner_title = 'Beginner title pending regeneration'
WHERE beginner_title IS NULL OR beginner_title = '';

UPDATE summary_papers
SET intermediate_title = 'Intermediate title pending regeneration'
WHERE intermediate_title IS NULL OR intermediate_title = '';

-- Step 6: Make all fields NOT NULL (after setting defaults)
ALTER TABLE summary_papers
ALTER COLUMN beginner_title SET NOT NULL;

ALTER TABLE summary_papers
ALTER COLUMN intermediate_title SET NOT NULL;

ALTER TABLE summary_papers
ALTER COLUMN beginner_overview SET NOT NULL;

ALTER TABLE summary_papers
ALTER COLUMN intermediate_overview SET NOT NULL;

ALTER TABLE summary_papers
ALTER COLUMN beginner_summary SET NOT NULL;

ALTER TABLE summary_papers
ALTER COLUMN intermediate_summary SET NOT NULL;

-- Step 7: Update the views to include the new field structure
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
    sp.beginner_title,
    sp.intermediate_title,
    sp.beginner_overview,
    sp.intermediate_overview,
    sp.beginner_summary,
    sp.intermediate_summary,
    sp.processing_status,
    sp.gemini_model,
    sp.created_at as summary_created_at
FROM arxiv_papers ap
LEFT JOIN summary_papers sp ON ap.id = sp.arxiv_paper_id
ORDER BY ap.published_date DESC;

-- Note: Papers with old summary structure will need to be regenerated to get the new overview fields
-- You can identify them with: 
-- SELECT * FROM summary_papers WHERE beginner_overview = 'Overview pending regeneration' OR intermediate_overview = 'Overview pending regeneration';
-- Then run the summarization process again for those papers 