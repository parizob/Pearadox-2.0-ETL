-- Create papers_quiz table in Supabase
-- This table stores AI-generated quiz questions for arXiv papers
-- Each quiz contains a question, 4 possible answers, and the correct answer

CREATE TABLE IF NOT EXISTS papers_quiz (
    id BIGSERIAL PRIMARY KEY,
    summary_paper_id BIGINT NOT NULL REFERENCES summary_papers(id) ON DELETE CASCADE,
    arxiv_paper_id BIGINT NOT NULL REFERENCES arxiv_papers(id) ON DELETE CASCADE,
    arxiv_id VARCHAR(50) NOT NULL, -- For easy reference

    -- Quiz content
    question TEXT NOT NULL, -- The quiz question
    answer_a TEXT NOT NULL, -- Option A
    answer_b TEXT NOT NULL, -- Option B
    answer_c TEXT NOT NULL, -- Option C
    answer_d TEXT NOT NULL, -- Option D
    correct_answer CHAR(1) NOT NULL CHECK (correct_answer IN ('A', 'B', 'C', 'D')), -- The correct answer (A, B, C, or D)

    processing_status VARCHAR(50) DEFAULT 'completed',
    processing_error TEXT, -- Store any errors during processing
    gemini_model VARCHAR(100), -- Track which Gemini model was used
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_papers_quiz_summary_paper_id ON papers_quiz(summary_paper_id);
CREATE INDEX IF NOT EXISTS idx_papers_quiz_arxiv_paper_id ON papers_quiz(arxiv_paper_id);
CREATE INDEX IF NOT EXISTS idx_papers_quiz_arxiv_id ON papers_quiz(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_papers_quiz_status ON papers_quiz(processing_status);
CREATE INDEX IF NOT EXISTS idx_papers_quiz_created_at ON papers_quiz(created_at);

-- Create unique constraint to prevent duplicate quizzes
ALTER TABLE papers_quiz
ADD CONSTRAINT unique_quiz_per_paper UNIQUE (summary_paper_id);

-- =============================================================================
-- ENABLE ROW LEVEL SECURITY (RLS)
-- =============================================================================

-- Enable RLS on the table
ALTER TABLE papers_quiz ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist (to avoid conflicts)
DROP POLICY IF EXISTS "Enable read access for all users" ON papers_quiz;
DROP POLICY IF EXISTS "Enable insert for authenticated users only" ON papers_quiz;
DROP POLICY IF EXISTS "Enable update for authenticated users only" ON papers_quiz;
DROP POLICY IF EXISTS "Enable delete for authenticated users only" ON papers_quiz;

-- Policy 1: Allow read access for all users (including anonymous)
CREATE POLICY "Enable read access for all users" ON papers_quiz
    FOR SELECT
    USING (true);

-- Policy 2: Allow insert for authenticated users, service role, and anon
CREATE POLICY "Enable insert for authenticated users only" ON papers_quiz
    FOR INSERT
    WITH CHECK (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role' OR
        auth.role() = 'anon'
    );

-- Policy 3: Allow update for authenticated users, service role, and anon
CREATE POLICY "Enable update for authenticated users only" ON papers_quiz
    FOR UPDATE
    USING (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role' OR
        auth.role() = 'anon'
    );

-- Policy 4: Allow delete for authenticated users and service role only
CREATE POLICY "Enable delete for authenticated users only" ON papers_quiz
    FOR DELETE
    USING (
        auth.role() = 'authenticated' OR 
        auth.role() = 'service_role'
    );

-- =============================================================================
-- GRANT PERMISSIONS
-- =============================================================================

-- Grant permissions to anon role (for ETL operations)
GRANT SELECT, INSERT, UPDATE ON papers_quiz TO anon;

-- Grant permissions to authenticated role
GRANT SELECT, INSERT, UPDATE, DELETE ON papers_quiz TO authenticated;

-- Grant permissions to service_role (for admin operations)
GRANT ALL ON papers_quiz TO service_role;

-- Grant usage on sequences
GRANT USAGE, SELECT ON SEQUENCE papers_quiz_id_seq TO anon;
GRANT USAGE, SELECT ON SEQUENCE papers_quiz_id_seq TO authenticated;

-- =============================================================================
-- CREATE VIEWS
-- =============================================================================

-- Create a view that joins papers_quiz with summary_papers and arxiv_papers
CREATE OR REPLACE VIEW v_papers_with_quizzes AS
SELECT
    ap.id as paper_id,
    ap.arxiv_id,
    ap.title as original_title,
    ap.abstract,
    ap.authors,
    ap.categories,
    ap.categories_name,
    ap.published_date,
    sp.beginner_title,
    sp.beginner_overview,
    sp.beginner_summary,
    pq.id as quiz_id,
    pq.question,
    pq.answer_a,
    pq.answer_b,
    pq.answer_c,
    pq.answer_d,
    pq.correct_answer,
    pq.gemini_model,
    pq.created_at as quiz_created_at
FROM arxiv_papers ap
INNER JOIN summary_papers sp ON ap.id = sp.arxiv_paper_id
LEFT JOIN papers_quiz pq ON sp.id = pq.summary_paper_id
ORDER BY ap.published_date DESC;

-- Create a view for papers that need quizzes
CREATE OR REPLACE VIEW v_papers_needing_quizzes AS
SELECT
    sp.id as summary_paper_id,
    sp.arxiv_paper_id,
    sp.arxiv_id,
    sp.beginner_title,
    sp.beginner_overview,
    sp.beginner_summary,
    ap.title as original_title,
    ap.published_date
FROM summary_papers sp
INNER JOIN arxiv_papers ap ON sp.arxiv_paper_id = ap.id
LEFT JOIN papers_quiz pq ON sp.id = pq.summary_paper_id
WHERE pq.id IS NULL  -- Papers without quizzes
   AND sp.processing_status = 'completed'  -- Only completed summaries
ORDER BY sp.created_at DESC;

-- =============================================================================
-- GRANT VIEW PERMISSIONS
-- =============================================================================

-- Grant permissions on views to all roles
GRANT SELECT ON v_papers_with_quizzes TO anon;
GRANT SELECT ON v_papers_with_quizzes TO authenticated;
GRANT SELECT ON v_papers_needing_quizzes TO anon;
GRANT SELECT ON v_papers_needing_quizzes TO authenticated;

-- Add table comment
COMMENT ON TABLE papers_quiz IS 'AI-generated quiz questions with RLS enabled for public read, authenticated write';

-- Verification query to check RLS policies
-- SELECT tablename, policyname, roles, cmd, qual FROM pg_policies WHERE tablename = 'papers_quiz';

