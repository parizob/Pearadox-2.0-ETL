-- Fix missing PDF URLs in arxiv_papers table
-- ArXiv PDF URLs follow a predictable pattern: https://arxiv.org/pdf/{arxiv_id}.pdf

-- Step 1: Check how many papers are missing pdf_url
SELECT 
  COUNT(*) as total_papers_without_pdf,
  MIN(created_at) as oldest,
  MAX(created_at) as newest
FROM arxiv_papers
WHERE pdf_url IS NULL;

-- Step 2: Update papers with missing pdf_url
UPDATE arxiv_papers
SET pdf_url = CONCAT('https://arxiv.org/pdf/', arxiv_id, '.pdf')
WHERE pdf_url IS NULL;

-- Step 3: Verify the fix
SELECT 
  COUNT(*) as total_papers,
  COUNT(pdf_url) as papers_with_pdf,
  COUNT(*) - COUNT(pdf_url) as papers_still_without_pdf
FROM arxiv_papers;

-- Step 4: Check v_papers_needing_summaries now shows papers
SELECT COUNT(*) as papers_needing_summaries
FROM v_papers_needing_summaries;

-- Step 5: Show sample of recently fixed papers
SELECT 
  arxiv_id, 
  title, 
  pdf_url,
  published_date,
  created_at
FROM arxiv_papers
WHERE DATE(created_at) >= '2025-11-12'
ORDER BY created_at DESC
LIMIT 5;
