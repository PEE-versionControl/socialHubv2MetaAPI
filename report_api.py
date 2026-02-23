#!/usr/bin/env python3
"""
Report API Script (API Only)
==============================
Retrieves Business Insights (organic) and Ad Manager Insights (paid)
from the Meta Graph API. Exports one CSV per post.

Each CSV contains:
  - Post Insight headers + data row
  - Ad Manager headers + data rows (one per matched ad)

Usage:
    python3 report_api.py <url> <end_date>
    python3 report_api.py https://www.instagram.com/reels/DSpM2yniRzK 2026-02-15
    python3 report_api.py -f urls.txt                # batch mode
    python3 report_api.py --month 2026-01            # monthly auto-discover
    python3 report_api.py -f urls.txt -o ./reports/  # custom output directory
"""

import argparse
import csv
import os
import re
import sys
import time

from facebookSightTest5Feb import (
    process_single_url,
    parse_input_file,
    discover_fb_posts_for_month,
    discover_ig_posts_for_month,
    prescan_fb_ad_end_dates,
    construct_fb_post_url,
    construct_ig_post_url,
    get_ig_ad_end_date,
    ACCESS_TOKEN,
    PAGE_ID,
)
from datetime import datetime, timedelta


POST_HEADERS = [
    "Platform", "Post Link", "Date Range", "Views", "Reach",
    "Interactions", "Likes and reactions", "Comments", "Shares",
    "Saves", "Link clicks",
]

AD_HEADERS = [
    "Campaign Name", "Ad Set Name", "Date Range", "Amount spent",
    "Impression", "Reach", "Frequency", "Link Clicks", "Click(All)",
    "Post engagement", "Post reactions", "Post comments", "Post shares",
    "Post saves", "ThruPlays", "Video plays at 100%",
]


def _extract_id(url):
    """Extract shortcode or content ID from URL for filename."""
    m = re.search(r'/(?:p|reels?|videos|posts)/([^/?#&]+)', url)
    return m.group(1) if m else "unknown"


def export_single_post_csv(result, output_dir="."):
    """
    Export one CSV for a single post result.
    Returns the filename written.
    """
    platform = result.get("platform", "Unknown")
    url = result.get("url", "")
    content_id = _extract_id(url)
    date_str = datetime.now().strftime("%Y%m%d")
    prefix = "IG" if platform == "Instagram" else "FB"
    filename = f"report_{prefix}_{content_id}_{date_str}.csv"
    filepath = os.path.join(output_dir, filename)

    pm = result.get("post_metrics", {})
    ad_list = result.get("ad_metrics")

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Post Insight block
        writer.writerow(POST_HEADERS)
        writer.writerow([
            platform,
            url,
            result.get("date_range_str", ""),
            pm.get("Views", 0),
            pm.get("Reach", 0),
            pm.get("Interactions", 0),
            pm.get("Reactions_Total", 0),
            pm.get("Comments", 0),
            pm.get("Shares", 0),
            pm.get("Saves", 0),
            pm.get("Link_Clicks", 0),
        ])

        writer.writerow([])

        # Ad Manager block
        writer.writerow(AD_HEADERS)
        if ad_list:
            for am in ad_list:
                writer.writerow([
                    am.get("campaign_name", "N/A"),
                    am.get("adset_name", "N/A"),
                    result.get("date_range_str", ""),
                    f"{am.get('spend', 0):.2f}",
                    am.get("impressions", 0),
                    am.get("reach", 0),
                    f"{am.get('frequency', 0):.2f}",
                    am.get("link_clicks", 0),
                    am.get("clicks_all", 0),
                    am.get("post_engagement", 0),
                    am.get("reactions", 0),
                    am.get("comments", 0),
                    am.get("shares", 0),
                    am.get("saves", 0),
                    am.get("thruplays", 0),
                    am.get("video_100", 0),
                ])
        else:
            writer.writerow(["No ad data"] + [""] * 15)

    return filepath


def result_to_firestore_format(result, account_name=None):
    """
    Convert a process_single_url() result to a dict matching
    the Social Hub Firestore Post schema.
    Used by api_server.py to send Firestore-compatible data to frontend.
    account_name: optional override from the account registry (e.g. "Play Eat Easy")
                  used as fallback when URL-based detection fails (e.g. IG posts).
    """
    pm = result.get("post_metrics", {})
    url = result.get("url", "")
    platform = result.get("platform", "Unknown")

    # Detect platform code (matching parseCSV logic)
    platform_code = "Other"
    if "instagram" in url.lower():
        platform_code = "IG"
    elif "facebook" in url.lower():
        platform_code = "FB"

    # Detect if video
    is_video = any(x in url.lower() for x in ["/videos/", "/reel/", "/reels/"])

    # Detect account from URL (works for FB). For IG posts the URL has no account
    # name, so fall back to the account_name passed in from the account registry.
    account = None
    if "playeateasy" in url.lower():
        account = "Play Eat Easy"
    elif "pestyle" in url.lower():
        account = "Pestyle"
    if not account and account_name and account_name != "Default Account":
        account = account_name

    # Build title from post text. facebookSightTest5Feb.py stores it as "Title".
    # IG posts may also store it as "Caption". Exclude sentinel "Untitled" placeholder.
    # Fall back to empty string (not the raw URL ID/shortcode).
    _SENTINELS = {"Untitled", "No title", "untitled"}
    message = pm.get("Title", "") or pm.get("Caption", "") or pm.get("Message", "") or ""
    if message in _SENTINELS:
        message = ""
    title = message[:80] if message else ""

    # Parse created date
    date_range = result.get("date_range_str", "")
    created_date = None
    if date_range and " to " in date_range:
        start_str = date_range.split(" to ")[0]
        if start_str != "N/A":
            try:
                created_date = datetime.strptime(start_str, "%Y-%m-%d").isoformat()
            except ValueError:
                pass

    return {
        "postUrl": url,
        "platform": platform_code,
        "title": title,
        "content": message,
        "likes": pm.get("Reactions_Total", 0),
        "reach": pm.get("Reach", 0),
        "shares": pm.get("Shares", 0),
        "comments": pm.get("Comments", 0),
        "clicks": pm.get("Link_Clicks", 0),
        "isVideo": is_video,
        "account": account,
        "createdAt": created_date,
        # Report-only fields (not in Firestore schema, for display)
        "_views": pm.get("Views", 0),
        "_interactions": pm.get("Interactions", 0),
        "_saves": pm.get("Saves", 0),
        "_date_range": date_range,
        "_platform_full": platform,
    }


