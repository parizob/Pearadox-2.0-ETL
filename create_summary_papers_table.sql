-- Create summary_papers table in Supabase
-- This table stores AI-generated summaries of arXiv papers

CREATE TABLE IF NOT EXISTS summary_papers (
    id BIGSERIAL PRIMARY KEY,
    arxiv_paper_id BIGINT NOT NULL REFERENCES arxiv_papers(id) ON DELETE CASCADE,
    arxiv_id VARCHAR(50) NOT NULL, -- For easy reference
    easy_title TEXT NOT NULL, -- AI-generated easy-to-understand title
    intermediate_title TEXT NOT NULL, -- AI-generated intermediate-level title
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