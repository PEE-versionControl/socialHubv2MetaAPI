#!/usr/bin/env python3
"""
FastAPI Backend for Social Hub Reports
========================================
Provides async job management for generating Meta API insight reports.

Endpoints:
    POST /api/report/by-urls     → submit URLs for processing
    POST /api/report/by-month    → submit month for auto-discovery
    GET  /api/report/status/{id} → poll job progress + results
    GET  /api/health             → backend health check
    GET  /api/accounts           → list available accounts

Start:
    pip install fastapi uvicorn
    uvicorn api_server:app --reload --port 8000
"""

import os
import sys
import time
import uuid
import threading
from datetime import datetime
from urllib.parse import quote as _url_quote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel

# Import from existing scripts
from facebookSightTest5Feb import (
    process_single_url,
    parse_input_file,
    ACCESS_TOKEN,
    PAGE_ID,
    AD_ACCOUNT_ID,
)
from live_fetch import fetch_live_counts, is_paused, reset_circuit_breaker
from report_api import result_to_firestore_format, build_work_items_for_month
from excel_report import generate_excel_report, generate_excel_report_combined


app = FastAPI(title="Social Hub Report API", version="1.0.0")

ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:8000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


# --- API Key Authentication ---
API_KEY = os.environ.get("API_KEY", "")


@app.middleware("http")
async def check_api_key(request, call_next):
    """Reject unauthenticated requests to /api/ routes (except health and OPTIONS)."""
    # Always let CORS preflight through — browsers send no custom headers on OPTIONS
    if request.method == "OPTIONS":
        return await call_next(request)
    # Skip auth for health check
    if not request.url.path.startswith("/api/") or request.url.path == "/api/health":
        return await call_next(request)
    # Skip if no API_KEY configured (local dev)
    if not API_KEY:
        return await call_next(request)
    if request.headers.get("X-API-Key") != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


# In-memory job store
task_store: dict = {}


# --- Account Registry ---
# Auto-discover accounts from .env by scanning for *_FACEBOOK_PAGE_ID patterns
ACCOUNTS = {}

def _load_accounts():
    """Scan .env for account credentials using PREFIX_FACEBOOK_PAGE_ID pattern."""
    from dotenv import load_dotenv
    load_dotenv()

    # Track prefixes that have PAGE_ID
    prefixes = set()
    for key in os.environ:
        if key.endswith("_FACEBOOK_PAGE_ID"):
            prefix = key[: -len("_FACEBOOK_PAGE_ID")]
            prefixes.add(prefix)

    # For each prefix, build account dict
    for prefix in prefixes:
        page_id = os.getenv(f"{prefix}_FACEBOOK_PAGE_ID")
        if not page_id:
            continue

        # Derive account name from prefix (convert PLAY_EAT_EASY -> Play Eat Easy)
        account_name = prefix.replace("_", " ").title() if prefix else "Default"
        account_key = prefix.lower() if prefix else "default"

        ACCOUNTS[account_key] = {
            "name": account_name,
            "fb_token": os.getenv(f"{prefix}_FACEBOOK_ACCESS_TOKEN", ""),
            "ig_token": os.getenv(f"{prefix}_IG_ACCESS_TOKEN", ""),
            "page_id": page_id,
            "ad_account_id": os.getenv(f"{prefix}_FACEBOOK_AD_ACCOUNT_ID", ""),
            "ig_business_id": os.getenv(f"{prefix}_IG_BUSINESS_ID", ""),
        }

    # Add legacy unprefixed account if it exists.
    # ACCOUNT_NAME env var lets you name this account (e.g. "Play Eat Easy").
    if os.getenv("FACEBOOK_PAGE_ID") and "" not in [p for p in prefixes if p]:
        ACCOUNTS["default"] = {
            "name": os.getenv("ACCOUNT_NAME", "Default Account"),
            "fb_token": os.getenv("FACEBOOK_ACCESS_TOKEN", ""),
            "ig_token": os.getenv("IG_ACCESS_TOKEN", ""),
            "page_id": os.getenv("FACEBOOK_PAGE_ID", ""),
            "ad_account_id": os.getenv("FACEBOOK_AD_ACCOUNT_ID", ""),
            "ig_business_id": os.getenv("IG_BUSINESS_ID", ""),
        }

