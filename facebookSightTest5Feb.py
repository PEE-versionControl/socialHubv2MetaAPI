
#!/usr/bin/env python3
"""
Facebook Combined Insights Script
===================================
Retrieves both Post Insights (organic) and Ad Manager Insights (paid)
from the Meta Graph API, producing a combined CSV report.

Supports post types: video, reel, photo, text post.

Usage:
    python facebook_insights.py                     Read URLs from urls.txt
    python facebook_insights.py -f my_urls.txt      Read URLs from custom file
    python facebook_insights.py --test              Test API connection

Input file format (one entry per line):
    <url> <end_date>
    https://www.facebook.com/page/videos/123456 2025-06-30
    https://www.facebook.com/reel/789012 2025-07-15

Lines starting with # are ignored.
"""

import argparse
import requests
import re
import os
import sys
import csv
import time
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")  # Separate token for IG insights
PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
AD_ACCOUNT_ID = os.getenv("FACEBOOK_AD_ACCOUNT_ID")
API_VERSION = "v24.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


# =============================================================================
# UTILITY
# =============================================================================

def safe_api_call(url, params, description="API call"):
    """Safe API call with error handling and rate-limit delay."""
    time.sleep(0.5)
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if "error" in data:
            print(f"  [!] {description}: {data['error'].get('message', 'Unknown')}")
            return None
        return data
    except requests.RequestException as e:
        print(f"  [!] Request failed ({description}): {e}")
        return None


def resolve_pfbid(url):
    """Resolve a pfbid-format Facebook URL to a numeric post ID.

    Strategy 1: Direct pfbid node lookup — GET /{pfbid}?fields=id
    Strategy 2: URL resolver — GET /?id={url}&fields=id (with validation)

    The URL resolver often echoes the pfbid URL back unchanged; we validate
    that the returned id is numeric/composite (not a URL or pfbid string).

    Returns the raw numeric post ID (without PAGE_ID prefix), or None on failure.
    """
    # Extract the pfbid token from the URL (use broad pattern to capture dashes too)
    match = re.search(r'/posts/([^/?#\s]+)', url)
    if not match or not match.group(1).startswith("pfbid"):
        print(f"  [pfbid] Could not extract pfbid token from URL.")
        return None
    pfbid_str = match.group(1)
    print(f"  [pfbid] Resolving {pfbid_str[:24]}... to numeric post ID...")

    def _extract_raw_id(obj_id):
        """Return raw post ID from composite PAGE_ID_POST_ID, or None if invalid."""
        if not obj_id or obj_id.startswith("http") or obj_id.startswith("pfbid"):
            return None  # URL resolver echoed the URL back — not a real node ID
        return obj_id.split("_", 1)[1] if "_" in obj_id else obj_id

    # Strategy 1: use {PAGE_ID}_{pfbid} as a composite Graph API node ID
    # (bare pfbid without PAGE_ID prefix fails with #12 deprecated)
    composite_pfbid = f"{PAGE_ID}_{pfbid_str}"
    data = safe_api_call(
        f"{BASE_URL}/{composite_pfbid}",
        {"fields": "id", "access_token": ACCESS_TOKEN},
        "pfbid composite node lookup",
    )
    if data:
        raw_id = _extract_raw_id(data.get("id", ""))
        if raw_id:
            print(f"  [pfbid] Resolved (direct lookup) -> post_id={raw_id}")
            return raw_id

    # Strategy 2: URL resolver (GET /?id={url}&fields=id)
    data = safe_api_call(
        BASE_URL,
        {"id": url, "fields": "id", "access_token": ACCESS_TOKEN},
        "pfbid URL resolver",
    )
    if data:
        raw_id = _extract_raw_id(data.get("id", ""))
        if raw_id:
            print(f"  [pfbid] Resolved (URL resolver) -> post_id={raw_id}")
            return raw_id

    print(f"  [pfbid] Could not resolve to numeric ID — both strategies failed.")
    return None


def detect_post_type(url):
    """Detect content type from URL."""
    # Instagram URLs (handle both /reel/ and /reels/)
    if re.search(r'instagram\.com/reels?/', url):
        return "ig_reel"
    elif re.search(r'instagram\.com/p/', url):
        return "ig_post"
    # Facebook URLs
    elif re.search(r'/videos/(\d+)', url) or re.search(r'/watch/\?v=(\d+)', url):
        return "video"
    elif re.search(r'/reel/(\d+)', url):
        return "reel"
    elif re.search(r'/photos?/', url) or re.search(r'[?&]fbid=\d+', url):
        return "photo"
    elif re.search(r'/posts/', url):
        return "post"
    return "unknown"


def resolve_post_type_via_api(content_id):
    """
    For /posts/ URLs, query the API to determine if the post is actually
    a video/reel. Returns (resolved_type, video_id_or_None).

    NOTE: Fields 'type', 'object_id', 'source', 'attachments' are DEPRECATED
    in Graph API v3.3+. We use post_activity_by_action_type to detect the post,
    then probe potential video IDs directly.

    Strategy:
      1. Try fetching post with non-deprecated fields
      2. Check if post_activity_by_action_type has video-related actions
      3. Try probing the content_id itself as a video object
      4. Check the post's permalink/story for video references
    """
    post_id = f"{PAGE_ID}_{content_id}" if "_" not in content_id else content_id

    print(f"\n[*] Resolving post type via API for {post_id}...")

    # Method 1: Try non-deprecated fields first
    data = safe_api_call(
        f"{BASE_URL}/{post_id}",
        {
            "access_token": ACCESS_TOKEN,
            "fields": "id,created_time,message,permalink_url"
        },
        "Resolve Post Type"
    )

    if not data:
        # Post ID might not work with composite format, try raw ID
        print(f"  [*] Trying raw ID: {content_id}...")
        data = safe_api_call(
            f"{BASE_URL}/{content_id}",
            {
                "access_token": ACCESS_TOKEN,
                "fields": "id,created_time,message,permalink_url"
            },
            "Resolve Post Type (raw)"
        )

    if data:
        permalink = data.get("permalink_url", "")
        print(f"  Post found. Permalink: {permalink[:60]}")

        # Check if permalink contains video/reel indicators
        if "/videos/" in permalink or "/reel/" in permalink:
            # Extract video ID from permalink
            video_match = re.search(r'/videos/(\d+)', permalink) or re.search(r'/reel/(\d+)', permalink)
            if video_match:
                video_id = video_match.group(1)
                print(f"  -> Post is a video via permalink (video_id: {video_id})")
                return "video", video_id

    # Method 2: Probe content_id directly as a video object
    print(f"  [*] Probing {content_id} as video object...")
    probe = safe_api_call(
        f"{BASE_URL}/{content_id}",
        {"access_token": ACCESS_TOKEN, "fields": "id,views,post_id,title"},
        "Video Probe"
    )
    if probe and "views" in probe:
        print(f"  -> Confirmed video via probe (video_id: {content_id}, views: {probe['views']})")
        return "video", content_id

    # Method 3: Check post insights to see if video metrics exist
    print(f"  [*] Checking if post has video metrics...")
    check = safe_api_call(
        f"{BASE_URL}/{post_id}/insights",
        {"access_token": ACCESS_TOKEN, "metric": "post_video_views", "period": "lifetime"},
        "Video Metric Probe"
    )
    if check and "data" in check and len(check["data"]) > 0:
        val = check["data"][0]["values"][0]["value"]
        if val > 0:
            print(f"  -> Post has video views ({val}), but could not find video_id")

    print(f"  -> Post type: photo/link/status (not a video)")
    return "post", None


def extract_id_from_url(url, post_type):
    """Extract the relevant ID from the URL based on post type."""
    if post_type in ("video", "reel"):
        patterns = [
            r'/videos/(\d+)',
            r'video_id=(\d+)',
            r'/reel/(\d+)',
            r'/watch/\?v=(\d+)',
            r'asset_id=(\d+)',
            r'v=(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
    elif post_type == "photo":
        # Check ?fbid= query parameter first (e.g., /photo/?fbid=123456)
        match = re.search(r'[?&]fbid=(\d+)', url)
        if match:
            return match.group(1)
        match = re.search(r'/photos/[^/]+/(\d+)', url)
        if match:
            return match.group(1)
        match = re.search(r'/photos/(\d+)', url)
        if match:
            return match.group(1)
    elif post_type == "post":
        match = re.search(r'/posts/(\w+)', url)
        if match:
            extracted = match.group(1)
            if extracted.startswith('pfbid'):
                resolved = resolve_pfbid(url)
                return resolved if resolved else extracted
            return extracted
    elif post_type == "ig_reel":
        # Handle both /reel/ and /reels/
        match = re.search(r'instagram\.com/reels?/([A-Za-z0-9_-]+)', url)
        if match:
            return match.group(1)
    elif post_type == "ig_post":
        match = re.search(r'instagram\.com/p/([A-Za-z0-9_-]+)', url)
        if match:
            return match.group(1)
    return None


# =============================================================================
# MONTHLY MODE: POST DISCOVERY
# =============================================================================

def discover_fb_posts_for_month(year, month):
    """Discover all Facebook Page posts published in the given month.

    Tries published_posts first, falls back to feed, then ad-account scan.
    Returns list of dicts: [{id, created_time, permalink_url, message}, ...]
    """
    # Month boundaries as Unix timestamps
    month_start = datetime(year, month, 1)
    if month == 12:
        month_end = datetime(year + 1, 1, 1)
    else:
        month_end = datetime(year, month + 1, 1)
    since_ts = int(month_start.timestamp())
    until_ts = int(month_end.timestamp())

    fields = "id,created_time,message,permalink_url"

    # Method 1: published_posts
    print("  Trying /{page_id}/published_posts...")
    posts = _fetch_fb_posts_endpoint(
        f"{BASE_URL}/{PAGE_ID}/published_posts",
        fields, since_ts, until_ts
    )
    if posts is not None:
        return posts

    # Method 2: page feed (filter by page's own posts)
    print("  Trying /{page_id}/feed (fallback)...")
    posts = _fetch_fb_posts_endpoint(
        f"{BASE_URL}/{PAGE_ID}/feed",
        fields + ",from", since_ts, until_ts
    )
    if posts is not None:
        # Filter to only page's own posts
        posts = [p for p in posts if p.get("from", {}).get("id") == PAGE_ID]
        return posts

    # Method 3: Reverse-discover from ad account
    print("  Trying ad account scan (last resort - only finds boosted posts)...")
    return _discover_fb_posts_from_ads(month_start, month_end)


def _fetch_fb_posts_endpoint(endpoint_url, fields, since_ts, until_ts):
    """Fetch posts from a FB endpoint with pagination. Returns list or None on error."""
    all_posts = []
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": fields,
        "since": since_ts,
        "until": until_ts,
        "limit": 100,
    }
    request_url = endpoint_url
    page_num = 0

    while request_url:
        page_num += 1
        time.sleep(0.5)
        data = safe_api_call(request_url, params, f"FB Posts page {page_num}")
        if data is None:
            return None  # API error — try next method
        if "data" not in data:
            return None

        all_posts.extend(data["data"])

        # Paginate
        next_url = data.get("paging", {}).get("next")
        if next_url and data["data"]:
            request_url = next_url
            params = {}  # Next URL has params embedded
        else:
            break

    return all_posts


def _discover_fb_posts_from_ads(month_start, month_end):
    """Scan ad account for ads active in the period. Extract unique post IDs.
    Only finds posts that had ads — incomplete but a fallback."""
    if not AD_ACCOUNT_ID:
        return []

    time_range = json.dumps({
        "since": month_start.strftime("%Y-%m-%d"),
        "until": month_end.strftime("%Y-%m-%d"),
    })
    fields = f"creative{{effective_object_story_id,video_id}},insights.time_range({time_range}){{date_start}}"

    request_url = f"{BASE_URL}/{AD_ACCOUNT_ID}/ads"
    params = {"access_token": ACCESS_TOKEN, "limit": 100, "fields": fields}

    seen_post_ids = set()
    results = []
    page_num = 0

    while request_url:
        page_num += 1
        time.sleep(0.5)
        data = safe_api_call(request_url, params, f"Ad scan page {page_num}")
        if not data or "data" not in data:
            break

        for ad in data["data"]:
            creative = ad.get("creative", {})
            story_id = creative.get("effective_object_story_id", "")
            if story_id and story_id not in seen_post_ids:
                seen_post_ids.add(story_id)
                # Fetch post metadata
                raw_id = story_id.split("_")[1] if "_" in story_id else story_id
                results.append({
                    "id": story_id,
                    "created_time": None,
                    "permalink_url": f"https://www.facebook.com/{PAGE_ID}/posts/{raw_id}",
                    "message": "",
                })

        next_url = data.get("paging", {}).get("next")
        if next_url and data["data"]:
            request_url = next_url
            params = {}
        else:
            break

    return results


