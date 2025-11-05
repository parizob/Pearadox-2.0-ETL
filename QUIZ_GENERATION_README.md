# Quiz Generation for ArXiv Papers

This module generates multiple-choice quiz questions from summarized research papers using Google's Gemini AI.

## Overview

The quiz generation system:
1. Fetches completed paper summaries from the `summary_papers` table
2. Uses Gemini AI to generate engaging multiple-choice questions
3. Stores questions in the `papers_quiz` table with 4 options (A-D) and the correct answer

## Database Setup

### Create the papers_quiz Table

Run the SQL script to create the necessary table and views in Supabase:

```bash
# Execute in your Supabase SQL editor
cat create_papers_quiz_table.sql
```

Or copy the contents of `create_papers_quiz_table.sql` and run it in the Supabase dashboard.

### Table Structure

The `papers_quiz` table includes:

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `summary_paper_id` | BIGINT | Foreign key to summary_papers.id |
| `arxiv_paper_id` | BIGINT | Foreign key to arxiv_papers.id |
| `arxiv_id` | VARCHAR(50) | ArXiv ID for easy reference |
| `question` | TEXT | The quiz question |
| `answer_a` | TEXT | Option A |
| `answer_b` | TEXT | Option B |
| `answer_c` | TEXT | Option C |
| `answer_d` | TEXT | Option D |
| `correct_answer` | CHAR(1) | The correct answer ('A', 'B', 'C', or 'D') |
| `processing_status` | VARCHAR(50) | Status (default: 'completed') |
| `processing_error` | TEXT | Error message if generation failed |
| `gemini_model` | VARCHAR(100) | Gemini model used |
| `created_at` | TIMESTAMPTZ | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | Last update timestamp |

## Usage

### Basic Usage

Generate quizzes for the 5 most recent papers without quizzes:

```bash
python3 generate_quiz.py
```

### Custom Limit

Generate quizzes for a specific number of papers:

```bash
# Generate 10 quizzes
python3 generate_quiz.py --limit 10

# Generate 1 quiz (for testing)
python3 generate_quiz.py --limit 1
```

### Generate for Specific Date

Generate quizzes for ALL papers created on a specific date:

```bash
# Generate quizzes for all papers from November 3rd, 2025
python3 generate_quiz.py --date 2025-11-03

# The date format is YYYY-MM-DD
# This will process ALL papers created on that date (ignores --limit)
# Automatically skips papers that already have quizzes
```

**Note:** The `--date` parameter works with the `created_at` field in `summary_papers` table, which is a `timestamptz` field. The script correctly handles the timestamp by matching the entire day (00:00:00 to 23:59:59.999999).

### View Help

```bash
python3 generate_quiz.py --help
```

## How It Works

### 1. Paper Selection

The script:
- Queries `summary_papers` table for completed summaries
- **Without `--date`**: Orders by `created_at` (most recent first) and returns up to the specified limit (default: 5)
- **With `--date`**: Filters papers where `created_at` matches the specified date (entire day from 00:00:00 to 23:59:59.999999)
- Filters out papers that already have quizzes
- Returns matching papers for quiz generation

### 2. Quiz Generation

For each paper, the script:
- Extracts `beginner_title`, `beginner_overview`, and `beginner_summary`
- Sends a prompt to Gemini AI requesting:
  - One multiple-choice question
  - Four plausible answers (A-D)
  - The correct answer
- Parses and validates the JSON response

### 3. Quiz Storage

Successfully generated quizzes are:
- Validated for required fields
- Linked to `summary_paper_id`, `arxiv_paper_id`, and `arxiv_id`
- Stored in the `papers_quiz` table
- Logged for tracking

## Example Quiz Output

```json
{
  "question": "What is the main advantage of the attention mechanism introduced in this paper?",
  "answer_a": "It eliminates the need for recurrent layers in sequence modeling",
  "answer_b": "It reduces training time by 90%",
  "answer_c": "It requires less GPU memory",
  "answer_d": "It only works with vision transformers",
  "correct_answer": "A"
}
```

## Logging

The script logs to:
- **Console**: Real-time progress updates
- **File**: `generate_quiz.log` - Detailed logs including errors

Log levels:
- `INFO`: Normal operation (paper processing, success/failure counts)
- `ERROR`: Generation or database errors
- `DEBUG`: Rate limiting details (when enabled)