_load_accounts()


def _swap_account(account_key: str):
    """Swap module-level globals in facebookSightTest5Feb to target account."""
    import facebookSightTest5Feb as meta_api

    if account_key not in ACCOUNTS:
        raise ValueError(f"Unknown account: {account_key}")

    acct = ACCOUNTS[account_key]
    meta_api.ACCESS_TOKEN = acct["fb_token"]
    meta_api.IG_ACCESS_TOKEN = acct["ig_token"]
    meta_api.PAGE_ID = acct["page_id"]
    meta_api.AD_ACCOUNT_ID = acct["ad_account_id"]

    # Also update BASE_URL if needed (though it shouldn't change)
    # meta_api.BASE_URL is constructed from API_VERSION which is constant


# --- Request/Response Models ---

class UrlReportRequest(BaseModel):
    urls: list[dict]  # [{"url": "...", "end_date": "YYYY-MM-DD"}, ...]
    include_live: bool = False
    account_key: str = ""  # Which account to use (empty = default)

class MonthReportRequest(BaseModel):
    year_month: str  # "YYYY-MM"
    include_live: bool = False
    account_keys: list[str] = []  # Which accounts to process (empty = all)

class JobResponse(BaseModel):
    job_id: str
    status: str


# --- Helper: format result for frontend ---

def format_result(r, live_counts=None, account_name=None):
    """Convert process_single_url result to frontend-friendly dict.

    Returns both display data and Firestore-compatible data for the
    "Both approach": CSV download + save to Social Hub.
    """
    pm = r.get("post_metrics", {})
    ad_list = r.get("ad_metrics") or []

    out = {
        "platform": r.get("platform", "Unknown"),
        "url": r.get("url", ""),
        "date_range": r.get("date_range_str", ""),
        "views": pm.get("Views", 0),
        "reach": pm.get("Reach", 0),
        "interactions": pm.get("Interactions", 0),
        "reactions": pm.get("Reactions_Total", 0),
        "comments": pm.get("Comments", 0),
        "shares": pm.get("Shares", 0),
        "saves": pm.get("Saves", 0),
        "link_clicks": pm.get("Link_Clicks", 0),
        # Per-post ad metrics for CSV generation in frontend
        "ad_metrics": [
            {
                "campaign_name": am.get("campaign_name", "N/A"),
                "adset_name": am.get("adset_name", "N/A"),
                "date_start": am.get("date_start", ""),
                "adset_start_time": am.get("adset_start_time", ""),
                "spend": round(am.get("spend", 0), 2),
                "impressions": am.get("impressions", 0),
                "reach": am.get("reach", 0),
                "frequency": round(am.get("frequency", 0), 2),
                "link_clicks": am.get("link_clicks", 0),
                "clicks_all": am.get("clicks_all", 0),
                "post_engagement": am.get("post_engagement", 0),
                "reactions": am.get("reactions", 0),
                "comments": am.get("comments", 0),
                "shares": am.get("shares", 0),
                "saves": am.get("saves", 0),
                "thruplays": am.get("thruplays", 0),
                "video_100": am.get("video_100", 0),
            }
            for am in ad_list
        ],
        # IDs for image fetching in Excel report
        "ig_media_id": r.get("_ig_media_id", ""),
        "fb_post_id": r.get("_post_id", ""),
        # Firestore-compatible format for "Save to Social Hub"
        "firestore": result_to_firestore_format(r, account_name=account_name),
    }
    if live_counts and "_error" not in live_counts:
        out["live_reactions"] = live_counts.get("reaction_count", live_counts.get("like_count"))
        out["live_comments"] = live_counts.get("comment_count")
        out["live_shares"] = live_counts.get("share_count")

    # Add account name if provided (for multi-account reports)
    if account_name:
        out["account"] = account_name

    return out


# --- Background Workers ---