def discover_ig_posts_for_month(year, month):
    """Discover all Instagram posts/reels published in the given month.

    Fetches media in reverse-chronological order, stopping when we hit
    posts older than the target month.
    Returns list of dicts: [{id, shortcode, media_type, timestamp, permalink}, ...]
    """
    ig_user_id = resolve_instagram_business_account()
    if not ig_user_id:
        print("  [!] No IG Business Account found")
        return []

    ig_token = get_ig_token()

    # Month boundaries
    month_start = datetime(year, month, 1)
    if month == 12:
        month_end = datetime(year + 1, 1, 1)
    else:
        month_end = datetime(year, month + 1, 1)

    all_media = []
    request_url = f"{BASE_URL}/{ig_user_id}/media"
    params = {
        "access_token": ig_token,
        "fields": "id,shortcode,media_type,timestamp,permalink",
        "limit": 300,
    }
    page_num = 0
    found_older = False

    while request_url and not found_older:
        page_num += 1
        time.sleep(0.5)
        data = safe_api_call(request_url, params, f"IG Media Discovery page {page_num}")
        if not data or "data" not in data:
            break

        for media in data["data"]:
            ts = media.get("timestamp", "")
            try:
                media_dt = datetime.fromisoformat(
                    ts.replace("+0000", "+00:00").replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue

            if media_dt < month_start:
                found_older = True
                break

            if month_start <= media_dt < month_end:
                all_media.append(media)

        # Paginate
        next_url = data.get("paging", {}).get("next")
        if next_url and not found_older:
            request_url = next_url
            params = {}
        else:
            break

    return all_media


def construct_fb_post_url(post_id, permalink_url=None):
    """Build a Facebook post URL from post_id or permalink."""
    if permalink_url:
        return permalink_url
    raw_id = post_id.split("_")[1] if "_" in post_id else post_id
    return f"https://www.facebook.com/{PAGE_ID}/posts/{raw_id}"


def construct_ig_post_url(shortcode, media_type):
    """Build an Instagram URL from shortcode and media type."""
    if media_type == "VIDEO":
        return f"https://www.instagram.com/reel/{shortcode}"
    return f"https://www.instagram.com/p/{shortcode}"


# =============================================================================
# POST INSIGHTS COLLECTION
# =============================================================================

def collect_video_insights(video_id, post_type):
    """Collect post insights for video/reel content."""
    print("\n" + "=" * 60)
    print("COLLECTING POST INSIGHTS")
    print("=" * 60)
    print(f"\nContent ID: {video_id} (type: {post_type})")

    metrics = {}
    created_time = None

    # Endpoint 1: Video object fields
    print("\n[1/4] GET /{video_id} -> Views, Post ID")
    data = safe_api_call(
        f"{BASE_URL}/{video_id}",
        {"access_token": ACCESS_TOKEN, "fields": "views,post_views,post_id,title,created_time"},
        "Video Object"
    )

    post_id = None
    if data:
        metrics["Views"] = data.get("views", 0)
        metrics["Views_3sec"] = data.get("post_views", 0)
        metrics["Title"] = data.get("title", "Untitled")
        created_time = data.get("created_time")

        raw_post_id = data.get("post_id")
        if raw_post_id:
            post_id = f"{PAGE_ID}_{raw_post_id}"

        print(f"  Views (reels_play): {metrics['Views']:,}")
        print(f"  Views (3-second):   {metrics['Views_3sec']:,}")
        print(f"  Post ID: {post_id}")

    if not post_id:
        print("  [!] Could not resolve Post ID. Some metrics will be unavailable.")

    # Endpoint 2: Video insights
    print("\n[2/4] GET /{video_id}/video_insights -> Reach, Reactions, Shares, Comments")
    data = safe_api_call(
        f"{BASE_URL}/{video_id}/video_insights",
        {"access_token": ACCESS_TOKEN},
        "Video Insights"
    )

    if data and "data" in data:
        for item in data["data"]:
            name = item["name"]
            val = item["values"][0]["value"]

            if name == "post_impressions_unique":
                metrics["Reach"] = val
            elif name == "post_video_likes_by_reaction_type" and isinstance(val, dict):
                metrics["Reactions_Total"] = sum(val.values())
            elif name == "post_video_social_actions" and isinstance(val, dict):
                metrics["Comments"] = val.get("COMMENT", 0)
                metrics["Shares"] = val.get("SHARE", 0)

        print(f"  Reach:     {metrics.get('Reach', 0):,}")
        print(f"  Reactions: {metrics.get('Reactions_Total', 0):,}")
        print(f"  Comments:  {metrics.get('Comments', 0):,}")
        print(f"  Shares:    {metrics.get('Shares', 0):,}")

    # Endpoint 3-4: Clicks
    print("\n[3/4] GET /{post_id}/insights -> Clicks breakdown")
    if post_id:
        url = f"{BASE_URL}/{post_id}/insights"

        data = safe_api_call(
            url,
            {"access_token": ACCESS_TOKEN, "metric": "post_clicks_by_type", "period": "lifetime"},
            "Clicks by Type"
        )
        if data and "data" in data and len(data["data"]) > 0:
            val = data["data"][0]["values"][0]["value"]
            if isinstance(val, dict):
                metrics["Link_Clicks"] = val.get("link clicks", 0)

        data = safe_api_call(
            url,
            {"access_token": ACCESS_TOKEN, "metric": "post_clicks", "period": "lifetime"},
            "Post Clicks Total"
        )
        if data and "data" in data and len(data["data"]) > 0:
            metrics["Post_Clicks_Total"] = data["data"][0]["values"][0]["value"]

        print(f"  Link Clicks:  {metrics.get('Link_Clicks', 0):,}")
        print(f"  Total Clicks: {metrics.get('Post_Clicks_Total', 0):,}")

    # Endpoint 5-9: Views breakdown
    print("\n[4/4] GET /{post_id}/insights -> Views breakdown (Organic/Paid)")
    if post_id:
        url = f"{BASE_URL}/{post_id}/insights"
        view_metrics = [
            ("post_video_views_organic", "Views_Organic"),
            ("post_video_views_paid", "Views_Paid"),
            ("post_video_views_unique", "Views_Unique"),
            ("post_video_complete_views_organic", "Complete_Views_Organic"),
            ("post_video_complete_views_paid", "Complete_Views_Paid"),
        ]
        for api_metric, label in view_metrics:
            data = safe_api_call(
                url,
                {"access_token": ACCESS_TOKEN, "metric": api_metric, "period": "lifetime"},
                f"Metric: {api_metric}"
            )
            if data and "data" in data and len(data["data"]) > 0:
                metrics[label] = data["data"][0]["values"][0]["value"]

    # Calculate Interactions
    metrics["Interactions"] = (
        metrics.get("Reactions_Total", 0) +
        metrics.get("Comments", 0) +
        metrics.get("Shares", 0)
    )

    # Flag for ad scan optimization: check multiple paid signals
    # Reach-objective ads may NOT show in Views_Paid, so check broadly
    paid_views = metrics.get("Views_Paid", 0)
    paid_complete = metrics.get("Complete_Views_Paid", 0)
    has_paid = (paid_views > 0) or (paid_complete > 0)
    # Conservative: if paid metrics weren't fetched at all, assume ads may exist
    if "Views_Paid" not in metrics:
        has_paid = True  # couldn't check — scan to be safe
    metrics["_has_paid_activity"] = has_paid
    if has_paid:
        print(f"  [i] Paid signal detected (Views_Paid={paid_views:,}, Complete_Paid={paid_complete:,}) — will scan for ads")
    else:
        print(f"  [i] No paid activity detected — ad scan will be skipped")

    return metrics, created_time, post_id


def collect_photo_post_insights(content_id, post_type):
    """Collect post insights for photo or text post content.

    Uses these endpoints:
      1. GET /{post_id}?fields=created_time,message         -> Post metadata
      2. GET /{post_id}/insights?metric=post_impressions_unique  -> Reach
      3. GET /{post_id}/insights?metric=post_reactions_by_type_total -> Reactions breakdown
      4. GET /{post_id}/insights?metric=post_activity_by_action_type -> Comments, Shares
      5. GET /{post_id}/insights?metric=post_clicks_by_type  -> Link Clicks
    """
    print("\n" + "=" * 60)
    print("COLLECTING POST INSIGHTS")
    print("=" * 60)
    print(f"\nContent ID: {content_id} (type: {post_type})")

    metrics = {}
    created_time = None

    # For photos/posts, construct composite post ID
    if "_" in content_id:
        post_id = content_id
    else:
        post_id = f"{PAGE_ID}_{content_id}"

    # Step 1: Get post object for created_time
    # NOTE: Do NOT request 'type', 'object_id', 'source', 'attachments', 'shares'
    #       — these are DEPRECATED in Graph API v3.3+
    print("\n[1/5] GET /{post_id} -> Post metadata")
    data = safe_api_call(
        f"{BASE_URL}/{post_id}",
        {"access_token": ACCESS_TOKEN, "fields": "created_time,message"},
        "Post Object"
    )
    if data:
        created_time = data.get("created_time")
        metrics["Title"] = data.get("message", "Untitled")[:50]
        print(f"  Created: {created_time}")
    else:
        print(f"  [!] Post object query failed, trying without composite ID...")
        data = safe_api_call(
            f"{BASE_URL}/{content_id}",
            {"access_token": ACCESS_TOKEN, "fields": "id,created_time,message"},
            "Post Object (raw ID)"
        )
        if data:
            created_time = data.get("created_time")
            metrics["Title"] = data.get("message", "Untitled")[:50]
            # Update post_id if we got a valid ID back
            returned_id = data.get("id")
            if returned_id and "_" in returned_id:
                post_id = returned_id
            print(f"  Created: {created_time}")
            print(f"  Post ID: {post_id}")

    url = f"{BASE_URL}/{post_id}/insights"

    # Step 2: Post insights - Reach
    print("\n[2/5] GET /{post_id}/insights -> Reach")
    data = safe_api_call(
        url,
        {"access_token": ACCESS_TOKEN, "metric": "post_impressions_unique", "period": "lifetime"},
        "Metric: post_impressions_unique"
    )
    if data and "data" in data and len(data["data"]) > 0:
        metrics["Reach"] = data["data"][0]["values"][0]["value"]
        print(f"  Reach: {metrics['Reach']:,}")

    # Step 3: Reactions via post_reactions_by_type_total
    print("\n[3/5] GET /{post_id}/insights -> Reactions, Comments, Shares")
    data = safe_api_call(
        url,
        {"access_token": ACCESS_TOKEN, "metric": "post_reactions_by_type_total", "period": "lifetime"},
        "Reactions by Type"
    )
    if data and "data" in data and len(data["data"]) > 0:
        val = data["data"][0]["values"][0]["value"]
        if isinstance(val, dict):
            metrics["Reactions_Total"] = sum(val.values())
            print(f"  Reactions: {metrics['Reactions_Total']:,}")

    # Comments and Shares via post_activity_by_action_type
    # This is the CORRECT source for Comments & Shares on non-video posts.
    # Returns: {"share": N, "like": N, "comment": N}
    data = safe_api_call(
        url,
        {"access_token": ACCESS_TOKEN, "metric": "post_activity_by_action_type", "period": "lifetime"},
        "Activity by Action Type"
    )
    if data and "data" in data and len(data["data"]) > 0:
        val = data["data"][0]["values"][0]["value"]
        if isinstance(val, dict):
            metrics["Comments"] = val.get("comment", 0)
            metrics["Shares"] = val.get("share", 0)
            print(f"  Comments: {metrics['Comments']:,}")
            print(f"  Shares: {metrics['Shares']:,}")

    # Step 4: Clicks
    print("\n[4/5] GET /{post_id}/insights -> Clicks")
    data = safe_api_call(
        url,
        {"access_token": ACCESS_TOKEN, "metric": "post_clicks_by_type", "period": "lifetime"},
        "Clicks by Type"
    )
    if data and "data" in data and len(data["data"]) > 0:
        val = data["data"][0]["values"][0]["value"]
        if isinstance(val, dict):
            metrics["Link_Clicks"] = val.get("link clicks", 0)
            print(f"  Link Clicks: {metrics['Link_Clicks']:,}")

    # Step 5: Views for non-video posts
    # As of Nov 2025, post_impressions is DEPRECATED.
    # Replacement: post_media_view (with optional is_from_ads / is_from_followers breakdowns)
    print("\n[5/5] GET /{post_id}/insights -> Views (post_media_view)")

    # Primary: post_media_view (replaces post_impressions)
    data = safe_api_call(
        url,
        {"access_token": ACCESS_TOKEN, "metric": "post_media_view", "period": "lifetime"},
        "Metric: post_media_view"
    )
    if data and "data" in data and len(data["data"]) > 0:
        val = data["data"][0]["values"][0]["value"]
        if isinstance(val, dict):
            metrics["Views"] = sum(val.values())
            print(f"  Views (post_media_view): {metrics['Views']:,} (breakdown: {val})")
        else:
            metrics["Views"] = val
            print(f"  Views (post_media_view): {metrics['Views']:,}")
    else:
        # Fallback: try post_media_view with breakdown
        print(f"  [!] post_media_view without breakdown failed, trying with is_from_ads breakdown...")
        data = safe_api_call(
            url,
            {"access_token": ACCESS_TOKEN, "metric": "post_media_view",
             "period": "lifetime", "breakdown": "is_from_ads"},
            "Metric: post_media_view (is_from_ads breakdown)"
        )
        if data and "data" in data and len(data["data"]) > 0:
            val = data["data"][0]["values"][0]["value"]
            if isinstance(val, dict):
                metrics["Views"] = sum(val.values())
                print(f"  Views (post_media_view breakdown): {metrics['Views']:,} (breakdown: {val})")
            else:
                metrics["Views"] = val
                print(f"  Views (post_media_view breakdown): {metrics['Views']:,}")
        else:
            # Last resort: try legacy post_impressions_unique (still works, gives Reach not Views)
            print(f"  [!] post_media_view failed, falling back to post_impressions_organic_unique + paid_unique...")
            views_total = 0
            for imp_metric in ["post_impressions_organic_unique", "post_impressions_paid_unique"]:
                d = safe_api_call(
                    url,
                    {"access_token": ACCESS_TOKEN, "metric": imp_metric, "period": "lifetime"},
                    f"Metric: {imp_metric}"
                )
                if d and "data" in d and len(d["data"]) > 0:
                    v = d["data"][0]["values"][0]["value"]
                    views_total += v
                    print(f"    {imp_metric}: {v:,}")
            metrics["Views"] = views_total
            if views_total > 0:
                print(f"  [i] Views (unique fallback sum): {views_total:,}")
            else:
                print(f"  [!] Could not retrieve Views for this post")

    print(f"  => Views = {metrics.get('Views', 0):,}")
    metrics.setdefault("Comments", 0)
    metrics.setdefault("Shares", 0)
    metrics.setdefault("Reactions_Total", 0)
    metrics.setdefault("Link_Clicks", 0)

    # Calculate Interactions = Reactions + Comments + Shares
    metrics["Interactions"] = (
        metrics.get("Reactions_Total", 0) +
        metrics.get("Comments", 0) +
        metrics.get("Shares", 0)
    )

    print(f"\n  Summary: Reach={metrics.get('Reach', 0):,} | Interactions={metrics['Interactions']:,} | Link Clicks={metrics.get('Link_Clicks', 0):,}")

    # Flag for ad scan optimization: check if post has any paid views
    # Try post_media_view with is_from_ads breakdown to detect paid activity
    # Conservative: default to True (scan ads) if check is inconclusive
    has_paid = True  # safe default
    paid_check = safe_api_call(
        f"{BASE_URL}/{post_id}/insights",
        {"access_token": ACCESS_TOKEN, "metric": "post_media_view",
         "period": "lifetime", "breakdown": "is_from_ads"},
        "Paid activity check (post_media_view is_from_ads)"
    )
    if paid_check and "data" in paid_check and len(paid_check["data"]) > 0:
        val = paid_check["data"][0]["values"][0]["value"]
        if isinstance(val, dict):
            paid_views = int(val.get("true", val.get("True", 0)) or 0)
            has_paid = paid_views > 0
            print(f"  [i] Paid views from breakdown: {paid_views:,}")
        elif isinstance(val, (int, float)) and val == 0:
            has_paid = False  # total views = 0 means no activity at all
    # else: API call failed or unexpected format → keep has_paid=True (safe)
    metrics["_has_paid_activity"] = has_paid
    if has_paid:
        print(f"  [i] Paid activity detected — will scan for ads")
    else:
        print(f"  [i] No paid views detected — ad scan will be skipped")

    return metrics, created_time, post_id


# =============================================================================
# INSTAGRAM INSIGHTS
# =============================================================================

def get_ig_token():
    """Return the best available token for IG API calls."""
    return IG_ACCESS_TOKEN or ACCESS_TOKEN


def resolve_instagram_business_account():
    """Get the Instagram Business Account ID linked to the Facebook Page."""
    # Try with IG token first, then FB token
    for token, label in [(IG_ACCESS_TOKEN, "IG token"), (ACCESS_TOKEN, "FB token")]:
        if not token:
            continue
        data = safe_api_call(
            f"{BASE_URL}/{PAGE_ID}",
            {"access_token": token, "fields": "instagram_business_account"},
            f"IG Business Account ({label})"
        )
        if data and "instagram_business_account" in data:
            return data["instagram_business_account"]["id"]
    return None


def find_ig_media_by_shortcode(ig_user_id, shortcode, hint_date=None):
    """Search media on the IG account to find the media ID matching a shortcode.

    Fetches up to 300 most-recent media items in a single call.
    The IG /media endpoint does not reliably support since/until filtering,
    so we always use limit=300 without a date filter.

    hint_date is kept as a parameter for API compatibility but is unused here.
    If the post is not in the first 300 items, resolve_ig_media_via_url handles
    the paginated fallback search.

    Uses IG token for this endpoint.
    """
    ig_token = get_ig_token()
    request_url = f"{BASE_URL}/{ig_user_id}/media"
    params = {
        "access_token": ig_token,
        "fields": "id,shortcode,media_type,timestamp,permalink",
        "limit": 300,
    }

    print(f"    Fetching media list (limit=300)...")

    data = safe_api_call(request_url, params, "IG Media Search")

    if not data or "data" not in data:
        print(f"    [!] No data returned from media endpoint")
        return None

    media_list = data["data"]
    print(f"    Retrieved {len(media_list)} media items")

    # Search for matching shortcode
    for media in media_list:
        sc = media.get("shortcode", "")
        if sc == shortcode:
            print(f"    Found match: id={media.get('id')} (shortcode={sc})")
            return media

    # Fallback: check permalink
    for media in media_list:
        permalink = media.get("permalink", "")
        if f"/{shortcode}" in permalink:
            print(f"    Found match via permalink: id={media.get('id')}")
            return media

    print(f"    [!] Shortcode '{shortcode}' not found in {len(media_list)} media items")
    return None


def resolve_ig_media_via_url(ig_user_id, shortcode, post_type, hint_date=None):
    """Fallback: try to find IG media ID via the Instagram URL using oEmbed or
    by paginating the media list with timestamp-based early stopping."""
    # Build the original Instagram URL
    if post_type == "ig_reel":
        ig_url = f"https://www.instagram.com/reel/{shortcode}/"
    else:
        ig_url = f"https://www.instagram.com/p/{shortcode}/"

    ig_token = get_ig_token()

    # Try oEmbed endpoint to at least confirm the post exists
    print(f"  [*] Trying oEmbed for: {ig_url}")
    data = safe_api_call(
        f"{BASE_URL}/instagram_oembed",
        {"url": ig_url, "access_token": ig_token},
        "IG oEmbed"
    )
    if data:
        print(f"  oEmbed returned data (title: {data.get('title', 'N/A')[:50]})")

    # Paginate through media WITHOUT since/until — the IG /media endpoint does not
    # reliably support timestamp filtering and silently fails when those params are
    # present. Instead, paginate page-by-page and stop early once timestamps go
    # older than the earliest plausible publish date for this post.
    stop_before_dt = datetime.now() - timedelta(days=730)  # 2-year hard cutoff
    if hint_date:
        try:
            end_dt = datetime.strptime(hint_date, "%Y-%m-%d")
            # Post must have been published before end_date; allow generous 18-month window
            stop_before_dt = end_dt - timedelta(days=548)
        except ValueError:
            pass

    print(f"  [*] Paginating media (early-stop before {stop_before_dt.date()}, max 20 pages)...")
    request_url = f"{BASE_URL}/{ig_user_id}/media"
    params = {
        "access_token": ig_token,
        "fields": "id,shortcode,media_type,timestamp,permalink",
        "limit": 100,
    }
    page_num = 0
    while request_url and page_num < 20:
        page_num += 1
        time.sleep(0.3)
        resp = safe_api_call(request_url, params, f"IG Broad Search (page {page_num})")
        if not resp or "data" not in resp:
            break
        items = resp["data"]
        print(f"    Page {page_num}: {len(items)} items", end="")
        oldest_ts = items[-1].get("timestamp", "") if items else ""
        print(f" | oldest: {oldest_ts[:10]}" if oldest_ts else "")
        for media in items:
            sc = media.get("shortcode", "")
            permalink = media.get("permalink", "")
            if sc == shortcode or shortcode in permalink:
                print(f"  [*] Found via fallback on page {page_num}: id={media.get('id')}")
                return media
        # Early stop: if oldest item on this page is before our cutoff, give up
        if oldest_ts:
            try:
                oldest_dt = datetime.fromisoformat(
                    oldest_ts.replace("+0000", "+00:00").replace("Z", "+00:00")
                ).replace(tzinfo=None)
                if oldest_dt < stop_before_dt:
                    print(f"  [*] Oldest item {oldest_dt.date()} < cutoff {stop_before_dt.date()}, stopping.")
                    break
            except (ValueError, AttributeError):
                pass
        next_url = resp.get("paging", {}).get("next")
        if next_url:
            request_url = next_url
            params = {}
        else:
            break

    return None


def collect_instagram_insights(shortcode, post_type, end_date=None):
    """Collect insights for an Instagram post or reel."""
    print("\n" + "=" * 60)
    print("COLLECTING INSTAGRAM INSIGHTS")
    print("=" * 60)
    print(f"\nShortcode: {shortcode} (type: {post_type})")

    metrics = {}
    created_time = None

    # Step 1: Resolve IG Business Account
    print("\n[1/4] Resolving Instagram Business Account...")
    ig_user_id = resolve_instagram_business_account()
    if not ig_user_id:
        print("  [!] No Instagram Business Account linked to this Page.")
        print("  [!] Check that your Page has a connected Instagram Business/Creator account.")
        return metrics, None, None, None

    print(f"  IG User ID: {ig_user_id}")

    ig_token = get_ig_token()

    # Verify IG insights permission (non-blocking — warn but continue)
    print(f"  Checking instagram_manage_insights permission (using {'IG' if IG_ACCESS_TOKEN else 'FB'} token)...")
    perm_check = safe_api_call(
        f"{BASE_URL}/{ig_user_id}/insights",
        {"access_token": ig_token, "metric": "reach", "period": "day"},
        "IG Permission Check"
    )
    if perm_check is None:
        print("  [!] WARNING: Permission check failed — this may indicate missing permissions")
        print("      or a temporary API error. Proceeding with media search anyway...")
        print("      If insights fail below, re-generate your token with:")
        print("      - instagram_basic, instagram_manage_insights, pages_read_engagement, read_insights")

    # Step 2: Find media by shortcode
    print("\n[2/4] Searching for media by shortcode...")
    media = find_ig_media_by_shortcode(ig_user_id, shortcode, hint_date=end_date)

    # Fallback if shortcode search failed
    if not media:
        print(f"  [*] Primary search failed, trying fallback methods...")
        media = resolve_ig_media_via_url(ig_user_id, shortcode, post_type, hint_date=end_date)

    if not media:
        print(f"  [!] Could not find media with shortcode '{shortcode}'.")
        return metrics, None, None, ig_user_id

    ig_media_id = media["id"]
    media_type = media.get("media_type", "UNKNOWN")
    created_time = media.get("timestamp")
    print(f"  Found: {ig_media_id} (type: {media_type})")

    # Step 3: Fetch media fields (like_count, comments_count are object fields, not insights)
    print("\n[3/4] Fetching media object fields...")
    field_data = safe_api_call(
        f"{BASE_URL}/{ig_media_id}",
        {"access_token": ig_token, "fields": "like_count,comments_count,timestamp,media_type,permalink,caption"},
        "IG Media Fields"
    )
    if field_data:
        metrics["Reactions_Total"] = field_data.get("like_count", 0)
        metrics["Comments"] = field_data.get("comments_count", 0)
        if field_data.get("caption"):
            metrics["Caption"] = field_data["caption"][:80]
        print(f"  Likes: {metrics['Reactions_Total']:,}")
        print(f"  Comments: {metrics['Comments']:,}")

    # Step 4: Fetch insights metrics
    # As of April 2025, `plays`, `ig_reels_aggregated_all_plays_count`, `impressions`
    # are DEPRECATED. Use `views` instead.
    # Available metrics by type:
    #   REELS: views, reach, likes, comments, saved, shares, total_interactions,
    #          ig_reels_avg_watch_time, ig_reels_video_view_total_time
    #   FEED:  views, reach, likes, comments, saved, shares, total_interactions,
    #          follows, profile_activity, profile_visits
    # Period is automatically lifetime (cannot be changed).
    print("\n[4/4] Fetching IG insights metrics...")

    if media_type == "VIDEO" or post_type == "ig_reel":
        insight_metrics = "views,crossposted_views,facebook_views,reach,likes,comments,saved,shares,reposts,total_interactions,ig_reels_avg_watch_time,ig_reels_video_view_total_time"
    else:
        insight_metrics = "views,crossposted_views,facebook_views,reach,likes,comments,saved,shares,reposts,total_interactions"

    # Fetch metrics individually to avoid errors from mixing metrics
    # that support breakdowns with those that don't
    metric_list = insight_metrics.split(",")
    for metric_name in metric_list:
        data = safe_api_call(
            f"{BASE_URL}/{ig_media_id}/insights",
            {"access_token": ig_token, "metric": metric_name},
            f"IG Metric: {metric_name}"
        )
        if not data or "data" not in data or len(data["data"]) == 0:
            print(f"  {metric_name}: no data")
            continue

        item = data["data"][0]

        # Parse value: handle both old format (values[]) and new format (total_value)
        val = None
        if "total_value" in item:
            val = item["total_value"].get("value", 0)
        elif "values" in item and len(item["values"]) > 0:
            val = item["values"][0].get("value", 0)

        if val is None:
            print(f"  {metric_name}: could not parse response: {json.dumps(item)[:200]}")
            continue

        print(f"  {metric_name}: {val:,}" if isinstance(val, (int, float)) else f"  {metric_name}: {val}")

        if metric_name == "views":
            metrics["Views_IG_Only"] = val
            # Set Views initially; may be overridden by crossposted_views
            if "Views" not in metrics:
                metrics["Views"] = val
        elif metric_name == "crossposted_views":
            metrics["Crossposted_Views"] = val
            # Use crossposted_views as primary Views (includes IG + FB)
            if val > 0:
                metrics["Views"] = val
        elif metric_name == "facebook_views":
            metrics["Facebook_Views"] = val
        elif metric_name == "reach":
            metrics["Reach"] = val
        elif metric_name == "likes":
            metrics["Reactions_Total"] = val
        elif metric_name == "comments":
            metrics["Comments"] = val
        elif metric_name == "saved":
            metrics["Saves"] = val
        elif metric_name == "shares":
            metrics["Shares"] = val
        elif metric_name == "reposts":
            metrics["Reposts"] = val
        elif metric_name == "total_interactions":
            metrics["Total_Interactions"] = val

    # Defaults
    metrics.setdefault("Views", 0)
    metrics.setdefault("Views_IG_Only", 0)
    metrics.setdefault("Crossposted_Views", 0)
    metrics.setdefault("Facebook_Views", 0)
    metrics.setdefault("Reach", 0)
    metrics.setdefault("Reactions_Total", 0)
    metrics.setdefault("Comments", 0)
    metrics.setdefault("Shares", 0)
    metrics.setdefault("Saves", 0)
    metrics.setdefault("Reposts", 0)
    metrics.setdefault("Link_Clicks", 0)

    # Use total_interactions from API if available, otherwise calculate
    if "Total_Interactions" in metrics:
        metrics["Interactions"] = metrics["Total_Interactions"]
    else:
        metrics["Interactions"] = (
            metrics["Reactions_Total"] + metrics["Comments"] + metrics["Shares"]
        )

    # Log views breakdown
    if metrics["Crossposted_Views"] > 0:
        print(f"\n  Views breakdown:")
        print(f"    IG-only views:       {metrics['Views_IG_Only']:,}")
        print(f"    Facebook views:      {metrics['Facebook_Views']:,}")
        print(f"    Crossposted views:   {metrics['Crossposted_Views']:,} (used as primary)")
    if metrics["Reposts"] > 0:
        print(f"  Reposts: {metrics['Reposts']:,}")

    print(f"\n  Summary: Views={metrics['Views']:,} | Reach={metrics['Reach']:,} | "
          f"Interactions={metrics['Interactions']:,} | Saves={metrics['Saves']:,}")

    return metrics, created_time, ig_media_id, ig_user_id


# =============================================================================
# AD MANAGER INSIGHTS
# =============================================================================

def _parse_ad_insights(ad):
    """Extract stats dict from a single ad object."""
    stats = {
        "campaign_name": ad.get("campaign", {}).get("name", "N/A"),
        "adset_name": ad.get("adset", {}).get("name", "N/A"),
        "adset_start_time": ad.get("adset", {}).get("start_time", ""),
        "spend": 0.0, "currency": "HKD", "impressions": 0, "reach": 0,
        "frequency": 0.0, "link_clicks": 0, "clicks_all": 0, "post_engagement": 0,
        "reactions": 0, "comments": 0, "shares": 0, "saves": 0,
        "thruplays": 0, "video_100": 0
    }
    insights = ad.get("insights", {}).get("data", [{}])[0]
    stats["currency"] = insights.get("account_currency", "HKD")
    stats["date_start"] = insights.get("date_start", "")

    stats["spend"] = float(insights.get("spend", 0))
    stats["impressions"] = int(insights.get("impressions", 0))
    stats["reach"] = int(insights.get("reach", 0))
    stats["frequency"] = float(insights.get("frequency", 0))
    stats["link_clicks"] = int(insights.get("inline_link_clicks", 0))
    stats["clicks_all"] = int(insights.get("clicks", 0))
    stats["post_engagement"] = int(insights.get("inline_post_engagement", 0))

    if "actions" in insights:
        for act in insights["actions"]:
            val = int(act["value"])
            atype = act["action_type"]
            if atype == "post_reaction":
                stats["reactions"] = val
            elif atype == "comment":
                stats["comments"] = val
            elif atype == "post":
                stats["shares"] = val
            elif atype == "post_save":
                stats["saves"] = val
            elif atype == "onsite_conversion.post_save":
                if stats["saves"] == 0:
                    stats["saves"] = val

    if "video_thruplay_watched_actions" in insights:
        stats["thruplays"] = int(insights["video_thruplay_watched_actions"][0].get("value", 0))
    if "video_p100_watched_actions" in insights:
        stats["video_100"] = int(insights["video_p100_watched_actions"][0].get("value", 0))

    return stats


def collect_ad_insights(video_id=None, time_range=None, post_id=None):
    """Collect Ad Manager insights for ads matching the given video_id or post_id.

    Returns a list of stats dicts (one per matching ad), or None if no matches.

    Strategy 1 (fast): Try server-side filtering by effective_object_story_id
                       — single API call, no pagination needed.
    Strategy 2 (fallback): Scan ads page by page with client-side matching.
                           Uses limit=200 and early termination to minimize calls.
    """
    print("\n" + "=" * 60)
    print("COLLECTING AD MANAGER INSIGHTS")
    print("=" * 60)

    if not AD_ACCOUNT_ID:
        print("  [!] FACEBOOK_AD_ACCOUNT_ID not set in .env, skipping ad insights.")
        return None

    if not video_id and not post_id:
        print("  [!] No video_id or post_id provided for ad matching.")
        return None

    print(f"  Matching by: video_id={video_id}, post_id={post_id}")

    # Build insights fields with optional time_range
    if time_range:
        time_range_str = json.dumps(time_range)
        insights_part = (
            f"insights.time_range({time_range_str})"
            "{spend,account_currency,impressions,reach,frequency,clicks,inline_link_clicks,"
            "inline_post_engagement,actions,"
            "video_thruplay_watched_actions,video_p100_watched_actions,date_start}"
        )
    else:
        insights_part = (
            "insights.date_preset(maximum)"
            "{spend,account_currency,impressions,reach,frequency,clicks,inline_link_clicks,"
            "inline_post_engagement,actions,"
            "video_thruplay_watched_actions,video_p100_watched_actions,date_start}"
        )

    fields = f"campaign{{name}},adset{{name,start_time}},creative{{video_id,effective_object_story_id,object_story_id}},{insights_part}"

    # ── Strategy 1: Server-side filtering (1 API call) ──
    # Try filtering by effective_object_story_id or video_id directly
    filter_field = None
    filter_value = None
    if post_id:
        filter_field = "effective_object_story_id"
        filter_value = post_id
    elif video_id:
        filter_field = "creative.video_id"
        filter_value = video_id

    if filter_field:
        print(f"  [Strategy 1] Trying server-side filter: {filter_field}={filter_value}")
        filtering = json.dumps([{"field": filter_field, "operator": "EQUAL", "value": filter_value}])
        time.sleep(0.5)
        try:
            resp = requests.get(
                f"{BASE_URL}/{AD_ACCOUNT_ID}/ads",
                params={"access_token": ACCESS_TOKEN, "limit": 200, "fields": fields, "filtering": filtering},
                timeout=30,
            )
            data = resp.json()
            if "error" not in data:
                filtered_ads = data.get("data", [])
                if filtered_ads:
                    all_matched = []
                    for ad in filtered_ads:
                        stats = _parse_ad_insights(ad)
                        all_matched.append(stats)
                        print(f"    [{len(all_matched)}] Matched (filtered): "
                              f"{stats['campaign_name']} | Spend=${stats['spend']:.2f} | "
                              f"Reach={stats['reach']:,}")
                    print(f"\n  Total matched ads: {len(all_matched)} (server-side filter, 1 API call)")
                    return all_matched
                else:
                    print(f"  [Strategy 1] No results from server-side filter")
            else:
                print(f"  [Strategy 1] Filter not supported: {data['error'].get('message', '')[:80]}")
        except requests.RequestException as e:
            print(f"  [Strategy 1] Request failed: {e}")

    # ── Strategy 2: Paginated scan with client-side matching ──
    print(f"  [Strategy 2] Scanning ads with client-side matching (limit=200)...")
    LIMIT = 200
    request_url = f"{BASE_URL}/{AD_ACCOUNT_ID}/ads"
    params = {"access_token": ACCESS_TOKEN, "limit": LIMIT, "fields": fields}

    all_matched = []
    page_num = 0

    while request_url:
        page_num += 1
        matches_before = len(all_matched)
        time.sleep(0.5)
        try:
            if page_num == 1:
                response = requests.get(request_url, params=params, timeout=30)
            else:
                response = requests.get(request_url, timeout=30)
            data = response.json()
        except requests.RequestException as e:
            print(f"  [!] Request failed: {e}")
            break

        if "error" in data:
            print(f"  [!] Ad API error: {data['error'].get('message', 'Unknown')}")
            break

        page_ads = data.get("data", [])
        print(f"  Page {page_num}: {len(page_ads)} ads returned")

        for ad in page_ads:
            creative = ad.get("creative", {})
            ad_video_id = creative.get("video_id")
            ad_effective_story_id = creative.get("effective_object_story_id")
            ad_story_id = creative.get("object_story_id")

            match_method = ""
            if video_id and ad_video_id == video_id:
                match_method = "video_id"
            elif post_id and ad_effective_story_id == post_id:
                match_method = "effective_object_story_id"
            elif post_id and ad_story_id == post_id:
                match_method = "object_story_id"

            if match_method:
                stats = _parse_ad_insights(ad)
                all_matched.append(stats)
                print(f"    [{len(all_matched)}] Matched via {match_method}: "
                      f"{stats['campaign_name']} | Spend=${stats['spend']:.2f} | "
                      f"Reach={stats['reach']:,}")

        matches_this_page = len(all_matched) - matches_before

        # Early termination: last page if fewer results than limit
        if len(page_ads) < LIMIT:
            print(f"  Last page reached ({len(page_ads)} < {LIMIT})")
            break

        # If we found matches previously but this page had none, stop
        if all_matched and matches_this_page == 0:
            print(f"  No new matches on page {page_num}, stopping search")
            break

        request_url = data.get("paging", {}).get("next")
        if not request_url:
            break

    if all_matched:
        print(f"\n  Total matched ads: {len(all_matched)} (scanned {page_num} page(s))")
    else:
        print(f"  [!] No matching ad found (searched {page_num} page(s)).")
        return None

    return all_matched


def fetch_ig_media_insights(ig_media_id, media_type="ig_post"):
    """Fetch insights from a specific IG media ID (organic or ad-specific).

    This is used to get metrics from ad-specific media when the ads don't
    directly promote the target organic post.

    Args:
        ig_media_id: Instagram media ID
        media_type: "ig_post" or "ig_reel"

    Returns:
        Dict with Views, Reach, Reactions_Total, Shares, etc.
    """
    ig_token = get_ig_token()
    if not ig_token:
        return None

    # First get basic fields
    fields = "like_count,comments_count,media_type,timestamp,permalink"
    basic_data = safe_api_call(
        f"{BASE_URL}/{ig_media_id}",
        {"access_token": ig_token, "fields": fields},
        f"IG Media {ig_media_id} basic"
    )

    if not basic_data:
        return None

    likes = basic_data.get("like_count", 0)
    comments = basic_data.get("comments_count", 0)
    actual_media_type = basic_data.get("media_type", "IMAGE")

    # Determine insights metrics based on media type
    if actual_media_type == "VIDEO" or media_type == "ig_reel":
        metrics = "views,reach,likes,comments,saved,shares,total_interactions"
    else:
        metrics = "views,reach,likes,comments,saved,shares,total_interactions"

    insights_data = safe_api_call(
        f"{BASE_URL}/{ig_media_id}/insights",
        {"access_token": ig_token, "metric": metrics},
        f"IG Media {ig_media_id} insights"
    )

    result = {
        "Views": 0,
        "Reach": 0,
        "Interactions": 0,
        "Reactions_Total": likes,
        "Comments": comments,
        "Shares": 0,
        "Saves": 0,
    }

    if insights_data and "data" in insights_data:
        for metric in insights_data["data"]:
            name = metric.get("name")
            values = metric.get("values", [])
            val = values[0].get("value", 0) if values else 0
            if name == "views":
                result["Views"] = val
            elif name == "reach":
                result["Reach"] = val
            elif name == "likes":
                result["Reactions_Total"] = val
            elif name == "shares":
                result["Shares"] = val
            elif name == "saved":
                result["Saves"] = val
            elif name == "total_interactions":
                result["Interactions"] = val
            elif name == "comments":
                result["Comments"] = val

    return result


def collect_ig_ad_insights(ig_media_id=None, time_range=None):
    """Collect Ad Manager insights for Instagram ads.

    Flow (verified via Graph API Explorer):
    1. {IG_MEDIA_ID}/boost_ads_list → get ad_id list
    2. {ad_id}/insights?fields=... → get ad metrics

    Args:
        ig_media_id: The IG Media ID (e.g., "18175930789370747")
        time_range: Optional dict {"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}

    Returns a list of stats dicts (one per ad), or None.
    """
    print("\n" + "=" * 60)
    print("COLLECTING IG AD MANAGER INSIGHTS")
    print("=" * 60)

    if not ig_media_id:
        print("  [!] No ig_media_id provided, cannot fetch ad insights.")
        return None

    print(f"  IG Media ID: {ig_media_id}")

    # Step 1: Get ad IDs from boost_ads_list
    # Use IG token (same token used to find media by shortcode)
    print(f"\n  [Step 1] Fetching boost_ads_list...")

    ig_token = get_ig_token()
    boost_url = f"{BASE_URL}/{ig_media_id}/boost_ads_list"

    boost_data = safe_api_call(
        boost_url,
        {"access_token": ig_token},
        "boost_ads_list"
    )

    if not boost_data or "data" not in boost_data or not boost_data["data"]:
        print("  [!] No boosted ads found for this media.")
        return None

    ad_entries_raw = boost_data["data"]
    # Deduplicate by ad_id — boost_ads_list sometimes returns the same ad ID twice
    seen_ids = set()
    ad_entries = []
    for entry in ad_entries_raw:
        aid = entry.get("ad_id")
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            ad_entries.append(entry)
    if len(ad_entries) < len(ad_entries_raw):
        print(f"  Found {len(ad_entries_raw)} ad(s) (deduplicated to {len(ad_entries)}):")
    else:
        print(f"  Found {len(ad_entries)} ad(s):")
    for entry in ad_entries:
        print(f"    - ad_id: {entry.get('ad_id')} | status: {entry.get('ad_status', 'unknown')}")

    # Step 2: Verify each ad's creative matches target media
    print(f"\n  [Step 2] Verifying ad creatives match target media...")
    matching_ads = []
    mismatched_ads = []

    for entry in ad_entries:
        ad_id = entry.get("ad_id")
        if not ad_id:
            continue

        time.sleep(0.3)
        # Fetch the ad's creative to check effective_instagram_media_id
        creative_data = safe_api_call(
            f"{BASE_URL}/{ad_id}",
            {
                "access_token": ACCESS_TOKEN,
                "fields": "creative{effective_instagram_media_id,instagram_permalink_url}"
            },
            f"Ad {ad_id} creative"
        )

        if creative_data and "creative" in creative_data:
            creative = creative_data["creative"]
            effective_media_id = creative.get("effective_instagram_media_id")
            ig_permalink = creative.get("instagram_permalink_url", "N/A")

            if effective_media_id == ig_media_id:
                matching_ads.append(entry)
                print(f"    [MATCH] Ad {ad_id}: effective_instagram_media_id={effective_media_id}")
            else:
                mismatched_ads.append({
                    "ad_id": ad_id,
                    "effective_media_id": effective_media_id,
                    "permalink": ig_permalink
                })
                print(f"    [SKIP]  Ad {ad_id}: promotes different media {effective_media_id}")
        else:
            # If we can't get creative info, include it but warn
            matching_ads.append(entry)
            print(f"    [WARN]  Ad {ad_id}: Could not verify creative, including anyway")

    # Collect unique ad-specific media IDs
    ad_specific_media_ids = set()
    if mismatched_ads:
        print(f"\n  [!] {len(mismatched_ads)} ad(s) promote DIFFERENT IG media:")
        for m in mismatched_ads:
            print(f"      - Ad {m['ad_id']}: promotes {m['effective_media_id']}")
            if m['effective_media_id']:
                ad_specific_media_ids.add(m['effective_media_id'])

    # Handle case where no direct matches
    if not matching_ads:
        if ad_specific_media_ids:
            print(f"\n  [*] Organic post was NOT directly boosted.")
            print(f"      But found {len(ad_specific_media_ids)} ad-specific media ID(s).")
            print(f"      Business Suite combines organic + ad-specific metrics.")
        else:
            print(f"\n  [!] No ads found that promote the target organic media.")
            return None
    else:
        print(f"\n  Found {len(matching_ads)} ad(s) that match the target media.")

    # Step 3: Fetch insights for ads (matching or mismatched)
    # If we have mismatched ads (ad-specific media), still fetch their insights
    ads_to_fetch = matching_ads if matching_ads else [{"ad_id": m["ad_id"]} for m in mismatched_ads]
    print(f"\n  [Step 3] Fetching insights for {len(ads_to_fetch)} ad(s)...")
    all_results = []
    insight_fields = (
        "campaign_name,adset_name,spend,account_currency,impressions,reach,frequency,"
        "inline_link_clicks,clicks,inline_post_engagement,actions,"
        "video_thruplay_watched_actions,video_p100_watched_actions,date_start"
    )

    for entry in ads_to_fetch:
        ad_id = entry.get("ad_id")
        ad_status = entry.get("ad_status", "unknown")
        if not ad_id:
            continue

        time.sleep(0.5)
        insight_params = {
            "access_token": ACCESS_TOKEN,
            "fields": insight_fields,
        }
        if time_range:
            insight_params["time_range"] = json.dumps(time_range)
        else:
            insight_params["date_preset"] = "maximum"

        insight_data = safe_api_call(
            f"{BASE_URL}/{ad_id}/insights",
            insight_params,
            f"Ad {ad_id} insights"
        )

        if not insight_data or "data" not in insight_data or not insight_data["data"]:
            print(f"    [{ad_id}] No insights data (status: {ad_status})")
            continue

        row = insight_data["data"][0]

        def get_action_val(action_list, action_type):
            if not action_list:
                return 0
            for item in action_list:
                if item.get("action_type") == action_type:
                    return int(item.get("value", 0))
            return 0

        actions = row.get("actions", [])
        thruplays_list = row.get("video_thruplay_watched_actions", [])
        p100_list = row.get("video_p100_watched_actions", [])

        saves = get_action_val(actions, "post_save")
        if saves == 0:
            saves = get_action_val(actions, "onsite_conversion.post_save")

        campaign_name = row.get("campaign_name", f"Ad {ad_id}")
        adset_name = row.get("adset_name", "N/A")
        currency = row.get("account_currency", "HKD")

        stats = {
            "campaign_name": campaign_name,
            "adset_name": adset_name,
            "date_start": row.get("date_start", ""),
            "spend": float(row.get("spend", 0)),
            "currency": currency,
            "impressions": int(row.get("impressions", 0)),
            "reach": int(row.get("reach", 0)),
            "frequency": float(row.get("frequency", 0)),
            "link_clicks": int(row.get("inline_link_clicks", 0)),
            "clicks_all": int(row.get("clicks", 0)),
            "post_engagement": int(row.get("inline_post_engagement", 0)),
            "reactions": get_action_val(actions, "post_reaction"),
            "comments": get_action_val(actions, "comment"),
            "shares": get_action_val(actions, "post"),
            "saves": saves,
            "thruplays": get_action_val(thruplays_list, "video_view"),
            "video_100": get_action_val(p100_list, "video_view"),
        }

        all_results.append(stats)
        print(f"    [{len(all_results)}] {adset_name} | "
              f"Spend={stats['spend']:.2f} | "
              f"Reach={stats['reach']:,} | Engagement={stats['post_engagement']:,} | "
              f"Reactions={stats['reactions']} | Shares={stats['shares']}")

    if all_results:
        print(f"\n  Total IG ad entries: {len(all_results)}")
        # Return results with metadata about matching status
        return {
            "ad_insights": all_results,
            "ads_match_organic": len(matching_ads) > 0,
            "ad_specific_media_ids": list(ad_specific_media_ids) if ad_specific_media_ids else []
        }
    else:
        print(f"  [!] No IG ad insights data retrieved.")
        return None


# =============================================================================
# MONTHLY MODE: AD END DATE DETECTION
# =============================================================================

def prescan_fb_ad_end_dates():
    """Scan the ad account once and build a mapping of post_id -> latest ad end date.

    Returns: dict {post_id_or_video_id: "YYYY-MM-DD", ...}
    """
    if not AD_ACCOUNT_ID:
        return {}

    print("\n  [Pre-scan] Scanning ad account for end dates...")
    fields = "creative{video_id,effective_object_story_id,object_story_id},adset{end_time}"

    request_url = f"{BASE_URL}/{AD_ACCOUNT_ID}/ads"
    params = {"access_token": ACCESS_TOKEN, "limit": 100, "fields": fields}

    end_date_map = {}  # {identifier: latest_end_datetime}
    page_num = 0

    while request_url:
        page_num += 1
        time.sleep(0.5)
        data = safe_api_call(request_url, params, f"Ad end-date scan page {page_num}")
        if not data or "data" not in data:
            break

        for ad in data["data"]:
            creative = ad.get("creative", {})
            adset = ad.get("adset", {})
            end_time_str = adset.get("end_time")
            if not end_time_str:
                continue

            try:
                end_dt = datetime.fromisoformat(
                    end_time_str.replace("+0000", "+00:00").replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue

            # Map all identifiers to this end date
            identifiers = []
            vid = creative.get("video_id")
            story_id = creative.get("effective_object_story_id")
            obj_story_id = creative.get("object_story_id")
            if vid:
                identifiers.append(vid)
            if story_id:
                identifiers.append(story_id)
            if obj_story_id:
                identifiers.append(obj_story_id)

            for ident in identifiers:
                if ident not in end_date_map or end_dt > end_date_map[ident]:
                    end_date_map[ident] = end_dt

        next_url = data.get("paging", {}).get("next")
        if next_url and data["data"]:
            request_url = next_url
            params = {}
        else:
            break

    # Convert to date strings with +2 days buffer
    result = {}
    for ident, end_dt in end_date_map.items():
        result[ident] = (end_dt + timedelta(days=2)).strftime("%Y-%m-%d")

    print(f"  [Pre-scan] Found end dates for {len(result)} ad identifier(s) across {page_num} page(s)")
    return result


def get_ig_ad_end_date(ig_media_id):
    """Find the latest ad end_time for an IG media via boost_ads_list.
    Returns YYYY-MM-DD string (end_time + 2 days) or None.
    """
    ig_token = get_ig_token()
    boost_data = safe_api_call(
        f"{BASE_URL}/{ig_media_id}/boost_ads_list",
        {"access_token": ig_token},
        "IG boost_ads_list (end_time)"
    )

    if not boost_data or "data" not in boost_data or not boost_data["data"]:
        return None

    latest_end = None
    for entry in boost_data["data"]:
        ad_id = entry.get("ad_id")
        if not ad_id:
            continue
        time.sleep(0.3)
        ad_data = safe_api_call(
            f"{BASE_URL}/{ad_id}",
            {"access_token": ACCESS_TOKEN, "fields": "adset{end_time}"},
            f"Ad {ad_id} end_time"
        )
        if ad_data and "adset" in ad_data:
            end_time_str = ad_data["adset"].get("end_time")
            if end_time_str:
                try:
                    end_dt = datetime.fromisoformat(
                        end_time_str.replace("+0000", "+00:00").replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    if latest_end is None or end_dt > latest_end:
                        latest_end = end_dt
                except (ValueError, AttributeError):
                    pass

    if latest_end:
        return (latest_end + timedelta(days=2)).strftime("%Y-%m-%d")
    return None


# =============================================================================
# ENGAGEMENT VERIFICATION (Phase 1: API Edge Endpoints)
# =============================================================================

def verify_fb_engagement(post_id):
    """Verify Facebook engagement using edge endpoints (live counts).

    Primary (requires App Review "Page Public Content Access"):
      GET /{post_id}/comments?summary=true&filter=stream&limit=0 → live comment count
      GET /{post_id}/reactions?summary=true&limit=0 → live reaction count
      GET /{post_id}/comments?filter=stream&fields=id,hidden&limit=100 → hidden comments

    Fallback (works without App Review):
      GET /{post_id}?fields=shares → live share count

    Returns dict with live counts and deltas, or None on failure.
    """
    # Try both tokens (IG token may have broader permissions)
    tokens_to_try = []
    if IG_ACCESS_TOKEN:
        tokens_to_try.append(("IG", IG_ACCESS_TOKEN))
    tokens_to_try.append(("FB", ACCESS_TOKEN))

    result = {
        "live_comments": None,
        "live_reactions": None,
        "live_shares": None,
        "hidden_comments": 0,
    }

    edge_success = False
    for token_label, token in tokens_to_try:
        # Live comment count via summary
        data = safe_api_call(
            f"{BASE_URL}/{post_id}/comments",
            {
                "access_token": token,
                "summary": "true",
                "filter": "stream",
                "limit": 0,
            },
            f"FB Comments Edge ({token_label} token)"
        )
        if data and "summary" in data:
            result["live_comments"] = data["summary"].get("total_count")
            print(f"    Live comments (stream): {result['live_comments']}")
            edge_success = True

            # Also try toplevel filter for comparison
            data_top = safe_api_call(
                f"{BASE_URL}/{post_id}/comments",
                {
                    "access_token": token,
                    "summary": "true",
                    "filter": "toplevel",
                    "limit": 0,
                },
                f"FB Comments Edge toplevel ({token_label} token)"
            )
            if data_top and "summary" in data_top:
                toplevel_count = data_top["summary"].get("total_count")
                print(f"    Live comments (toplevel): {toplevel_count}")

            # Live reaction count
            data = safe_api_call(
                f"{BASE_URL}/{post_id}/reactions",
                {
                    "access_token": token,
                    "summary": "true",
                    "limit": 0,
                },
                f"FB Reactions Edge ({token_label} token)"
            )
            if data and "summary" in data:
                result["live_reactions"] = data["summary"].get("total_count")
                print(f"    Live reactions: {result['live_reactions']}")

            # Count hidden comments (fetch up to 100 with hidden field)
            data = safe_api_call(
                f"{BASE_URL}/{post_id}/comments",
                {
                    "access_token": token,
                    "filter": "stream",
                    "fields": "id,hidden",
                    "limit": 100,
                },
                f"FB Hidden Comments ({token_label} token)"
            )
            if data and "data" in data:
                hidden_count = sum(1 for c in data["data"] if c.get("hidden", False))
                result["hidden_comments"] = hidden_count
                if hidden_count > 0:
                    print(f"    Hidden comments: {hidden_count}")

            break  # Success with this token, no need to try next

        # If first token failed, try next
        if not edge_success and token_label == tokens_to_try[-1][0]:
            print(f"    [!] Comments/Reactions edges blocked (needs 'Page Public Content Access' App Review)")

    # Fallback: shares field works without App Review (despite being "deprecated")
    data = safe_api_call(
        f"{BASE_URL}/{post_id}",
        {"access_token": ACCESS_TOKEN, "fields": "shares"},
        "FB Post shares field"
    )
    if data and "shares" in data:
        result["live_shares"] = data["shares"].get("count", 0)
        print(f"    Live shares: {result['live_shares']}")

    return result


def verify_ig_engagement(ig_media_id):
    """Verify Instagram engagement using media object fields (live counts).

    Uses:
      GET /{ig_media_id}?fields=like_count,comments_count → live counts
      GET /{ig_media_id}/comments?fields=id,text,timestamp,hidden → individual comments

    Returns dict with live counts, or None on failure.
    """
    ig_token = get_ig_token()
    result = {
        "live_comments": None,
        "live_reactions": None,
        "hidden_comments": 0,
    }

    # Live counts from media object
    data = safe_api_call(
        f"{BASE_URL}/{ig_media_id}",
        {
            "access_token": ig_token,
            "fields": "like_count,comments_count",
        },
        "IG Media Fields (live counts)"
    )
    if data:
        result["live_reactions"] = data.get("like_count")
        result["live_comments"] = data.get("comments_count")
        print(f"    Live likes: {result['live_reactions']}")
        print(f"    Live comments: {result['live_comments']}")

    # Try to get individual comments with hidden field
    data = safe_api_call(
        f"{BASE_URL}/{ig_media_id}/comments",
        {
            "access_token": ig_token,
            "fields": "id,timestamp,hidden",
            "limit": 100,
        },
        "IG Comments Edge (hidden check)"
    )
    if data and "data" in data:
        hidden_count = sum(1 for c in data["data"] if c.get("hidden", False))
        result["hidden_comments"] = hidden_count
        if hidden_count > 0:
            print(f"    Hidden comments: {hidden_count}")
    elif data is None:
        print(f"    [!] IG comments edge failed (may need instagram_manage_comments permission)")

    return result


def verify_engagement(result):
    """Run engagement verification for a processed post result.

    Args:
        result: dict from process_single_url() with keys:
            platform, post_metrics, url, and internal IDs

    Returns:
        dict with verification data to add to result, or empty dict.
    """
    platform = result.get("platform", "")
    post_metrics = result.get("post_metrics", {})
    verification = {}

    print(f"\n  [Verify] Checking live engagement counts...")

    if platform == "Facebook":
        post_id = result.get("_post_id")
        if not post_id:
            print(f"    [!] No post_id available for verification")
            return verification

        fb_verify = verify_fb_engagement(post_id)
        if fb_verify:
            verification["Live_Comments"] = fb_verify["live_comments"]
            verification["Live_Reactions"] = fb_verify["live_reactions"]
            verification["Live_Shares"] = fb_verify.get("live_shares")
            verification["Hidden_Comments"] = fb_verify["hidden_comments"]

            # Calculate deltas
            if fb_verify["live_comments"] is not None:
                insights_comments = post_metrics.get("Comments", 0)
                verification["Delta_Comments"] = fb_verify["live_comments"] - insights_comments
            if fb_verify["live_reactions"] is not None:
                insights_reactions = post_metrics.get("Reactions_Total", 0)
                verification["Delta_Reactions"] = fb_verify["live_reactions"] - insights_reactions
            if fb_verify.get("live_shares") is not None:
                insights_shares = post_metrics.get("Shares", 0)
                verification["Delta_Shares"] = fb_verify["live_shares"] - insights_shares

    elif platform == "Instagram":
        ig_media_id = result.get("_ig_media_id")
        if not ig_media_id:
            print(f"    [!] No ig_media_id available for verification")
            return verification

        ig_verify = verify_ig_engagement(ig_media_id)
        if ig_verify:
            verification["Live_Comments"] = ig_verify["live_comments"]
            verification["Live_Reactions"] = ig_verify["live_reactions"]
            verification["Hidden_Comments"] = ig_verify["hidden_comments"]

            if ig_verify["live_comments"] is not None:
                insights_comments = post_metrics.get("Comments", 0)
                verification["Delta_Comments"] = ig_verify["live_comments"] - insights_comments
            if ig_verify["live_reactions"] is not None:
                insights_reactions = post_metrics.get("Reactions_Total", 0)
                verification["Delta_Reactions"] = ig_verify["live_reactions"] - insights_reactions

    # Print summary
    if verification:
        dc = verification.get("Delta_Comments")
        dr = verification.get("Delta_Reactions")
        ds = verification.get("Delta_Shares")
        hc = verification.get("Hidden_Comments", 0)
        print(f"    Delta Comments: {dc:+d}" if dc is not None else "    Delta Comments: N/A")
        print(f"    Delta Reactions: {dr:+d}" if dr is not None else "    Delta Reactions: N/A")
        print(f"    Delta Shares: {ds:+d}" if ds is not None else "    Delta Shares: N/A")
        if hc > 0:
            print(f"    Hidden Comments: {hc}")

    return verification


# =============================================================================
# CSV EXPORT
# =============================================================================

def export_combined_csv(results, filename="combined_insights.csv", include_verify=False):
    """
    Export combined CSV with layout per entry:
      Row 1 (A1): Post Insight headers
      Row 2 (A2): Post Insight values (one row per URL)
      Row 3-5: empty
      Row 6 (A6): Ad Manager headers
      Row 7+ (A7): Ad Manager values (one row per URL)

    results: list of dicts with keys: post_metrics, ad_metrics, url, date_range_str
    include_verify: if True, add verification columns (Live_Comments, Live_Reactions, etc.)
    """
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Row 1: Post Insight headers
        post_headers = [
            "Platform", "Post Link", "Date Range", "Views", "Reach",
            "Interactions", "Likes and reactions", "Comments", "Shares",
            "Saves", "Link clicks"
        ]
        if include_verify:
            post_headers += [
                "", "Live Comments", "Live Reactions", "Live Shares",
                "Delta Comments", "Delta Reactions", "Delta Shares",
                "Hidden Comments"
            ]
        writer.writerow(post_headers)

        # Row 2+: Post Insight values (one row per URL)
        for r in results:
            pm = r["post_metrics"]
            post_values = [
                r.get("platform", "Facebook"),
                r["url"],
                r["date_range_str"],
                pm.get("Views", 0),
                pm.get("Reach", 0),
                pm.get("Interactions", 0),
                pm.get("Reactions_Total", 0),
                pm.get("Comments", 0),
                pm.get("Shares", 0),
                pm.get("Saves", 0),  # Available for IG; FB organic returns 0
                pm.get("Link_Clicks", 0),
            ]
            if include_verify:
                v = r.get("verification", {})
                post_values += [
                    "",  # spacer
                    v.get("Live_Comments", "N/A"),
                    v.get("Live_Reactions", "N/A"),
                    v.get("Live_Shares", "N/A"),
                    v.get("Delta_Comments", "N/A"),
                    v.get("Delta_Reactions", "N/A"),
                    v.get("Delta_Shares", "N/A"),
                    v.get("Hidden_Comments", 0),
                ]
            writer.writerow(post_values)

        # Rows: empty separator
        writer.writerow([])
        writer.writerow([])
        writer.writerow([])

        # Ad Manager headers
        ad_headers = [
            "Campaign Name", "Ad Set Name", "Date Range", "Amount spent",
            "Impression", "Reach", "Frequency", "Link Clicks", "Click(All)",
            "Post engagement", "Post reactions", "Post comments", "Post shares",
            "Post saves", "ThruPlays", "Video plays at 100%"
        ]
        writer.writerow(ad_headers)

        # Ad Manager values (multiple rows per URL if multiple ads matched)
        for r in results:
            ad_list = r["ad_metrics"]
            if ad_list:
                for am in ad_list:
                    ad_values = [
                        am["campaign_name"],
                        am.get("adset_name", "N/A"),
                        r["date_range_str"],
                        f"{am['spend']:.2f}",
                        am["impressions"],
                        am["reach"],
                        f"{am['frequency']:.2f}",
                        am["link_clicks"],
                        am["clicks_all"],
                        am["post_engagement"],
                        am["reactions"],
                        am["comments"],
                        am["shares"],
                        am["saves"],
                        am["thruplays"],
                        am["video_100"],
                    ]
                    writer.writerow(ad_values)
            else:
                ad_values = [f"No ad data ({r['url'][:50]}...)"] + ["N/A", r["date_range_str"]] + [""] * 13
                writer.writerow(ad_values)

    print(f"\nCSV exported: {filename}")


def export_per_post_csv(results, filename="monthly_insights.csv", include_verify=False):
    """Export CSV with per-post blocks. Each post is self-contained with
    repeated headers for easy manual matching.

    Layout per post:
      Post Insight Headers
      Post data row
      (1 blank row)
      Ad Manager Headers
      Ad data row(s)
      (2 blank rows separator)
    """
    post_headers = [
        "Platform", "Post Link", "Date Range", "Views", "Reach",
        "Interactions", "Likes and reactions", "Comments", "Shares",
        "Saves", "Link clicks"
    ]
    if include_verify:
        post_headers += [
            "", "Live Comments", "Live Reactions", "Delta Comments",
            "Delta Reactions", "Hidden Comments"
        ]
    ad_headers = [
        "Campaign Name", "Ad Set Name", "Date Range", "Amount spent",
        "Impression", "Reach", "Frequency", "Link Clicks", "Click(All)",
        "Post engagement", "Post reactions", "Post comments", "Post shares",
        "Post saves", "ThruPlays", "Video plays at 100%"
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        for i, r in enumerate(results):
            pm = r["post_metrics"]

            # Post Insight Headers
            writer.writerow(post_headers)

            # Post Insight data
            row_data = [
                r.get("platform", "Facebook"),
                r["url"],
                r["date_range_str"],
                pm.get("Views", 0),
                pm.get("Reach", 0),
                pm.get("Interactions", 0),
                pm.get("Reactions_Total", 0),
                pm.get("Comments", 0),
                pm.get("Shares", 0),
                pm.get("Saves", 0),
                pm.get("Link_Clicks", 0),
            ]
            if include_verify:
                v = r.get("verification", {})
                row_data += [
                    "",
                    v.get("Live_Comments", "N/A"),
                    v.get("Live_Reactions", "N/A"),
                    v.get("Delta_Comments", "N/A"),
                    v.get("Delta_Reactions", "N/A"),
                    v.get("Hidden_Comments", 0),
                ]
            writer.writerow(row_data)

            # 1 blank row
            writer.writerow([])

            # Ad Manager Headers
            writer.writerow(ad_headers)

            # Ad Manager data rows
            ad_list = r.get("ad_metrics")
            if ad_list:
                for am in ad_list:
                    writer.writerow([
                        am["campaign_name"],
                        am.get("adset_name", "N/A"),
                        r["date_range_str"],
                        f"{am['spend']:.2f}",
                        am["impressions"],
                        am["reach"],
                        f"{am['frequency']:.2f}",
                        am["link_clicks"],
                        am["clicks_all"],
                        am["post_engagement"],
                        am["reactions"],
                        am["comments"],
                        am["shares"],
                        am["saves"],
                        am["thruplays"],
                        am["video_100"],
                    ])
            else:
                writer.writerow(["No ad data"] + [""] * 15)

            # 2 blank rows separator (unless last post)
            if i < len(results) - 1:
                writer.writerow([])
                writer.writerow([])

    print(f"\nPer-post CSV exported: {filename}")


# =============================================================================
# REPORT
# =============================================================================

def print_report(post_metrics, ad_metrics):
    """Print a summary report to console."""
    print("\n" + "=" * 55)
    print("POST INSIGHTS (Business Suite Aligned)")
    print("=" * 55)
    for key, label in [
        ("Views", "Views"), ("Reach", "Reach"), ("Interactions", "Interactions"),
        ("Reactions_Total", "Likes and reactions"), ("Comments", "Comments"),
        ("Shares", "Shares"), ("Link_Clicks", "Link Clicks"),
    ]:
        if key in post_metrics:
            val = post_metrics[key]
            if isinstance(val, float):
                print(f"  {label:<30} {val:>12}")
            else:
                print(f"  {label:<30} {val:>12,}")

    if ad_metrics:
        print("\n" + "=" * 55)
        print(f"AD MANAGER INSIGHTS ({len(ad_metrics)} ad(s))")
        print("=" * 55)
        for i, am in enumerate(ad_metrics, 1):
            print(f"\n  --- Ad {i} ---")
            print(f"  {'Campaign':<30} {am['campaign_name']}")
            print(f"  {'Spend':<30} ${am['spend']:.2f}")
            print(f"  {'Impressions':<30} {am['impressions']:>12,}")
            print(f"  {'Reach':<30} {am['reach']:>12,}")
            print(f"  {'Link Clicks':<30} {am['link_clicks']:>12,}")
            print(f"  {'ThruPlays':<30} {am['thruplays']:>12,}")

    print("=" * 55)


# =============================================================================
# MAIN
# =============================================================================

def test_connection():
    """Quick API connectivity test."""
    print("\n[Testing API Connection]")
    data = safe_api_call(
        f"{BASE_URL}/{PAGE_ID}",
        {"access_token": ACCESS_TOKEN, "fields": "id,name"},
        "Page"
    )
    if data:
        print(f"  Page: {data.get('name')}")
        print("  Status: OK")
    else:
        print("  Status: FAILED")


def parse_input_file(filepath):
    """
    Parse input text file. Each non-empty, non-comment line contains:
        <url> <end_date>
    e.g.:
        https://www.facebook.com/page/videos/123456 2025-06-30
    """
    entries = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                print(f"  [!] Line {line_num}: Expected '<url> <end_date>', got: {line}")
                continue
            url = parts[0]
            end_date = parts[1]
            # Validate date format
            try:
                datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                print(f"  [!] Line {line_num}: Invalid date '{end_date}', expected YYYY-MM-DD. Skipping.")
                continue
            entries.append({"url": url, "end_date": end_date})
    return entries


def process_single_url(url, end_date):
    """Process a single URL and return results dict."""
    post_type = detect_post_type(url)
    if post_type == "unknown":
        print(f"\n  [!] Skipping unknown post type: {url}")
        return None

    print(f"\nDetected post type from URL: {post_type}")

    content_id = extract_id_from_url(url, post_type)
    if not content_id:
        print(f"  [!] Could not extract content ID from: {url}")
        return None

    # Instagram pipeline
    if post_type in ("ig_reel", "ig_post"):
        post_metrics, created_time, ig_media_id, ig_user_id = collect_instagram_insights(content_id, post_type, end_date=end_date)

        start_date = None
        if created_time:
            try:
                start_date = datetime.fromisoformat(created_time.replace("+0000", "+00:00").replace("Z", "+00:00")).strftime("%Y-%m-%d")
            except (ValueError, AttributeError):
                start_date = created_time[:10] if len(created_time) >= 10 else None

        date_range_str = f"{start_date or 'N/A'} to {end_date}"
        print(f"\nDate range: {date_range_str}")

        # Collect IG ad insights via {IG_MEDIA_ID}/boost_ads_list -> {ad_id}/insights
        ig_ad_result = None
        ig_ad_metrics = None
        ad_specific_media_ids = []
        ads_match_organic = True

        if ig_media_id:
            time_range = None
            if start_date and end_date:
                time_range = {"since": start_date, "until": end_date}
            ig_ad_result = collect_ig_ad_insights(
                ig_media_id=ig_media_id,
                time_range=time_range,
            )

        # Extract ad insights and metadata from result
        if ig_ad_result:
            ig_ad_metrics = ig_ad_result.get("ad_insights", [])
            ads_match_organic = ig_ad_result.get("ads_match_organic", True)
            ad_specific_media_ids = ig_ad_result.get("ad_specific_media_ids", [])

        # If ads promote different media, fetch insights from ad-specific media
        # This aligns with Business Suite which combines organic + ad-specific metrics
        ad_media_metrics = None
        if ad_specific_media_ids and not ads_match_organic:
            print(f"\n  [Step 4] Fetching insights from ad-specific media...")
            for ad_media_id in ad_specific_media_ids:
                print(f"    Fetching insights for ad-specific media: {ad_media_id}")
                ad_media_metrics = fetch_ig_media_insights(ad_media_id, post_type)
                if ad_media_metrics:
                    print(f"      Views: {ad_media_metrics.get('Views', 0):,}")
                    print(f"      Reach: {ad_media_metrics.get('Reach', 0):,}")
                    print(f"      Likes: {ad_media_metrics.get('Reactions_Total', 0):,}")
                    print(f"      Shares: {ad_media_metrics.get('Shares', 0):,}")
                break  # Usually there's one ad-specific media

        # Combine organic + paid metrics for Instagram
        # Key insight: IG Media Insights API returns COMBINED (organic + paid) when
        # ads directly promote the organic post (ads_match_organic=True).
        # Only add ad metrics when ads promote DIFFERENT media (ads_match_organic=False).
        if post_metrics:
            if ads_match_organic and ig_ad_metrics:
                # IG insights already includes paid metrics - DO NOT add ad metrics
                # Business Suite reads the same combined number from IG insights API
                print(f"\n  [*] Ads directly promote this organic media.")
                print(f"      IG insights already includes paid metrics - using as-is.")
                print(f"      Views={post_metrics.get('Views', 0):,} | "
                      f"Reach={post_metrics.get('Reach', 0):,}")

            elif not ads_match_organic and ig_ad_metrics:
                # Ads promoted DIFFERENT media - add Ad Manager metrics
                organic_views = post_metrics.get("Views", 0)
                organic_reach = post_metrics.get("Reach", 0)
                organic_likes = post_metrics.get("Reactions_Total", 0)
                organic_shares = post_metrics.get("Shares", 0)

                total_ad_impressions = sum(ad.get("impressions", 0) for ad in ig_ad_metrics)
                total_ad_reach = sum(ad.get("reach", 0) for ad in ig_ad_metrics)
                total_ad_reactions = sum(ad.get("reactions", 0) for ad in ig_ad_metrics)
                total_ad_shares = sum(ad.get("shares", 0) for ad in ig_ad_metrics)

                # Get likes from ad-specific media if available (even if views=0)
                if ad_media_metrics:
                    ad_likes_from_media = ad_media_metrics.get("Reactions_Total", 0)
                    if ad_likes_from_media > total_ad_reactions:
                        total_ad_reactions = ad_likes_from_media

                combined_views = organic_views + total_ad_impressions
                combined_reach = organic_reach + total_ad_reach
                combined_likes = organic_likes + total_ad_reactions
                combined_shares = organic_shares + total_ad_shares

                print(f"\n  [Combined Metrics: Organic + Ad Manager]")
                print(f"    Views:  Organic {organic_views:,} + Ad Impressions {total_ad_impressions:,} = {combined_views:,}")
                print(f"    Reach:  Organic {organic_reach:,} + Ad Reach {total_ad_reach:,} = {combined_reach:,}")
                print(f"    Likes:  Organic {organic_likes:,} + Ad Reactions {total_ad_reactions:,} = {combined_likes:,}")
                print(f"    Shares: Organic {organic_shares:,} + Ad Shares {total_ad_shares:,} = {combined_shares:,}")
                print(f"    (Note: Reach is summed - Business Suite de-duplicates)")

                # Update post_metrics with combined values
                post_metrics["Views"] = combined_views
                post_metrics["Reach"] = combined_reach
                post_metrics["Reactions_Total"] = combined_likes
                post_metrics["Shares"] = combined_shares

        print_report(post_metrics, ig_ad_metrics)

        return {
            "url": url,
            "date_range_str": date_range_str,
            "post_metrics": post_metrics,
            "ad_metrics": ig_ad_metrics,
            "platform": "Instagram",
            "_ig_media_id": ig_media_id,
        }

    # Facebook pipeline
    # For /posts/ URLs, query API to check if it's actually a video
    video_id = None
    if post_type == "post":
        resolved_type, video_id = resolve_post_type_via_api(content_id)
        if resolved_type == "video" and video_id:
            post_type = "video"
            content_id = video_id
            print(f"  Rerouting to video pipeline (video_id: {video_id})")

    # Collect post insights based on type
    if post_type in ("video", "reel"):
        post_metrics, created_time, post_id = collect_video_insights(content_id, post_type)
    else:
        post_metrics, created_time, post_id = collect_photo_post_insights(content_id, post_type)

    # Determine start date from created_time
    start_date = None
    if created_time:
        try:
            start_date = datetime.fromisoformat(created_time.replace("+0000", "+00:00")).strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            start_date = created_time[:10] if len(created_time) >= 10 else None

    date_range_str = f"{start_date or 'N/A'} to {end_date}"
    print(f"\nDate range: {date_range_str}")

    # Build time_range for Ad Manager
    time_range = None
    if start_date and end_date:
        time_range = {"since": start_date, "until": end_date}

    # Collect ad insights - skip full scan if no paid activity detected
    ad_metrics = None
    has_paid = post_metrics.get("_has_paid_activity", True)  # default True to be safe
    if AD_ACCOUNT_ID and has_paid:
        ad_video_id = content_id if post_type in ("video", "reel") else None
        ad_metrics = collect_ad_insights(
            video_id=ad_video_id,
            time_range=time_range,
            post_id=post_id,
        )
    elif AD_ACCOUNT_ID and not has_paid:
        print(f"\n  [SKIP] No paid activity detected — skipping ad account scan")
        print(f"         (This saves scanning {AD_ACCOUNT_ID} page by page)")

    print_report(post_metrics, ad_metrics)

    return {
        "url": url,
        "date_range_str": date_range_str,
        "post_metrics": post_metrics,
        "ad_metrics": ad_metrics,
        "platform": "Facebook",
        "_post_id": post_id,
    }


def run_monthly_mode(year_month, output_file=None, verify=False):
    """Orchestrator for monthly mode. Discovers all FB + IG posts from the
    given month, determines end dates via ad end_time, processes each post,
    and exports per-post-block CSV."""

    # Parse year_month
    try:
        parts = year_month.split("-")
        year = int(parts[0])
        month = int(parts[1])
        if month < 1 or month > 12:
            raise ValueError
    except (ValueError, IndexError):
        print(f"Error: Invalid month format '{year_month}'. Use YYYY-MM (e.g. 2025-12)")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"MONTHLY MODE: {year}-{month:02d}")
    print(f"{'=' * 60}")

    # Calculate fallback end date (end of month + 2 days)
    if month == 12:
        fallback_end = datetime(year + 1, 1, 1) + timedelta(days=2)
    else:
        fallback_end = datetime(year, month + 1, 1) + timedelta(days=2)
    fallback_end_str = fallback_end.strftime("%Y-%m-%d")

    # Step 1: Discover FB posts
    print(f"\n[Step 1] Discovering Facebook posts for {year}-{month:02d}...")
    fb_posts = discover_fb_posts_for_month(year, month)
    print(f"  Found {len(fb_posts)} Facebook post(s)")

    # Step 2: Discover IG posts
    print(f"\n[Step 2] Discovering Instagram posts for {year}-{month:02d}...")
    ig_posts = discover_ig_posts_for_month(year, month)
    print(f"  Found {len(ig_posts)} Instagram post(s)")

    # Step 3: Pre-scan FB ad account for end dates (once for all posts)
    print(f"\n[Step 3] Pre-scanning ad account for end dates...")
    fb_end_date_map = prescan_fb_ad_end_dates()

    # Step 4: Build work items with URLs and end dates
    print(f"\n[Step 4] Building work items with end dates...")
    work_items = []

    for fb_post in fb_posts:
        post_id = fb_post["id"]
        url = construct_fb_post_url(post_id, fb_post.get("permalink_url"))

        # Look up end date from pre-scanned map
        end_date = None
        # Try composite post_id
        if post_id in fb_end_date_map:
            end_date = fb_end_date_map[post_id]
        else:
            # Try raw post_id (without page prefix)
            raw_id = post_id.split("_")[1] if "_" in post_id else post_id
            for key, val in fb_end_date_map.items():
                if raw_id in key:
                    end_date = val
                    break
        # Also check permalink for video_id
        if not end_date:
            permalink = fb_post.get("permalink_url", "")
            vid_match = re.search(r'/videos/(\d+)', permalink) or re.search(r'/reel/(\d+)', permalink)
            if vid_match:
                vid = vid_match.group(1)
                if vid in fb_end_date_map:
                    end_date = fb_end_date_map[vid]

        end_date = end_date or fallback_end_str
        work_items.append({"url": url, "end_date": end_date})
        print(f"  FB: {url[:70]}... -> end={end_date}")

    for ig_post in ig_posts:
        shortcode = ig_post["shortcode"]
        media_type = ig_post.get("media_type", "IMAGE")
        url = construct_ig_post_url(shortcode, media_type)
        ig_media_id = ig_post["id"]

        # Get IG ad end date
        end_date = get_ig_ad_end_date(ig_media_id)
        end_date = end_date or fallback_end_str
        work_items.append({"url": url, "end_date": end_date})
        print(f"  IG: {url[:70]}... -> end={end_date}")

    total = len(work_items)
    if total == 0:
        print("\nNo posts found for this month.")
        return

    # Step 5: Process each post
    print(f"\n[Step 5] Processing {total} post(s)...")
    results = []
    for i, item in enumerate(work_items, 1):
        print(f"\n{'#' * 60}")
        print(f"# PROCESSING POST {i}/{total}")
        print(f"# {item['url']}")
        print(f"# End date: {item['end_date']}")
        print(f"{'#' * 60}")

        result = process_single_url(item["url"], item["end_date"])
        if result:
            if verify:
                result["verification"] = verify_engagement(result)
            results.append(result)

    # Step 6: Export per-post CSV
    if results:
        output = output_file or f"monthly_insights_{year}_{month:02d}.csv"
        export_per_post_csv(results, output, include_verify=verify)
        print(f"\nDone. Processed {len(results)}/{total} posts for {year}-{month:02d}.")
    else:
        print("\nNo results to export.")


def main():
    script_start = time.time()

    if not ACCESS_TOKEN or not PAGE_ID:
        print("Error: Missing FACEBOOK_ACCESS_TOKEN or FACEBOOK_PAGE_ID in .env")
        sys.exit(1)

    # Show token status
    print("Token status:")
    print(f"  FACEBOOK_ACCESS_TOKEN: {'set' if ACCESS_TOKEN else 'MISSING'}")
    print(f"  IG_ACCESS_TOKEN:       {'set' if IG_ACCESS_TOKEN else 'not set (will use FB token for IG)'}")
    print(f"  AD_ACCOUNT_ID:         {AD_ACCOUNT_ID or 'not set'}")
    print()

    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description="Meta Graph API Insights - Organic + Paid report"
    )
    parser.add_argument("-f", "--file", default="urls.txt",
                        help="Input URL file (default: urls.txt)")
    parser.add_argument("--month", metavar="YYYY-MM",
                        help="Monthly mode: auto-discover all posts from given month")
    parser.add_argument("-o", "--output",
                        help="Output CSV filename")
    parser.add_argument("--test", action="store_true",
                        help="Test API connection")
    parser.add_argument("--verify", action="store_true",
                        help="Verify engagement via live API edge counts (adds verification columns to CSV)")
    args = parser.parse_args()

    if args.test:
        test_connection()
        elapsed = time.time() - script_start
        minutes, seconds = divmod(elapsed, 60)
        print(f"\nTotal time: {int(minutes)}m {seconds:.1f}s")
        return

    if args.month:
        # Monthly mode
        run_monthly_mode(args.month, args.output, verify=args.verify)
    else:
        # URL mode (existing behavior)
        input_file = args.file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        input_path = os.path.join(script_dir, input_file) if not os.path.isabs(input_file) else input_file

        if not os.path.exists(input_path):
            print(f"Error: Input file not found: {input_path}")
            print(f"Create a '{input_file}' file with one URL and end date per line:")
            print(f"  https://www.facebook.com/page/videos/123456 2025-06-30")
            sys.exit(1)

        entries = parse_input_file(input_path)
        if not entries:
            print("No valid entries found in input file.")
            sys.exit(1)

        print(f"Found {len(entries)} URL(s) in {input_file}")
        print("=" * 60)

        results = []
        for i, entry in enumerate(entries, 1):
            print(f"\n{'#' * 60}")
            print(f"# PROCESSING URL {i}/{len(entries)}")
            print(f"# {entry['url']}")
            print(f"# End date: {entry['end_date']}")
            print("#" * 60)

            result = process_single_url(entry["url"], entry["end_date"])
            if result:
                if args.verify:
                    result["verification"] = verify_engagement(result)
                results.append(result)

        if results:
            output = args.output or "combined_insights.csv"
            export_combined_csv(results, output, include_verify=args.verify)
            print(f"\nDone. Processed {len(results)}/{len(entries)} URLs successfully.")
        else:
            print("\nNo results to export.")

    elapsed = time.time() - script_start
    minutes, seconds = divmod(elapsed, 60)
    print(f"\nTotal time: {int(minutes)}m {seconds:.1f}s")


if __name__ == "__main__":
    main()
