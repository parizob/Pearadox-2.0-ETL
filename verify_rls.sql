-- Verification script to check RLS policies and permissions
-- Run this in Supabase SQL editor to verify RLS is working correctly

-- =============================================================================
-- CHECK RLS STATUS ON TABLES
-- =============================================================================

SELECT 
    schemaname,
    tablename,
    rowsecurity as rls_enabled
FROM pg_tables 
WHERE tablename IN ('arxiv_papers', 'summary_papers')
ORDER BY tablename;

-- =============================================================================
-- CHECK EXISTING RLS POLICIES
-- =============================================================================

SELECT 
    tablename,
    policyname,
    permissive,
    roles,
    cmd,
    qual
FROM pg_policies 
WHERE tablename IN ('arxiv_papers', 'summary_papers')
ORDER BY tablename, policyname;

-- =============================================================================
-- CHECK TABLE PERMISSIONS
-- =============================================================================

SELECT 
    table_name,
    grantee,
    privilege_type
FROM information_schema.table_privileges 
WHERE table_name IN ('arxiv_papers', 'summary_papers')
  AND table_schema = 'public'
ORDER BY table_name, grantee, privilege_type;

-- =============================================================================
-- CHECK VIEW PERMISSIONS
-- =============================================================================

SELECT 
    table_name,
    grantee,
    privilege_type
FROM information_schema.table_privileges 
WHERE table_name IN ('v_papers_with_summaries', 'v_papers_needing_summaries', 'v_arxiv_categories')
  AND table_schema = 'public'
ORDER BY table_name, grantee, privilege_type;

-- =============================================================================
-- TEST QUERIES (Should work with your anon key)
-- =============================================================================

-- Test read access (should work)
-- SELECT COUNT(*) as arxiv_papers_count FROM arxiv_papers;
-- SELECT COUNT(*) as summary_papers_count FROM summary_papers;
-- SELECT COUNT(*) as papers_needing_summaries FROM v_papers_needing_summaries;

-- =============================================================================
-- SHOW TABLE COMMENTS
-- =============================================================================

SELECT 
    schemaname,
    tablename,
    obj_description(oid) as table_comment
FROM pg_tables pt
JOIN pg_class pc ON pc.relname = pt.tablename
WHERE tablename IN ('arxiv_papers', 'summary_papers')
  AND schemaname = 'public'; 