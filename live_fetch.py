#!/usr/bin/env python3
"""
Live Engagement Count Fetcher
==============================
Fetches live engagement counts from Facebook and Instagram post pages
using plain HTTP requests (no browser/Playwright needed).

Instagram: Finds data-sjs block containing shortcode, locates media node
           by code/shortcode match, extracts like_count/comment_count.
           (Proven approach from version1.py)
Facebook:  Filters blocks by engagement keys (i18n_reaction_count),
           brute-force recursive search for counts.

"""

import re
import json
import time
import requests

# version1.py headers (proven working for IG)
IG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# FB headers (Referer needed to avoid bot detection)
FB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.facebook.com/",
}

# Circuit breaker state
_consecutive_errors = 0
_paused = False


def is_paused():
    return _paused


def reset_circuit_breaker():
    global _consecutive_errors, _paused
    _consecutive_errors = 0
    _paused = False


def _record_success():
    global _consecutive_errors
    _consecutive_errors = 0


def _record_error():
    global _consecutive_errors, _paused
    _consecutive_errors += 1
    if _consecutive_errors >= 3:
        _paused = True


def _extract_id(url):
    """Extract post/reel/video ID or shortcode from URL."""
    m = re.search(r'/(?:p|reels?|videos|posts)/([^/?#&]+)', url)
    return m.group(1) if m else None


# =========================================================================
# INSTAGRAM: version1.py approach — data-sjs + shortcode-anchored media node
# =========================================================================

def _find_media_node(obj, target_shortcode):
    """
    Recursively search for a media dict where code/shortcode matches target.
    Only returns nodes that have engagement fields (like_count etc).
    Also checks nested 'media' dicts (common in Relay results).
    """
    if isinstance(obj, dict):
        # Check if this dict IS the media node
        if obj.get("code") == target_shortcode or obj.get("shortcode") == target_shortcode:
            if any(k in obj for k in ["like_count", "edge_media_preview_like", "comment_count"]):
                return obj

        # Check nested 'media' key
        if "media" in obj and isinstance(obj["media"], dict):
            m = obj["media"]
            if m.get("code") == target_shortcode or m.get("shortcode") == target_shortcode:
                return m

        # Recurse
        for v in obj.values():
            found = _find_media_node(v, target_shortcode)
            if found:
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = _find_media_node(item, target_shortcode)
            if found:
                return found

    return None


