# Meta Performance Metrics — Social Hub

A self-hosted tool that pulls **Facebook + Instagram post insights** (organic) and **Ad Manager insights** (paid) from the Meta Graph API, and displays them in the **Social Hub** dashboard.

---

## Architecture

```
metaAPIProject/
├── api_server.py                  ← FastAPI backend (single port: 8000)
├── facebookSightTest5Feb.py       ← Core Meta API script (FB + IG insights)
├── report_api.py                  ← Report helpers + Firestore formatter
├── requirements.txt               ← Python dependencies
└── socialhubTest-.../             ← React/Vite frontend (Social Hub UI)
    └── dist/                      ← Built frontend (served by FastAPI)
```

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.10+ |
| Node.js | 18+ |
| pip | latest |

---

## Setup

### 1 — Clone the repo

```bash
git clone <repo-url>
cd metaAPIProject
```

### 2 — Configure credentials

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

| Variable | Where to get it |
|----------|----------------|
| `ACCOUNT_NAME` | Your Facebook Page name (display only) |
| `FACEBOOK_ACCESS_TOKEN` | Meta Business Suite → Settings → Page Access Tokens |
| `FACEBOOK_PAGE_ID` | Facebook Page → About (numeric ID) |
| `FACEBOOK_AD_ACCOUNT_ID` | Meta Ads Manager → Account Overview (prefix with `act_`) |
| `IG_ACCESS_TOKEN` | Same token as FB if pages are linked, or generate separately |
| `IG_BUSINESS_ID` | Instagram → Professional dashboard → Account ID |
| `VITE_FIREBASE_*` | Firebase console → Project settings → SDK config |

> **Token permissions required:**
> `pages_read_engagement`, `pages_show_list`, `ads_read`,
> `instagram_basic`, `instagram_manage_insights`, `business_management`

### 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4 — Build the frontend

```bash
cd socialhubTest-claude-review-project-overview-d72PO
npm install
npm run build
cd ..
```

The build output lands in `socialhubTest-.../dist/` and is automatically served by the backend.

### 5 — Start the server

```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000** in your browser.

---

## Remote / Demo Access (optional)

To expose the app for a client demo without deploying:

**ngrok:**
```bash
ngrok http 8000
# Share the https://xxxx.ngrok-free.app URL
```

**Cloudflare Tunnel (no account needed for quick demo):**
```bash
cloudflared tunnel --url http://localhost:8000
```

---

## Multi-Account Support

To add a second brand/account, add a prefixed block to `.env`:

```env
BRAND2_ACCOUNT_NAME=Second Brand
BRAND2_FACEBOOK_ACCESS_TOKEN=EAAxxxx
BRAND2_FACEBOOK_PAGE_ID=999888777
BRAND2_FACEBOOK_AD_ACCOUNT_ID=act_123456
BRAND2_IG_ACCESS_TOKEN=EAAxxxx
BRAND2_IG_BUSINESS_ID=123456789
```

The backend auto-discovers all prefixed accounts and exposes them via `GET /api/accounts`.

---

## Generating Reports

### Via the UI

1. Click **Meta Performance Metrics Report** in the sidebar
2. Choose **URL mode** (paste post links) or **Monthly scan** (auto-discovers all posts)
3. Click **Run** and wait for results
4. Save individual posts to Social Hub or download CSVs

### Via CLI

```bash
# Single post
python3 report_api.py https://www.facebook.com/page/posts/123 2025-12-31

# Batch file
python3 report_api.py -f urls.txt

# Full month (auto-discover all FB + IG posts)
python3 report_api.py --month 2025-12

# Custom output directory
python3 report_api.py --month 2025-12 -o ./reports/
```

---

## Obtaining Your Own Tokens

> The provided tokens are tied to a specific Facebook App and Page. Each client must generate their own.

1. Go to [Meta for Developers](https://developers.facebook.com) → Your App → Tools → Graph API Explorer
2. Select your Page from the dropdown
3. Add permissions: `pages_read_engagement`, `ads_read`, `instagram_manage_insights`
4. Click **Generate Access Token**
5. For a **long-lived token** (60 days): exchange via the Token Debugger or the `oauth/access_token` endpoint
6. For a **never-expiring Page token**: generate a System User token in Meta Business Suite → Settings → System Users

---

## Project Notes

- API version: `v24.0`
- Rate limiting: the script adds 0.5 s between calls automatically
- Monthly scan for ~300 posts takes ~3 hours (Meta API rate limits)
- Saves are not available via the public Graph API for organic posts (always 0)
- Reach is slightly over-counted for boosted posts (API cannot de-duplicate organic + paid audiences)