def build_work_items_for_month(year_month):
    """Build list of {url, end_date} for a given month. Reused by api_server."""
    parts = year_month.split("-")
    year = int(parts[0])
    month = int(parts[1])

    if month == 12:
        fallback_end = datetime(year + 1, 1, 1) + timedelta(days=2)
    else:
        fallback_end = datetime(year, month + 1, 1) + timedelta(days=2)
    fallback_end_str = fallback_end.strftime("%Y-%m-%d")

    print(f"Discovering FB posts for {year}-{month:02d}...")
    fb_posts = discover_fb_posts_for_month(year, month)
    print(f"  Found {len(fb_posts)} FB post(s)")

    print(f"Discovering IG posts for {year}-{month:02d}...")
    ig_posts = discover_ig_posts_for_month(year, month)
    print(f"  Found {len(ig_posts)} IG post(s)")

    print(f"Pre-scanning ad end dates...")
    fb_end_date_map = prescan_fb_ad_end_dates()

    work_items = []
    for fb_post in fb_posts:
        post_id = fb_post["id"]
        url = construct_fb_post_url(post_id, fb_post.get("permalink_url"))
        end_date = fb_end_date_map.get(post_id)
        if not end_date:
            raw_id = post_id.split("_")[1] if "_" in post_id else post_id
            for key, val in fb_end_date_map.items():
                if raw_id in key:
                    end_date = val
                    break
        if not end_date:
            permalink = fb_post.get("permalink_url", "")
            vid_match = re.search(r'/videos/(\d+)', permalink) or re.search(r'/reel/(\d+)', permalink)
            if vid_match and vid_match.group(1) in fb_end_date_map:
                end_date = fb_end_date_map[vid_match.group(1)]
        work_items.append({"url": url, "end_date": end_date or fallback_end_str})

    for ig_post in ig_posts:
        shortcode = ig_post["shortcode"]
        media_type = ig_post.get("media_type", "IMAGE")
        url = construct_ig_post_url(shortcode, media_type)
        end_date = get_ig_ad_end_date(ig_post["id"])
        work_items.append({"url": url, "end_date": end_date or fallback_end_str})

    return work_items


def main():
    parser = argparse.ArgumentParser(description="Meta API Report — per-post CSV export")
    parser.add_argument("url", nargs="?", help="Single post URL")
    parser.add_argument("end_date", nargs="?", help="End date (YYYY-MM-DD)")
    parser.add_argument("-f", "--file", help="Input file with URLs + end dates")
    parser.add_argument("--month", metavar="YYYY-MM", help="Monthly auto-discover mode")
    parser.add_argument("-o", "--output-dir", default=".", help="Output directory for CSVs")
    args = parser.parse_args()

    if not ACCESS_TOKEN or not PAGE_ID:
        print("Error: Missing FACEBOOK_ACCESS_TOKEN or FACEBOOK_PAGE_ID in .env")
        sys.exit(1)

    # Ensure output dir exists
    if args.output_dir != "." and not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir, exist_ok=True)

    # Build work items
    work_items = []
    if args.url and args.end_date:
        work_items = [{"url": args.url, "end_date": args.end_date}]
    elif args.file:
        entries = parse_input_file(args.file)
        work_items = [{"url": e["url"], "end_date": e["end_date"]} for e in entries]
    elif args.month:
        work_items = build_work_items_for_month(args.month)
    else:
        # Default: read urls.txt
        script_dir = os.path.dirname(os.path.abspath(__file__))
        input_path = os.path.join(script_dir, "urls.txt")
        if os.path.exists(input_path):
            entries = parse_input_file(input_path)
            work_items = [{"url": e["url"], "end_date": e["end_date"]} for e in entries]
        else:
            parser.print_help()
            sys.exit(1)

    if not work_items:
        print("No URLs to process.")
        sys.exit(1)

    start = time.time()
    exported = []

    for i, item in enumerate(work_items, 1):
        print(f"\n{'=' * 50}")
        print(f"[{i}/{len(work_items)}] {item['url']}")
        print(f"  End date: {item['end_date']}")

        result = process_single_url(item["url"], item["end_date"])
        if not result:
            print(f"  [!] Failed to process")
            continue

        filepath = export_single_post_csv(result, args.output_dir)
        exported.append(filepath)
        print(f"  -> {filepath}")

    elapsed = time.time() - start
    m, s = divmod(elapsed, 60)
    print(f"\nDone. {len(exported)}/{len(work_items)} CSVs exported. Time: {int(m)}m {s:.1f}s")
    for f in exported:
        print(f"  {f}")


if __name__ == "__main__":
    main()