def _process_urls_worker(job_id: str, urls: list[dict], include_live: bool):
    """Background worker for URL-based report."""
    job = task_store[job_id]
    job["total"] = len(urls)
    results = []

    if include_live:
        reset_circuit_breaker()

    # Determine account name from the currently active PAGE_ID (for IG posts that
    # have no account name in the URL). Skip generic "Default Account" placeholder.
    try:
        import facebookSightTest5Feb as _meta
        _active_page = str(getattr(_meta, "PAGE_ID", ""))
        _url_account = next(
            (a["name"] for a in ACCOUNTS.values()
             if a.get("page_id") == _active_page and a["name"] != "Default Account"),
            None
        )
    except Exception:
        _url_account = None

    for i, entry in enumerate(urls):
        if job.get("cancelled"):
            job["status"] = "cancelled"
            return

        url = entry.get("url", "")
        end_date = entry.get("end_date", "")
        job["progress"] = i
        job["current_url"] = url

        try:
            result = process_single_url(url, end_date)
            if result:
                live = None
                if include_live and not is_paused():
                    live = fetch_live_counts(url)
                    if is_paused():
                        job["live_fetch_paused"] = True

                formatted = format_result(result, live, account_name=_url_account)
                results.append(formatted)
                job["results"] = results
        except Exception as e:
            job["errors"] = job.get("errors", []) + [{"url": url, "error": str(e)}]

        job["progress"] = i + 1

    job["status"] = "completed"
    job["results"] = results
    job["completed_at"] = datetime.now().isoformat()


def _process_month_worker(job_id: str, year_month: str, include_live: bool, account_keys: list[str] = None):
    """Background worker for monthly report (supports multi-account)."""
    job = task_store[job_id]

    try:
        parts = year_month.split("-")
        year = int(parts[0])
        month = int(parts[1])
        if month < 1 or month > 12:
            raise ValueError
    except (ValueError, IndexError):
        job["status"] = "failed"
        job["error"] = f"Invalid month format: {year_month}"
        return

    if include_live:
        reset_circuit_breaker()

    # Determine which accounts to process
    if not account_keys:
        account_keys = list(ACCOUNTS.keys())
    else:
        # Validate account keys
        invalid = [k for k in account_keys if k not in ACCOUNTS]
        if invalid:
            job["status"] = "failed"
            job["error"] = f"Unknown account(s): {', '.join(invalid)}"
            return

    all_results = []

    # Process each account
    for account_idx, account_key in enumerate(account_keys):
        if job.get("cancelled"):
            job["status"] = "cancelled"
            return

        account = ACCOUNTS[account_key]
        job["status_detail"] = f"[{account['name']}] Discovering posts and scanning ad end dates..."

        # Swap to this account's credentials
        try:
            _swap_account(account_key)
        except Exception as e:
            job["errors"] = job.get("errors", []) + [{"url": f"Account: {account['name']}", "error": f"Failed to swap credentials: {str(e)}"}]
            continue

        # Build work items for this account
        try:
            work_items = build_work_items_for_month(year_month)
        except Exception as e:
            job["errors"] = job.get("errors", []) + [{"url": f"Account: {account['name']}", "error": f"Failed to discover posts: {str(e)}"}]
            continue

        if not work_items:
            job["status_detail"] = f"[{account['name']}] No posts found"
            continue

        # Update total count (sum across all accounts)
        if account_idx == 0:
            job["total"] = len(work_items)
        else:
            job["total"] += len(work_items)

        job["status_detail"] = f"[{account['name']}] Processing {len(work_items)} posts..."

        # Process posts for this account
        for i, item in enumerate(work_items):
            if job.get("cancelled"):
                job["status"] = "cancelled"
                return

            job["current_url"] = f"[{account['name']}] {item['url']}"

            try:
                result = process_single_url(item["url"], item["end_date"])
                if result:
                    live = None
                    if include_live and not is_paused():
                        live = fetch_live_counts(item["url"])
                        if is_paused():
                            job["live_fetch_paused"] = True

                    formatted = format_result(result, live, account_name=account['name'])
                    all_results.append(formatted)
                    job["results"] = all_results
            except Exception as e:
                job["errors"] = job.get("errors", []) + [{"url": item["url"], "error": str(e)}]

            job["progress"] += 1

    job["status"] = "completed"
    job["results"] = all_results
    job["completed_at"] = datetime.now().isoformat()


# --- Endpoints ---

