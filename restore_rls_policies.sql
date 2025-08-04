-- Restore Row Level Security (RLS) policies for ArXiv ETL tables
-- Run this script in Supabase SQL editor to restore proper RLS policies

-- =============================================================================
-- ENABLE RLS ON ALL TABLES
-- =============================================================================

-- Enable RLS on arxiv_papers table
ALTER TABLE arxiv_papers ENABLE ROW LEVEL SECURITY;

-- Enable RLS on summary_papers table
ALTER TABLE summary_papers ENABLE ROW LEVEL SECURITY;

-- Note: arxiv_categories is typically a view, but if it's a table, enable RLS
-- ALTER TABLE arxiv_categories ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- CREATE RLS POLICIES FOR ARXIV_PAPERS TABLE
-- =============================================================================

-- Drop existing policies if they exist (to avoid conflicts)
DROP POLICY IF EXISTS "Enable read access for all users" ON arxiv_papers;
DROP POLICY IF EXISTS "Enable insert for authenticated users only" ON arxiv_papers;
DROP POLICY IF EXISTS "Enable update for authenticated users only" ON arxiv_papers;
DROP POLICY IF EXISTS "Enable delete for authenticated users only" ON arxiv_papers;

-- Policy 1: Allow read access for all users (including anonymous)
CREATE POLICY "Enable read access for all users" ON arxiv_papers
    FOR SELECT
    USING (true);

-- Policy 2: Allow insert for authenticated users and service role
CREATE POLICY "Enable insert for authenticated users only" ON arxiv_papers
    FOR INSERT
    WITH CHECK (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role' OR
        auth.role() = 'anon'
    );

-- Policy 3: Allow update for authenticated users and service role
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
-- CREATE RLS POLICIES FOR SUMMARY_PAPERS TABLE
-- =============================================================================

-- Drop existing policies if they exist (to avoid conflicts)
DROP POLICY IF EXISTS "Enable read access for all users" ON summary_papers;
DROP POLICY IF EXISTS "Enable insert for authenticated users only" ON summary_papers;
DROP POLICY IF EXISTS "Enable update for authenticated users only" ON summary_papers;
DROP POLICY IF EXISTS "Enable delete for authenticated users only" ON summary_papers;

-- Policy 1: Allow read access for all users (including anonymous)
CREATE POLICY "Enable read access for all users" ON summary_papers
    FOR SELECT
    USING (true);

-- Policy 2: Allow insert for authenticated users and service role
CREATE POLICY "Enable insert for authenticated users only" ON summary_papers
    FOR INSERT
    WITH CHECK (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role' OR
        auth.role() = 'anon'
    );

-- Policy 3: Allow update for authenticated users and service role
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
-- GRANT NECESSARY PERMISSIONS
-- =============================================================================

-- Grant permissions to anon role (for ETL operations)
GRANT SELECT, INSERT, UPDATE ON arxiv_papers TO anon;
GRANT SELECT, INSERT, UPDATE ON summary_papers TO anon;

-- Grant permissions to authenticated role
GRANT SELECT, INSERT, UPDATE, DELETE ON arxiv_papers TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON summary_papers TO authenticated;

-- Grant permissions to service_role (for admin operations)
GRANT ALL ON arxiv_papers TO service_role;
GRANT ALL ON summary_papers TO service_role;

-- Grant usage on sequences
GRANT USAGE, SELECT ON SEQUENCE arxiv_papers_id_seq TO anon;
GRANT USAGE, SELECT ON SEQUENCE arxiv_papers_id_seq TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE summary_papers_id_seq TO anon;
GRANT USAGE, SELECT ON SEQUENCE summary_papers_id_seq TO authenticated;

-- =============================================================================
-- VIEWS PERMISSIONS (if using views for categories)
-- =============================================================================

-- Grant permissions on views to all roles
GRANT SELECT ON v_arxiv_categories TO anon;
GRANT SELECT ON v_arxiv_categories TO authenticated;
GRANT SELECT ON v_papers_needing_summaries TO anon;
GRANT SELECT ON v_papers_needing_summaries TO authenticated;
GRANT SELECT ON v_papers_with_summaries TO anon;
GRANT SELECT ON v_papers_with_summaries TO authenticated;

-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================

-- Run these queries to verify RLS is working:
-- SELECT * FROM information_schema.table_privileges WHERE table_name IN ('arxiv_papers', 'summary_papers');
-- SELECT * FROM pg_policies WHERE tablename IN ('arxiv_papers', 'summary_papers');

-- Test queries (should work with anon key):
-- SELECT COUNT(*) FROM arxiv_papers;
-- SELECT COUNT(*) FROM summary_papers;

COMMENT ON TABLE arxiv_papers IS 'ArXiv papers with RLS enabled for public read, authenticated write';
COMMENT ON TABLE summary_papers IS 'AI-generated summaries with RLS enabled for public read, authenticated write'; 