## Rate Limiting

The script includes built-in rate limiting for Gemini API:
- **Free tier limit**: 15 requests per minute
- **Automatic throttling**: Waits when limit is reached
- **Respectful delays**: 1 second between papers

## Error Handling

The script handles:
- Missing or invalid Gemini API responses
- JSON parsing errors
- Database connection issues
- Invalid quiz data (missing fields, invalid correct_answer)

Failed quiz generations are logged but don't stop the entire process.

## Querying Quizzes

### Get All Quizzes with Paper Info

```sql
SELECT * FROM v_papers_with_quizzes
WHERE quiz_id IS NOT NULL
ORDER BY quiz_created_at DESC;
```

### Get Papers Needing Quizzes

```sql
SELECT * FROM v_papers_needing_quizzes
LIMIT 10;
```

### Get Quiz for Specific Paper

```sql
SELECT 
    pq.*,
    sp.beginner_title,
    ap.title as original_title
FROM papers_quiz pq
JOIN summary_papers sp ON pq.summary_paper_id = sp.id
JOIN arxiv_papers ap ON pq.arxiv_paper_id = ap.id
WHERE pq.arxiv_id = '2401.12345';
```

## Integration with Existing Workflow

### Recommended Workflow

1. **Fetch papers**: Run `arxiv_etl.py` to get new papers
2. **Generate summaries**: Run `process_summaries.py` to create beginner summaries
3. **Generate quizzes**: Run `generate_quiz.py` to create quiz questions
4. **Export to sheets**: Run `daily5.py` to export to Google Sheets (if needed)

### Automated Scheduling

Add to `scheduler.py` or run via cron:

```python
# In scheduler.py
from generate_quiz import QuizGenerator

def generate_daily_quizzes():
    """Generate quizzes for papers without them."""
    generator = QuizGenerator()
    generated_count = generator.generate_quizzes_for_papers(limit=5)
    logger.info(f"Generated {generated_count} new quizzes")
```

Or via cron:

```bash
# Run quiz generation daily at 3 AM
0 3 * * * cd /path/to/project && /usr/bin/python3 generate_quiz.py --limit 5 >> quiz_cron.log 2>&1
```

## Environment Variables

Required environment variables (in `.env` file):

```env
# Supabase credentials
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key

# Gemini API
GEMINI_API_KEY=your_gemini_api_key
```

## Troubleshooting

### "Missing Supabase credentials"
- Ensure `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set in `.env`

### "Gemini API key not configured"
- Ensure `GEMINI_API_KEY` is set in `.env`
- Verify the key is valid (not placeholder text)

### "Failed to parse JSON response"
- Check `generate_quiz.log` for the actual response
- Gemini might occasionally return malformed JSON
- Script will skip that paper and continue with others

### "Rate limit reached"
- Normal behavior - script automatically waits
- Free tier: 15 requests/minute
- Consider upgrading to paid tier for higher limits

### No papers found
- Verify papers exist in `summary_papers` table
- Check that papers have `processing_status = 'completed'`
- Run `process_summaries.py` first if needed

## Testing

### Test with One Paper

```bash
python3 generate_quiz.py --limit 1
```

### Verify Database Table

```sql
-- Check if table exists
SELECT COUNT(*) FROM papers_quiz;

-- View latest quizzes
SELECT 
    arxiv_id,
    question,
    correct_answer,
    created_at
FROM papers_quiz
ORDER BY created_at DESC
LIMIT 5;
```

### Test Quiz Quality

Review generated quizzes for:
- Clear, understandable questions
- Plausible answer options
- Correct answer is actually correct
- All options are distinct

## Future Enhancements

Potential improvements:
- [ ] Generate multiple questions per paper
- [ ] Add difficulty levels (easy, medium, hard)
- [ ] Support for advanced/intermediate quizzes
- [ ] Quiz question validation/review system
- [ ] Integration with frontend quiz interface
- [ ] Analytics on quiz performance

## Support

For issues or questions:
1. Check `generate_quiz.log` for detailed error messages
2. Verify all environment variables are set correctly
3. Ensure Gemini API quota is not exceeded
4. Test with `--limit 1` to isolate issues

---

**Created**: 2025-11-05  
**Version**: 1.0  
**Author**: Pearadox ETL Pipeline