@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "fb_token": bool(ACCESS_TOKEN),
        "ig_token": bool(os.getenv("IG_ACCESS_TOKEN")),
        "ad_account": bool(AD_ACCOUNT_ID),
        "page_id": PAGE_ID,
    }


@app.get("/api/accounts")
def list_accounts():
    """Return list of available accounts from .env."""
    return [
        {
            "key": key,
            "name": acct["name"],
            "page_id": acct["page_id"],
            "has_fb_token": bool(acct["fb_token"]),
            "has_ig_token": bool(acct["ig_token"]),
            "has_ad_account": bool(acct["ad_account_id"]),
        }
        for key, acct in ACCOUNTS.items()
    ]


@app.post("/api/report/by-urls", response_model=JobResponse)
def create_url_report(req: UrlReportRequest):
    if not req.urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    # Swap account if specified
    account_key = req.account_key
    if account_key and account_key in ACCOUNTS:
        _swap_account(account_key)
    elif not account_key and ACCOUNTS:
        # Default to first account to ensure consistent state after restarts
        account_key = list(ACCOUNTS.keys())[0]
        _swap_account(account_key)

    job_id = str(uuid.uuid4())[:8]
    task_store[job_id] = {
        "status": "running",
        "type": "by-urls",
        "progress": 0,
        "total": len(req.urls),
        "current_url": "",
        "results": [],
        "errors": [],
        "live_fetch_paused": False,
        "created_at": datetime.now().isoformat(),
    }

    t = threading.Thread(
        target=_process_urls_worker,
        args=(job_id, req.urls, req.include_live),
        daemon=True,
    )
    t.start()

    return JobResponse(job_id=job_id, status="running")


@app.post("/api/report/by-month", response_model=JobResponse)
def create_month_report(req: MonthReportRequest):
    job_id = str(uuid.uuid4())[:8]
    task_store[job_id] = {
        "status": "running",
        "type": "by-month",
        "progress": 0,
        "total": 0,
        "current_url": "",
        "results": [],
        "errors": [],
        "live_fetch_paused": False,
        "status_detail": "Starting...",
        "created_at": datetime.now().isoformat(),
    }

    t = threading.Thread(
        target=_process_month_worker,
        args=(job_id, req.year_month, req.include_live, req.account_keys),
        daemon=True,
    )
    t.start()

    return JobResponse(job_id=job_id, status="running")


@app.get("/api/report/status/{job_id}")
def get_report_status(job_id: str):
    if job_id not in task_store:
        raise HTTPException(status_code=404, detail="Job not found")

    job = task_store[job_id]

    # Compute elapsed time from created_at
    elapsed_seconds = None
    created_at = job.get("created_at")
    if created_at:
        try:
            start = datetime.fromisoformat(created_at)
            end = datetime.fromisoformat(job["completed_at"]) if job.get("completed_at") else datetime.now()
            elapsed_seconds = int((end - start).total_seconds())
        except (ValueError, TypeError):
            pass

    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "total": job["total"],
        "current_url": job.get("current_url", ""),
        "results": job.get("results", []),
        "errors": job.get("errors", []),
        "live_fetch_paused": job.get("live_fetch_paused", False),
        "status_detail": job.get("status_detail", ""),
        "completed_at": job.get("completed_at"),
        "elapsed_seconds": elapsed_seconds,
    }


@app.post("/api/report/cancel/{job_id}")
def cancel_report(job_id: str):
    if job_id not in task_store:
        raise HTTPException(status_code=404, detail="Job not found")
    task_store[job_id]["cancelled"] = True
    return {"status": "cancelling"}


def _content_disposition(filename: str) -> str:
    """Build a Content-Disposition header that safely handles Unicode filenames.

    HTTP headers must be Latin-1 encodable. Campaign names often contain
    en/em dashes and other Unicode characters that crash header encoding.
    We use RFC 5987 (filename*=UTF-8'') for full Unicode support, with an
    ASCII fallback for older clients.
    """
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    utf8_name = _url_quote(filename, safe=" -()+#.,")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'


