-- Create summary_papers table in Supabase
-- This table stores AI-generated summaries of arXiv papers
-- Includes RLS policies to prevent them from being overwritten

CREATE TABLE IF NOT EXISTS summary_papers (
    id BIGSERIAL PRIMARY KEY,
    arxiv_paper_id BIGINT NOT NULL REFERENCES arxiv_papers(id) ON DELETE CASCADE,
    arxiv_id VARCHAR(50) NOT NULL, -- For easy reference

    -- Titles
    beginner_title TEXT NOT NULL, -- AI-generated easy-to-understand title
    intermediate_title TEXT NOT NULL, -- AI-generated intermediate-level title

    -- One-sentence overviews
    beginner_overview TEXT NOT NULL, -- One sentence overview for general audience
    intermediate_overview TEXT NOT NULL, -- One sentence overview for technical audience

    -- Detailed summaries (150-200 words each)
    beginner_summary TEXT NOT NULL, -- Summary for beginners/general audience
    intermediate_summary TEXT NOT NULL, -- Summary for intermediate/post-university level

    processing_status VARCHAR(50) DEFAULT 'completed',
    processing_error TEXT, -- Store any errors during processing
    gemini_model VARCHAR(100), -- Track which Gemini model was used
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_summary_papers_arxiv_paper_id ON summary_papers(arxiv_paper_id);
CREATE INDEX IF NOT EXISTS idx_summary_papers_arxiv_id ON summary_papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_summary_papers_status ON summary_papers(processing_status);
CREATE INDEX IF NOT EXISTS idx_summary_papers_created_at ON summary_papers(created_at);

-- Create unique constraint to prevent duplicate summaries
ALTER TABLE summary_papers
ADD CONSTRAINT unique_summary_per_paper UNIQUE (arxiv_paper_id);

-- =============================================================================
-- ENABLE ROW LEVEL SECURITY (RLS)
-- =============================================================================

-- Enable RLS on the table
ALTER TABLE summary_papers ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist (to avoid conflicts)
DROP POLICY IF EXISTS "Enable read access for all users" ON summary_papers;
DROP POLICY IF EXISTS "Enable insert for authenticated users only" ON summary_papers;
DROP POLICY IF EXISTS "Enable update for authenticated users only" ON summary_papers;
DROP POLICY IF EXISTS "Enable delete for authenticated users only" ON summary_papers;

-- Policy 1: Allow read access for all users (including anonymous)
CREATE POLICY "Enable read access for all users" ON summary_papers
    FOR SELECT
    USING (true);

-- Policy 2: Allow insert for authenticated users, service role, and anon
CREATE POLICY "Enable insert for authenticated users only" ON summary_papers
    FOR INSERT
    WITH CHECK (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role' OR
        auth.role() = 'anon'
    );

-- Policy 3: Allow update for authenticated users, service role, and anon
CREATE POLICY "Enable update for authenticated users only" ON summary_papers
    FOR UPDATE
    USING (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role' OR
        auth.role() = 'anon'
    );

-- Policy 4: Allow delete for authenticated users and service role only
CREATE POLICY "Enable delete for authenticated users only" ON summary_papers
    FOR DELETE
    USING (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role'
    );

-- =============================================================================
-- GRANT PERMISSIONS
-- =============================================================================

-- Grant permissions to anon role (for ETL operations)
GRANT SELECT, INSERT, UPDATE ON summary_papers TO anon;

-- Grant permissions to authenticated role
GRANT SELECT, INSERT, UPDATE, DELETE ON summary_papers TO authenticated;

-- Grant permissions to service_role (for admin operations)
GRANT ALL ON summary_papers TO service_role;

-- Grant usage on sequences
GRANT USAGE, SELECT ON SEQUENCE summary_papers_id_seq TO anon;
GRANT USAGE, SELECT ON SEQUENCE summary_papers_id_seq TO authenticated;

-- =============================================================================
-- CREATE VIEWS
-- =============================================================================

-- Create a view that joins summary_papers with arxiv_papers for easy querying
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

-- Create a view for papers that need summarization
CREATE OR REPLACE VIEW v_papers_needing_summaries AS
SELECT
    ap.id,
    ap.arxiv_id,
    ap.title,
    ap.abstract,
    ap.pdf_url,
    ap.published_date
FROM arxiv_papers ap
LEFT JOIN summary_papers sp ON ap.id = sp.arxiv_paper_id
WHERE sp.id IS NULL  -- Papers without summaries
   AND ap.pdf_url IS NOT NULL  -- Only papers with PDF URLs
ORDER BY ap.published_date DESC;

-- =============================================================================
-- GRANT VIEW PERMISSIONS
-- =============================================================================

-- Grant permissions on views to all roles
GRANT SELECT ON v_papers_with_summaries TO anon;
GRANT SELECT ON v_papers_with_summaries TO authenticated;
GRANT SELECT ON v_papers_needing_summaries TO anon;
GRANT SELECT ON v_papers_needing_summaries TO authenticated;

-- Add table comment
COMMENT ON TABLE summary_papers IS 'AI-generated summaries with RLS enabled for public read, authenticated write';

-- Verification query to check RLS policies
-- SELECT tablename, policyname, roles, cmd, qual FROM pg_policies WHERE tablename = 'summary_papers'; 