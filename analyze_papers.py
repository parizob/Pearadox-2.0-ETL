#!/usr/bin/env python3
"""
Analysis script to investigate paper counts and identify why there are more papers
needing summarization than expected.

This script will:
1. Count papers in arxiv_papers by date
2. Count papers in summary_papers by date
3. Identify papers without summaries
4. Show the breakdown of where the backlog is coming from
"""

import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_ANON_KEY')
    
    if not supabase_url or not supabase_key:
        print("❌ Missing Supabase credentials in environment variables")
        return 1
    
    supabase: Client = create_client(supabase_url, supabase_key)
    
    print("=" * 70)
    print("📊 PAPER ANALYSIS REPORT")
    print("=" * 70)
    print(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # =========================================================================
    # 1. Total counts
    # =========================================================================
    print("=" * 70)
    print("1️⃣  TOTAL COUNTS")
    print("=" * 70)
    
    # Count all arxiv_papers
    arxiv_papers = supabase.table('arxiv_papers').select('id', count='exact').execute()
    total_arxiv = arxiv_papers.count if arxiv_papers.count else len(arxiv_papers.data)
    print(f"📄 Total papers in arxiv_papers: {total_arxiv}")
    
    # Count all summary_papers
    summary_papers = supabase.table('summary_papers').select('id', count='exact').execute()
    total_summaries = summary_papers.count if summary_papers.count else len(summary_papers.data)
    print(f"📝 Total papers in summary_papers: {total_summaries}")
    
    # Count papers needing summaries
    try:
        needing_summaries = supabase.table('v_papers_needing_summaries').select('id').limit(5000).execute()
        total_needing = len(needing_summaries.data) if needing_summaries.data else 0
        print(f"⏳ Papers needing summarization: {total_needing}")
    except Exception as e:
        print(f"⏳ Papers needing summarization: (query failed: {str(e)[:50]})")
        total_needing = "unknown"
    
    print(f"\n📊 Summary rate: {total_summaries}/{total_arxiv} = {(total_summaries/total_arxiv*100):.1f}%" if total_arxiv > 0 else "N/A")
    print()
    
    # =========================================================================
    # 2. Papers by created_at date (arxiv_papers)
    # =========================================================================
    print("=" * 70)
    print("2️⃣  ARXIV_PAPERS BY CREATED_AT DATE (when loaded into DB)")
    print("=" * 70)
    
    # Get all arxiv_papers with created_at
    all_arxiv = supabase.table('arxiv_papers').select('id, arxiv_id, created_at').order('created_at', desc=True).limit(5000).execute()
    
    # Group by date
    arxiv_by_date = defaultdict(list)
    for paper in all_arxiv.data:
        created_at = paper.get('created_at', '')
        if created_at:
            date_part = created_at.split('T')[0] if 'T' in created_at else created_at[:10]
            arxiv_by_date[date_part].append(paper['arxiv_id'])
    
    # Sort and display
    sorted_dates = sorted(arxiv_by_date.keys(), reverse=True)
    print(f"\n{'Date':<15} {'Count':<10} {'Note'}")
    print("-" * 50)
    for date in sorted_dates[:15]:  # Show last 15 days
        count = len(arxiv_by_date[date])
        note = "⚠️ MORE THAN 50!" if count > 50 else ""
        print(f"{date:<15} {count:<10} {note}")
    
    if len(sorted_dates) > 15:
        older_count = sum(len(arxiv_by_date[d]) for d in sorted_dates[15:])
        print(f"{'(older)':<15} {older_count:<10}")
    
    print()
    
    # =========================================================================
    # 3. Summary_papers by created_at date
    # =========================================================================
    print("=" * 70)
    print("3️⃣  SUMMARY_PAPERS BY CREATED_AT DATE")
    print("=" * 70)
    
    all_summaries = supabase.table('summary_papers').select('id, arxiv_id, created_at, processing_status').order('created_at', desc=True).limit(5000).execute()
    
    # Group by date
    summaries_by_date = defaultdict(lambda: {'completed': 0, 'error': 0, 'pending': 0})
    for paper in all_summaries.data:
        created_at = paper.get('created_at', '')
        status = paper.get('processing_status', 'unknown')
        if created_at:
            date_part = created_at.split('T')[0] if 'T' in created_at else created_at[:10]
            if status == 'completed':
                summaries_by_date[date_part]['completed'] += 1
            elif status == 'error':
                summaries_by_date[date_part]['error'] += 1
            else:
                summaries_by_date[date_part]['pending'] += 1
    
    sorted_summary_dates = sorted(summaries_by_date.keys(), reverse=True)
    print(f"\n{'Date':<15} {'Completed':<12} {'Error':<10} {'Pending':<10}")
    print("-" * 50)
    for date in sorted_summary_dates[:15]:
        stats = summaries_by_date[date]
        print(f"{date:<15} {stats['completed']:<12} {stats['error']:<10} {stats['pending']:<10}")
    
    print()
    
    # =========================================================================
    # 4. Papers WITHOUT summaries (the backlog)
    # =========================================================================
    print("=" * 70)
    print("4️⃣  PAPERS WITHOUT SUMMARIES (THE BACKLOG)")
    print("=" * 70)
    
    # Get all arxiv_ids that have summaries
    summarized_ids = set()
    for paper in all_summaries.data:
        summarized_ids.add(paper.get('arxiv_id'))
    
    # Find papers without summaries
    papers_without_summaries = []
    for paper in all_arxiv.data:
        if paper.get('arxiv_id') not in summarized_ids:
            papers_without_summaries.append(paper)
    
    # Group by date
    backlog_by_date = defaultdict(list)
    for paper in papers_without_summaries:
        created_at = paper.get('created_at', '')
        if created_at:
            date_part = created_at.split('T')[0] if 'T' in created_at else created_at[:10]
            backlog_by_date[date_part].append(paper['arxiv_id'])
    
    sorted_backlog_dates = sorted(backlog_by_date.keys(), reverse=True)
    print(f"\nTotal papers without summaries: {len(papers_without_summaries)}")
    print(f"\n{'Date':<15} {'Backlog Count':<15} {'Sample arxiv_ids'}")
    print("-" * 70)
    for date in sorted_backlog_dates[:15]:
        ids = backlog_by_date[date]
        sample = ', '.join(ids[:3])
        if len(ids) > 3:
            sample += f" (+{len(ids)-3} more)"
        print(f"{date:<15} {len(ids):<15} {sample}")
    
    print()
    
    # =========================================================================
    # 5. Check for papers loaded BEFORE the 50-paper limit was implemented
    # =========================================================================
    print("=" * 70)
    print("5️⃣  DIAGNOSIS: WHY IS THERE A BACKLOG?")
    print("=" * 70)
    
    # Find dates with more than 50 papers loaded
    dates_over_50 = [(date, len(arxiv_by_date[date])) for date in sorted_dates if len(arxiv_by_date[date]) > 50]
    
    if dates_over_50:
        print("\n⚠️  FOUND DATES WITH MORE THAN 50 PAPERS LOADED:")
        print("   These are from BEFORE the 50-paper limit was implemented.")
        total_excess = 0
        for date, count in dates_over_50:
            excess = count - 50
            total_excess += excess
            print(f"   {date}: {count} papers ({excess} over the 50 limit)")
        print(f"\n   Total excess papers from old loads: {total_excess}")
    else:
        print("\n✅ No dates found with more than 50 papers loaded.")
    
    # Check for papers with NULL pdf_url (these won't appear in v_papers_needing_summaries)
    null_pdf = supabase.table('arxiv_papers').select('id, arxiv_id').is_('pdf_url', 'null').limit(100).execute()
    if null_pdf.data:
        print(f"\n⚠️  Papers with NULL pdf_url (won't be summarized): {len(null_pdf.data)}")
        print(f"   Sample: {[p['arxiv_id'] for p in null_pdf.data[:5]]}")
    
    # Summary
    print("\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    print(f"""
The backlog of {len(papers_without_summaries)} papers likely comes from:
1. Papers loaded BEFORE the 50-paper-per-day limit was implemented
2. Papers that failed summarization (check error status above)
3. Papers still in the queue from recent days

To clear the backlog:
- Run process_summaries.py multiple times (it processes 15 papers per batch)
- Estimated batches needed: {(len(papers_without_summaries) // 15) + 1}
- Estimated time: ~{((len(papers_without_summaries) // 15) + 1)} minutes (1 min per batch)

Going forward, with the 50-paper limit, the daily load will be manageable.
""")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())


