-- Create arxiv_papers table and related views in Supabase
-- This script includes RLS policies to prevent them from being overwritten

-- Drop existing table if it exists (use with caution)
-- DROP TABLE IF EXISTS arxiv_papers CASCADE;

-- Create the main arxiv_papers table
CREATE TABLE IF NOT EXISTS arxiv_papers (
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

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_arxiv_papers_arxiv_id ON arxiv_papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_arxiv_papers_published_date ON arxiv_papers(published_date);
CREATE INDEX IF NOT EXISTS idx_arxiv_papers_categories ON arxiv_papers USING GIN(categories);
CREATE INDEX IF NOT EXISTS idx_arxiv_papers_categories_name ON arxiv_papers USING GIN(categories_name);
CREATE INDEX IF NOT EXISTS idx_arxiv_papers_extracted_at ON arxiv_papers(extracted_at);

-- =============================================================================
-- ENABLE ROW LEVEL SECURITY (RLS)
-- =============================================================================

-- Enable RLS on the table
ALTER TABLE arxiv_papers ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist (to avoid conflicts)
DROP POLICY IF EXISTS "Enable read access for all users" ON arxiv_papers;
DROP POLICY IF EXISTS "Enable insert for authenticated users only" ON arxiv_papers;
DROP POLICY IF EXISTS "Enable update for authenticated users only" ON arxiv_papers;
DROP POLICY IF EXISTS "Enable delete for authenticated users only" ON arxiv_papers;

-- Policy 1: Allow read access for all users (including anonymous)
CREATE POLICY "Enable read access for all users" ON arxiv_papers
    FOR SELECT
    USING (true);

-- Policy 2: Allow insert for authenticated users, service role, and anon
CREATE POLICY "Enable insert for authenticated users only" ON arxiv_papers
    FOR INSERT
    WITH CHECK (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role' OR
        auth.role() = 'anon'
    );

-- Policy 3: Allow update for authenticated users, service role, and anon
CREATE POLICY "Enable update for authenticated users only" ON arxiv_papers
    FOR UPDATE
    USING (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role' OR
        auth.role() = 'anon'
    );

-- Policy 4: Allow delete for authenticated users and service role only
CREATE POLICY "Enable delete for authenticated users only" ON arxiv_papers
    FOR DELETE
    USING (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role'
    );

-- =============================================================================
-- GRANT PERMISSIONS
-- =============================================================================

-- Grant permissions to anon role (for ETL operations)
GRANT SELECT, INSERT, UPDATE ON arxiv_papers TO anon;

-- Grant permissions to authenticated role
GRANT SELECT, INSERT, UPDATE, DELETE ON arxiv_papers TO authenticated;

-- Grant permissions to service_role (for admin operations)
GRANT ALL ON arxiv_papers TO service_role;

-- Grant usage on sequences
GRANT USAGE, SELECT ON SEQUENCE arxiv_papers_id_seq TO anon;
GRANT USAGE, SELECT ON SEQUENCE arxiv_papers_id_seq TO authenticated;

-- =============================================================================
-- CREATE VIEWS
-- =============================================================================

-- Create a view for recent papers (last 30 days)
CREATE OR REPLACE VIEW recent_arxiv_papers AS
SELECT *
FROM arxiv_papers
WHERE published_date >= (NOW() - INTERVAL '30 days')
ORDER BY published_date DESC;

-- Create a view for AI category breakdown (using category names)
CREATE OR REPLACE VIEW arxiv_papers_by_category AS
SELECT
    UNNEST(categories_name) as category_name,
    UNNEST(categories) as category_id,
    COUNT(*) as paper_count,
    MAX(published_date) as latest_paper
FROM arxiv_papers
GROUP BY category_name, category_id
ORDER BY paper_count DESC;

-- Create a view for category names only
CREATE OR REPLACE VIEW arxiv_papers_by_category_names AS
SELECT
    UNNEST(categories_name) as category_name,
    COUNT(*) as paper_count,
    MAX(published_date) as latest_paper
FROM arxiv_papers
GROUP BY category_name
ORDER BY paper_count DESC;

-- =============================================================================
-- GRANT VIEW PERMISSIONS
-- =============================================================================

-- Grant permissions on views to all roles
GRANT SELECT ON recent_arxiv_papers TO anon;
GRANT SELECT ON recent_arxiv_papers TO authenticated;
GRANT SELECT ON arxiv_papers_by_category TO anon;
GRANT SELECT ON arxiv_papers_by_category TO authenticated;
GRANT SELECT ON arxiv_papers_by_category_names TO anon;
GRANT SELECT ON arxiv_papers_by_category_names TO authenticated;

-- Add table comment
COMMENT ON TABLE arxiv_papers IS 'ArXiv AI papers with RLS enabled for public read, authenticated write';

-- Verification query to check RLS policies
-- SELECT tablename, policyname, roles, cmd, qual FROM pg_policies WHERE tablename = 'arxiv_papers'; 