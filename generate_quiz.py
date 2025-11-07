#!/usr/bin/env python3
"""
ArXiv Papers Quiz Generator
Generates quiz questions from summarized papers using Gemini AI.
Fetches papers from summary_papers table and creates multiple-choice questions.
"""

import os
import sys
import logging
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from supabase import create_client, Client
from dotenv import load_dotenv
import time
import threading

# Gemini AI imports
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('generate_quiz.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class RateLimiter:
    """Rate limiter for Gemini API to stay within free tier limits."""
    
    def __init__(self, max_requests_per_minute=10):
        self.max_requests_per_minute = max_requests_per_minute
        self.requests_made = []
        self.lock = threading.Lock()
    
    def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        with self.lock:
            now = datetime.now()
            
            # Remove requests older than 1 minute
            self.requests_made = [req_time for req_time in self.requests_made 
                                if (now - req_time).total_seconds() < 60]
            
            # If we're at the limit, wait until we can make another request
            if len(self.requests_made) >= self.max_requests_per_minute:
                oldest_request = min(self.requests_made)
                wait_time = 60 - (now - oldest_request).total_seconds()
                if wait_time > 0:
                    logger.info(f"Rate limit reached. Waiting {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
                    # Clean up again after waiting
                    now = datetime.now()
                    self.requests_made = [req_time for req_time in self.requests_made 
                                        if (now - req_time).total_seconds() < 60]
            
            # Record this request
            self.requests_made.append(now)
            logger.debug(f"API requests in last minute: {len(self.requests_made)}/{self.max_requests_per_minute}")

class QuizGenerator:
    """Generate quiz questions from summarized arXiv papers using Gemini AI."""
    
    def __init__(self):
        """Initialize the quiz generator with Supabase and Gemini clients."""
        # Supabase configuration
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_ANON_KEY')
        
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("Missing Supabase credentials in environment variables")
        
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
        
        # Gemini AI configuration with rate limiting
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        if not self.gemini_api_key or self.gemini_api_key == 'your_gemini_api_key_here':
            raise ValueError("Gemini API key not configured. Cannot generate quizzes.")
        
        try:
            genai.configure(api_key=self.gemini_api_key)
            # Use Gemini 2.5 Flash Lite model (free tier)
            self.gemini_model = genai.GenerativeModel('gemini-2.5-flash-lite')
            self.gemini_enabled = True
            # Initialize rate limiter for free tier: 10 requests per minute
            self.rate_limiter = RateLimiter(max_requests_per_minute=10)
            self.model_name = 'gemini-2.5-flash-lite'
            logger.info("Gemini AI initialized successfully with rate limiting (10 req/min)")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini AI: {str(e)}")
            raise
    
    def get_papers_needing_quizzes(self, limit: int = 5, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve papers from summary_papers that don't have quizzes yet.
        
        Args:
            limit: Maximum number of papers to retrieve (default: 5)
            target_date: Optional date filter in YYYY-MM-DD format (e.g., '2025-11-03')
                        Will match papers created on this date regardless of time
            
        Returns:
            List of paper dictionaries with summary data
        """
        try:
            if target_date:
                logger.info(f"Retrieving papers created on {target_date} needing quizzes from Supabase")
            else:
                logger.info(f"Retrieving up to {limit} papers needing quizzes from Supabase")
            
            # Build the query
            query = self.supabase.table('summary_papers').select(
                """
                id,
                arxiv_paper_id,
                arxiv_id,
                beginner_title,
                beginner_overview,
                beginner_summary,
                processing_status,
                created_at
                """
            ).eq('processing_status', 'completed')
            
            # Add date filter if specified
            if target_date:
                # Validate date format
                from datetime import datetime as dt
                try:
                    # Validate the date format
                    dt.strptime(target_date, '%Y-%m-%d')
                    
                    logger.info(f"Filtering for papers where date(created_at) = {target_date}")
                    
                    # Use PostgreSQL's date casting to compare only the date part
                    # This uses a direct filter that compares YYYY-MM-DD regardless of time/timezone
                    # We need to use a custom filter with the ::date cast
                    # Since Supabase doesn't support ::date in the Python client directly,
                    # we'll query all recent papers and filter in Python
                    
                    # For now, let's get papers from a wider range and filter in Python
                    # Calculate date range to be safe with timezones
                    start_timestamp = f"{target_date}T00:00:00"
                    end_timestamp = f"{target_date}T23:59:59.999999"
                    
                    # Also account for timezone offsets (papers might be stored in UTC)
                    # Get papers from the previous day to next day to be safe
                    import datetime
                    date_obj = dt.strptime(target_date, '%Y-%m-%d')
                    prev_day = (date_obj - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
                    next_day = (date_obj + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
                    
                    logger.info(f"Querying papers from {prev_day} to {next_day} (to handle timezones)")
                    
                    # Query with wider range
                    query = query.gte('created_at', f"{prev_day}T00:00:00").lt('created_at', f"{next_day}T00:00:00")
                    
                except ValueError as e:
                    logger.error(f"Invalid date format: {target_date}. Use YYYY-MM-DD format.")
                    raise ValueError(f"Invalid date format: {target_date}. Expected YYYY-MM-DD (e.g., 2025-11-03)")
            
            # Order and execute query
            # If date filtering, don't apply a limit (get all papers from that date)
            # Otherwise use limit * 2 to account for papers that already have quizzes
            if target_date:
                # Set a very high limit to get ALL papers from the specified date
                # Supabase has a default limit of ~1000, so we set a high value
                # This ensures we get all papers without pagination
                response = query.order('created_at', desc=True).limit(10000).execute()
                logger.info(f"Query executed with limit=10000 to retrieve all papers from {target_date}")
            else:
                # Apply limit for recent papers query
                response = query.order('created_at', desc=True).limit(limit * 2).execute()
            
            if not response.data:
                if target_date:
                    logger.warning(f"No completed summary papers found for date {target_date}")
                else:
                    logger.warning("No completed summary papers found in database")
                return []
            
            logger.info(f"Found {len(response.data)} completed papers in database")
            
            # If using date filter, filter results to exact date (handling timezone)
            if target_date and response.data:
                from datetime import datetime as dt
                filtered_papers = []
                for paper in response.data:
                    created_at = paper.get('created_at', '')
                    if created_at:
                        # Extract just the date part from the timestamp
                        # Handle formats like: 2025-11-03T12:34:56+00:00 or 2025-11-03T12:34:56.123456+00:00
                        try:
                            # Parse the timestamp and extract date
                            if 'T' in created_at:
                                date_part = created_at.split('T')[0]
                            else:
                                date_part = created_at.split(' ')[0] if ' ' in created_at else created_at[:10]
                            
                            if date_part == target_date:
                                filtered_papers.append(paper)
                        except Exception as e:
                            logger.warning(f"Could not parse date from created_at: {created_at}")
                            continue
                
                response.data = filtered_papers
                logger.info(f"After date filtering: {len(response.data)} papers match {target_date}")
            
            # Filter out papers that already have quizzes
            papers_without_quizzes = []
            for paper in response.data:
                # Check if quiz already exists
                quiz_check = self.supabase.table('papers_quiz').select('id').eq(
                    'summary_paper_id', paper['id']
                ).execute()
                
                if not quiz_check.data:
                    papers_without_quizzes.append(paper)
                    # Only apply limit if not using date filter
                    if not target_date and len(papers_without_quizzes) >= limit:
                        break
            
            logger.info(f"Found {len(papers_without_quizzes)} papers without quizzes")
            return papers_without_quizzes
            
        except Exception as e:
            logger.error(f"Error retrieving papers from Supabase: {str(e)}")
            raise
    
    def generate_quiz_question(self, paper: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generate a quiz question for a paper using Gemini AI.
        
        Args:
            paper: Dictionary containing paper data with beginner_title, beginner_overview, beginner_summary
            
        Returns:
            Dictionary with question, answers (A-D), and correct_answer, or None if generation fails
        """
        try:
            # Wait for rate limiting
            self.rate_limiter.wait_if_needed()
            
            beginner_title = paper.get('beginner_title', '')
            beginner_overview = paper.get('beginner_overview', '')
            beginner_summary = paper.get('beginner_summary', '')
            
            # Create prompt for Gemini
            prompt = f"""Based on the following research paper summary, create ONE multiple-choice quiz question to test understanding of the key concept.

Title: {beginner_title}

Overview: {beginner_overview}

Summary: {beginner_summary}

TASK: Create a quiz question with:
1. One clear question about a key concept or finding
2. Four answer options labeled A, B, C, D (appropriate for beginners)
3. Three incorrect but plausible distractors
4. ONE correct answer

CRITICAL: You MUST include ALL SIX fields in your response:
- question (the quiz question)
- answer_a (option A)
- answer_b (option B)
- answer_c (option C)
- answer_d (option D)
- correct_answer (which letter A, B, C, or D is correct)

OUTPUT FORMAT: Respond with ONLY valid JSON (no markdown, no code blocks, no explanations):

{{
    "question": "Your question text here?",
    "answer_a": "First option text",
    "answer_b": "Second option text",
    "answer_c": "Third option text",
    "answer_d": "Fourth option text",
    "correct_answer": "A"
}}

REMEMBER: The "correct_answer" field is REQUIRED and must be exactly one of these letters: "A" or "B" or "C" or "D"
"""
            
            logger.info(f"Generating quiz for paper: {paper.get('arxiv_id')}")
            
            # Retry up to 3 times if we get incomplete responses
            max_attempts = 3
            for attempt in range(max_attempts):
                if attempt > 0:
                    logger.info(f"Retry attempt {attempt + 1}/{max_attempts} for paper: {paper.get('arxiv_id')}")
                    time.sleep(2)  # Brief delay between retries
                    self.rate_limiter.wait_if_needed()  # Check rate limit again
                
                # Use lower temperature on retries for more consistent output
                temperature = 0.5 if attempt > 0 else 0.7
                
                # Generate quiz using Gemini
                response = self.gemini_model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        top_p=0.9,
                        top_k=40,
                        max_output_tokens=600,  # Increased slightly for better completion
                    )
                )
                
                if not response or not response.text:
                    logger.warning(f"Empty response from Gemini (attempt {attempt + 1}/{max_attempts})")
                    continue
                
                # Parse the JSON response
                response_text = response.text.strip()
                
                # Remove markdown code blocks if present
                if response_text.startswith('```'):
                    response_text = re.sub(r'^```(?:json)?\s*\n', '', response_text)
                    response_text = re.sub(r'\n```\s*$', '', response_text)
                
                # Try to parse JSON
                try:
                    quiz_data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON (attempt {attempt + 1}/{max_attempts}): {e}")
                    logger.debug(f"Response text: {response_text}")
                    continue
                
                # Validate the quiz data
                required_fields = ['question', 'answer_a', 'answer_b', 'answer_c', 'answer_d', 'correct_answer']
                missing_fields = [field for field in required_fields if field not in quiz_data]
                
                if missing_fields:
                    logger.warning(f"Missing fields (attempt {attempt + 1}/{max_attempts}): {missing_fields}")
                    logger.debug(f"Partial quiz data: {quiz_data}")
                    continue
                
                # If we got here, we have all required fields
                break
            else:
                # All attempts failed
                logger.error(f"Failed to generate valid quiz after {max_attempts} attempts")
                logger.error(f"Last quiz data received: {quiz_data if 'quiz_data' in locals() else 'None'}")
                return None
            
            # Validate correct_answer is A, B, C, or D
            correct_answer = quiz_data['correct_answer'].upper().strip()
            if correct_answer not in ['A', 'B', 'C', 'D']:
                logger.error(f"Invalid correct_answer: {correct_answer}")
                return None
            
            quiz_data['correct_answer'] = correct_answer
            
            logger.info(f"Successfully generated quiz for paper: {paper.get('arxiv_id')}")
            return quiz_data
            
        except Exception as e:
            logger.error(f"Error generating quiz for paper {paper.get('arxiv_id')}: {str(e)}")
            return None
    
    def save_quiz_to_database(self, paper: Dict[str, Any], quiz_data: Dict[str, Any]) -> bool:
        """
        Save generated quiz to the papers_quiz table.
        
        Args:
            paper: Dictionary containing paper data (id, arxiv_paper_id, arxiv_id)
            quiz_data: Dictionary containing quiz question and answers
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Prepare data for insertion
            quiz_record = {
                'summary_paper_id': paper['id'],
                'arxiv_paper_id': paper['arxiv_paper_id'],
                'arxiv_id': paper['arxiv_id'],
                'question': quiz_data['question'],
                'answer_a': quiz_data['answer_a'],
                'answer_b': quiz_data['answer_b'],
                'answer_c': quiz_data['answer_c'],
                'answer_d': quiz_data['answer_d'],
                'correct_answer': quiz_data['correct_answer'],
                'processing_status': 'completed',
                'gemini_model': self.model_name,
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            # Insert into database
            response = self.supabase.table('papers_quiz').insert(quiz_record).execute()
            
            if response.data:
                logger.info(f"Successfully saved quiz for paper: {paper['arxiv_id']}")
                return True
            else:
                logger.error(f"Failed to save quiz for paper: {paper['arxiv_id']}")
                return False
                
        except Exception as e:
            logger.error(f"Error saving quiz to database for paper {paper.get('arxiv_id')}: {str(e)}")
            return False
    
    def generate_quizzes_for_papers(self, limit: int = 5, target_date: Optional[str] = None) -> int:
        """
        Main method to generate quizzes for papers without them.
        
        Args:
            limit: Maximum number of quizzes to generate (default: 5)
            target_date: Optional date filter in YYYY-MM-DD format (e.g., '2025-11-03')
            
        Returns:
            Number of quizzes successfully generated
        """
        try:
            if target_date:
                logger.info(f"Starting quiz generation for papers created on {target_date}")
            else:
                logger.info(f"Starting quiz generation for up to {limit} papers")
            
            # Get papers needing quizzes
            papers = self.get_papers_needing_quizzes(limit, target_date)
            
            if not papers:
                if target_date:
                    logger.info(f"No papers found that need quizzes for date {target_date}")
                else:
                    logger.info("No papers found that need quizzes")
                return 0
            
            logger.info(f"Found {len(papers)} papers to generate quizzes for")
            
            successful_count = 0
            failed_count = 0
            
            for i, paper in enumerate(papers, 1):
                logger.info(f"Processing paper {i}/{len(papers)}: {paper['arxiv_id']}")
                
                # Generate quiz
                quiz_data = self.generate_quiz_question(paper)
                
                if quiz_data:
                    # Save to database
                    if self.save_quiz_to_database(paper, quiz_data):
                        successful_count += 1
                        logger.info(f"✓ Quiz {i}/{len(papers)} completed for {paper['arxiv_id']}")
                    else:
                        failed_count += 1
                        logger.error(f"✗ Failed to save quiz {i}/{len(papers)} for {paper['arxiv_id']}")
                else:
                    failed_count += 1
                    logger.error(f"✗ Failed to generate quiz {i}/{len(papers)} for {paper['arxiv_id']}")
                
                # Small delay between papers to be respectful to API
                if i < len(papers):
                    time.sleep(1)
            
            logger.info(f"Quiz generation complete: {successful_count} successful, {failed_count} failed")
            return successful_count
            
        except Exception as e:
            logger.error(f"Error in quiz generation process: {str(e)}")
            raise

def main():
    """Main function to run the quiz generator."""
    import argparse
    from datetime import datetime as dt, timezone
    
    parser = argparse.ArgumentParser(
        description='Generate quiz questions for ArXiv paper summaries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto mode: Generate quizzes for today's papers (if max date = today)
  python3 generate_quiz.py
  
  # Generate quizzes for ALL papers created on a specific date
  python3 generate_quiz.py --date 2025-11-03
  
  # Legacy: Generate N quizzes from most recent papers
  python3 generate_quiz.py --limit 10 --legacy
        """
    )
    parser.add_argument('--limit', type=int, default=5, 
                       help='Number of quizzes to generate (default: 5). Only used with --legacy flag.')
    parser.add_argument('--date', type=str, default=None,
                       help='Generate quizzes for ALL papers created on this date (YYYY-MM-DD). Processes ALL papers from that date, no limit applied.')
    parser.add_argument('--legacy', action='store_true',
                       help='Use legacy mode: generate N most recent papers instead of auto date detection.')
    
    args = parser.parse_args()
    
    try:
        generator = QuizGenerator()
        
        # Determine which mode to run
        if args.date:
            # Explicit date mode
            target_date = args.date
            print(f"\nGenerating quizzes for papers created on {target_date}...")
        elif args.legacy:
            # Legacy mode: N most recent papers
            print(f"\nLegacy mode: Generating up to {args.limit} quizzes from recent papers...")
            generated_count = generator.generate_quizzes_for_papers(
                limit=args.limit,
                target_date=None
            )
            print(f"\n✓ Successfully generated {generated_count} quiz questions")
            return 0
        else:
            # AUTO MODE: Check max date in summary_papers and run for today if it matches
            logger.info("Running in AUTO mode: checking max date in summary_papers")
            print("\nAUTO MODE: Checking for papers from today...")
            
            # Get max date from summary_papers
            max_date_response = generator.supabase.table('summary_papers').select(
                'created_at'
            ).eq('processing_status', 'completed').order('created_at', desc=True).limit(1).execute()
            
            if not max_date_response.data:
                logger.warning("No papers found in summary_papers table")
                print("\n⚠ No papers found in summary_papers table")
                return 0
            
            # Extract date from max created_at
            max_created_at = max_date_response.data[0]['created_at']
            if 'T' in max_created_at:
                max_date = max_created_at.split('T')[0]
            else:
                max_date = max_created_at.split(' ')[0] if ' ' in max_created_at else max_created_at[:10]
            
            # Get current date in EST
            from datetime import timezone, timedelta
            est_tz = timezone(timedelta(hours=-5))  # EST is UTC-5
            current_date = dt.now(est_tz).strftime('%Y-%m-%d')
            
            logger.info(f"Max date in summary_papers: {max_date}")
            logger.info(f"Current date (EST): {current_date}")
            
            if max_date != current_date:
                logger.info(f"Max date ({max_date}) does not equal current date ({current_date}). Skipping quiz generation.")
                print(f"\n⚠ No papers from today yet.")
                print(f"   Max date in database: {max_date}")
                print(f"   Current date: {current_date}")
                print(f"\n✓ Script will run when papers from {current_date} are available.")
                return 0
            
            # Max date equals current date, proceed with quiz generation
            target_date = current_date
            logger.info(f"Max date equals current date. Generating quizzes for {target_date}")
            print(f"\n✓ Papers from today found! Generating quizzes for {target_date}...")
        
        # Generate quizzes for target_date
        generated_count = generator.generate_quizzes_for_papers(
            limit=args.limit,
            target_date=target_date
        )
        
        print(f"\n✓ Successfully generated {generated_count} quiz questions for papers from {target_date}")
        return 0
        
    except Exception as e:
        logger.error(f"Quiz generation failed: {str(e)}")
        print(f"\n✗ Quiz generation failed: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