@app.get("/api/report/excel/{job_id}")
def download_excel_combined(job_id: str):
    """Generate combined Excel report for all results in a job (FB + IG on one sheet)."""
    job = task_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    results = job.get("results", [])
    if not results:
        raise HTTPException(status_code=404, detail="No results in job")

    import facebookSightTest5Feb as _meta
    fb_token   = getattr(_meta, "ACCESS_TOKEN",    os.getenv("FACEBOOK_ACCESS_TOKEN", ""))
    ig_token   = getattr(_meta, "IG_ACCESS_TOKEN", os.getenv("IG_ACCESS_TOKEN", ""))
    page_id    = getattr(_meta, "PAGE_ID",         os.getenv("FACEBOOK_PAGE_ID", ""))
    ig_user_id = os.getenv("IG_BUSINESS_ID", "")

    buf = generate_excel_report_combined(
        results,
        fb_token=fb_token,
        ig_token=ig_token,
        page_id=page_id,
        ig_user_id=ig_user_id,
    )
    # Extract campaign info for filename: "#12345 CampaignName Post-Buy Report.xlsx"
    from excel_report import parse_campaign_header as _parse_header
    import re as _re
    _adset_names = []
    _campaign_names = []
    for r in results:
        _adset_names += [am.get("adset_name", "") for am in r.get("ad_metrics", [])]
        _campaign_names += [am.get("campaign_name", "") for am in r.get("ad_metrics", [])]
    _campaign = _parse_header(_adset_names, _campaign_names)
    print(f"  [Excel filename] adset_names={_adset_names[:3]}, campaign_names={_campaign_names[:3]}")
    print(f"  [Excel filename] parsed: code='{_campaign.get('code','')}', name='{_campaign.get('name','')}'")
    print(f"  [Excel filename] full_campaign_name='{_campaign.get('full_campaign_name','')}'")
    code = _campaign.get("code", "")
    name = _campaign.get("name", "")
    if code and name:
        safe_name = _re.sub(r'[<>:"/\\|?*]', '', f"#{code} {name}").strip()
        filename = f"{safe_name} Post-Buy Report.xlsx"
    elif name:
        safe_name = _re.sub(r'[<>:"/\\|?*]', '', name).strip()
        filename = f"{safe_name} Post-Buy Report.xlsx"
    else:
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"report_combined_{date_str}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@app.get("/api/report/excel/{job_id}/{result_index}")
def download_excel_report(job_id: str, result_index: int):
    """Generate and return an Excel (.xlsx) report for a single result."""
    job = task_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    results = job.get("results", [])
    if result_index >= len(results):
        raise HTTPException(status_code=404, detail="Result index out of range")

    result = results[result_index]

    # Use the currently active credentials (swapped per account)
    import facebookSightTest5Feb as _meta
    fb_token   = getattr(_meta, "ACCESS_TOKEN",    os.getenv("FACEBOOK_ACCESS_TOKEN", ""))
    ig_token   = getattr(_meta, "IG_ACCESS_TOKEN", os.getenv("IG_ACCESS_TOKEN", ""))
    page_id    = getattr(_meta, "PAGE_ID",         os.getenv("FACEBOOK_PAGE_ID", ""))
    ig_user_id = os.getenv("IG_BUSINESS_ID", "")

    buf = generate_excel_report(
        result,
        fb_token=fb_token,
        ig_token=ig_token,
        page_id=page_id,
        ig_user_id=ig_user_id,
    )

    # Extract campaign info for filename: "#12345 CampaignName Post-Buy Report.xlsx"
    from excel_report import parse_campaign_header as _parse_header
    import re as _re
    _adset_names = [am.get("adset_name", "") for am in result.get("ad_metrics", [])]
    _campaign_names = [am.get("campaign_name", "") for am in result.get("ad_metrics", [])]
    _campaign = _parse_header(_adset_names, _campaign_names)
    code = _campaign.get("code", "")
    name = _campaign.get("name", "")
    if code and name:
        safe_name = _re.sub(r'[<>:"/\\|?*]', '', f"#{code} {name}").strip()
        filename = f"{safe_name} Post-Buy Report.xlsx"
    elif name:
        safe_name = _re.sub(r'[<>:"/\\|?*]', '', name).strip()
        filename = f"{safe_name} Post-Buy Report.xlsx"
    else:
        platform = result.get("platform", "")[:2].upper()
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"report_{platform}_{result_index}_{date_str}.xlsx"

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _content_disposition(filename)},
    )



if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