def _fetch_ig(url, shortcode):
    """
    Fetch IG engagement using version1.py's proven approach:
    1. Find data-sjs script blocks containing the shortcode
    2. Locate media node by code == shortcode
    3. Extract like_count and comment_count from that node
    """
    try:
        resp = requests.get(url, headers=IG_HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        _record_error()
        print(f"  [live_fetch] IG request error: {e}")
        return {"_error": str(e)}

    _record_success()
    html = resp.text

    # Strategy 1: data-sjs blocks (primary — matches version1.py)
    blocks = re.findall(r'<script[^>]*data-sjs[^>]*>([\s\S]*?)</script>', html)
    if not blocks:
        # Fallback: standard JSON scripts
        blocks = re.findall(r'<script type="application/json">([\s\S]*?)</script>', html)

    for block in blocks:
        if shortcode not in block:
            continue

        try:
            data = json.loads(block)
        except (json.JSONDecodeError, TypeError):
            continue

        node = _find_media_node(data, shortcode)
        if node:
            likes = (
                node.get("like_count")
                or node.get("edge_media_preview_like", {}).get("count")
                or node.get("edge_liked_by", {}).get("count")
                or node.get("reaction_count", {}).get("count")
            )
            comments = (
                node.get("comment_count")
                or node.get("edge_media_to_comment", {}).get("count")
                or node.get("total_comment_count")
            )

            if likes is not None:
                counts = {"like_count": int(str(likes).replace(",", ""))}
                if comments is not None:
                    counts["comment_count"] = int(str(comments).replace(",", ""))
                counts["_source"] = "data_sjs"
                counts["_type"] = node.get("__typename", "Unknown")
                return counts

    # Strategy 2: Meta tag fallback (stale)
    meta_m = re.search(r'content="([\d,]+)\s+likes?', html, re.IGNORECASE)
    if meta_m:
        counts = {"like_count": int(meta_m.group(1).replace(",", ""))}
        comment_m = re.search(r'([\d,]+)\s+comments?', html, re.IGNORECASE)
        if comment_m:
            counts["comment_count"] = int(comment_m.group(1).replace(",", ""))
        counts["_source"] = "meta_tag"
        return counts

    print(f"  [live_fetch] IG: No engagement data for {shortcode}")
    return {}


# =========================================================================
# FACEBOOK: Brute-force recursive search (proven working for FB videos)
# =========================================================================

def _fb_recursive_search(obj):
    """
    Brute-force recursive search for FB engagement data.
    Returns {"likes": N, "comments": N} on first hit, or None.
    """
    res = {"likes": None, "comments": None}

    if isinstance(obj, dict):
        l = (
            obj.get("i18n_reaction_count")
            or obj.get("like_count")
            or (obj.get("reaction_count", {}).get("count")
                if isinstance(obj.get("reaction_count"), dict) else None)
        )
        if l is not None:
            try:
                res["likes"] = int(str(l).replace(",", ""))
            except (ValueError, TypeError):
                pass

        c = (
            obj.get("total_comment_count")
            or obj.get("comment_count")
            or (obj.get("comment_rendering_instance", {}).get("comments", {}).get("total_count")
                if isinstance(obj.get("comment_rendering_instance"), dict) else None)
        )
        if c is not None:
            try:
                res["comments"] = int(str(c).replace(",", ""))
            except (ValueError, TypeError):
                pass

        if res["likes"] is not None:
            return res

        for v in obj.values():
            found = _fb_recursive_search(v)
            if found and found["likes"] is not None:
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = _fb_recursive_search(item)
            if found and found["likes"] is not None:
                return found

    return None


def _fb_find_share_count(obj):
    """Recursively find share count in FB JSON."""
    if isinstance(obj, dict):
        val = obj.get("i18n_share_count") or obj.get("share_count")
        if val is not None:
            try:
                return int(str(val).replace(",", ""))
            except (ValueError, TypeError):
                pass
        for v in obj.values():
            found = _fb_find_share_count(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _fb_find_share_count(item)
            if found is not None:
                return found
    return None


def _fetch_fb(url):
    """
    Fetch FB engagement using brute-force recursive search.
    Filters blocks by engagement key presence, then searches.
    Retries with alternate headers if first attempt gets 400 (bot detection).
    """
    # Try two header strategies — FB bot detection varies by URL type
    header_strategies = [
        ("session+referer", FB_HEADERS),
        ("sec-fetch", IG_HEADERS),  # IG headers sometimes bypass FB bot detection
    ]

    resp = None
    for strategy_name, headers in header_strategies:
        try:
            if strategy_name == "session+referer":
                session = requests.Session()
                resp = session.get(url, headers=headers, timeout=20, allow_redirects=True)
            else:
                resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)

            if resp.status_code == 200:
                break
            elif resp.status_code in (429, 403):
                _record_error()
                print(f"  [live_fetch] FB HTTP {resp.status_code} ({strategy_name})")
                return {"_error": f"HTTP {resp.status_code}"}
            else:
                print(f"  [live_fetch] FB HTTP {resp.status_code} ({strategy_name}), trying next strategy...")
                continue

        except requests.RequestException as e:
            print(f"  [live_fetch] FB request error ({strategy_name}): {e}")
            continue

    if resp is None or resp.status_code != 200:
        _record_error()
        status = resp.status_code if resp else "no response"
        print(f"  [live_fetch] FB all strategies failed (last: {status})")
        return {"_error": f"HTTP {status}"}

    _record_success()
    html = resp.text

    blocks = re.findall(
        r'<script[^>]*type="application/json"[^>]*>([\s\S]*?)</script>', html
    )

    for block_str in blocks:
        if "i18n_reaction_count" not in block_str and "like_count" not in block_str:
            continue

        try:
            data = json.loads(block_str)
        except (json.JSONDecodeError, RecursionError):
            continue

        result = _fb_recursive_search(data)
        if result and result["likes"] is not None:
            counts = {"reaction_count": result["likes"]}
            if result["comments"] is not None:
                counts["comment_count"] = result["comments"]
            share_val = _fb_find_share_count(data)
            if share_val is not None:
                counts["share_count"] = share_val
            counts["_source"] = "relay_json"
            return counts

    # Meta tag fallback
    meta_m = re.search(r'content="([\d,]+)\s+Reactions?"', html, re.IGNORECASE)
    if meta_m:
        return {"reaction_count": int(meta_m.group(1).replace(",", "")), "_source": "meta_tag"}

    print(f"  [live_fetch] FB: No engagement data for {url[:60]}")
    return {}


# =========================================================================
# MAIN ENTRY POINT
# =========================================================================

def fetch_live_counts(url, delay=2.0):
    """
    Fetch live engagement counts from a Facebook or Instagram post URL.

    Returns dict with available counts:
        IG: like_count, comment_count
        FB: reaction_count, comment_count, share_count

    Returns empty dict or {"_error": ...} on failure.
    """
    if _paused:
        return {"_error": "live_fetch_paused"}

    time.sleep(delay)

    target_id = _extract_id(url)

    if "instagram.com" in url:
        if not target_id:
            return {"_error": "cannot_extract_shortcode"}
        return _fetch_ig(url, target_id)
    elif "facebook.com" in url:
        return _fetch_fb(url)
    else:
        return {"_error": "unknown_platform"}


# =========================================================================
# CLI
# =========================================================================

if __name__ == "__main__":
    import sys
    test_urls = [
        "https://www.instagram.com/p/DSbyfkSj_sO",
        "https://www.instagram.com/reels/DSpM2yniRzK",
        "https://www.facebook.com/playeateasy/posts/1192897706280130",
        "https://www.facebook.com/playeateasy/videos/1285183940317503",
    ]
    urls = sys.argv[1:] if len(sys.argv) > 1 else test_urls
    for u in urls:
        print(f"\n--- {u} ---")
        result = fetch_live_counts(u)
        if not result or (len(result) == 1 and "_error" in result):
            print(f"  FAILED: {result.get('_error', 'empty response')}")
        else:
            for k, v in sorted(result.items()):
                print(f"  {k}: {v}")
        if is_paused():
            print("  [!] Circuit breaker tripped — pausing live fetch")
            break
