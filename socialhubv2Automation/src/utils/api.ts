// In dev mode (Vite on :5173), API is on :8000.
// In production (single-process), API is same origin.
const API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : '';

export interface ReportUrlEntry {
  url: string;
  end_date: string;
}

export interface AdMetric {
  campaign_name: string;
  adset_name: string;
  spend: number;
  impressions: number;
  reach: number;
  frequency: number;
  link_clicks: number;
  clicks_all: number;
  post_engagement: number;
  reactions: number;
  comments: number;
  shares: number;
  saves: number;
  thruplays: number;
  video_100: number;
}

export interface FirestoreData {
  postUrl: string;
  platform: string;
  title: string;
  content: string;
  likes: number;
  reach: number;
  shares: number;
  comments: number;
  clicks: number;
  isVideo: boolean;
  account: string | null;
  createdAt: string | null;
  _views: number;
  _interactions: number;
  _saves: number;
  _date_range: string;
  _platform_full: string;
}

export interface ReportResult {
  platform: string;
  url: string;
  date_range: string;
  views: number;
  reach: number;
  interactions: number;
  reactions: number;
  comments: number;
  shares: number;
  saves: number;
  link_clicks: number;
  live_reactions?: number | null;
  live_comments?: number | null;
  live_shares?: number | null;
  ad_metrics: AdMetric[];
  firestore: FirestoreData;
  account?: string;
}

export interface JobStatus {
  job_id: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  total: number;
  current_url: string;
  results: ReportResult[];
  errors: { url: string; error: string }[];
  live_fetch_paused: boolean;
  status_detail: string;
  completed_at: string | null;
}

export interface Account {
  key: string;
  name: string;
  page_id: string;
  has_fb_token: boolean;
  has_ig_token: boolean;
  has_ad_account: boolean;
}

export async function checkHealth(): Promise<{ status: string; fb_token: boolean; ig_token: boolean }> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error('Backend unavailable');
  return res.json();
}

export async function fetchAccounts(): Promise<Account[]> {
  const res = await fetch(`${API_BASE}/api/accounts`);
  if (!res.ok) throw new Error('Failed to fetch accounts');
  return res.json();
}

export async function submitUrlReport(urls: ReportUrlEntry[], include_live: boolean): Promise<{ job_id: string }> {
  const res = await fetch(`${API_BASE}/api/report/by-urls`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls, include_live }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.statusText}`);
  return res.json();
}

export async function submitMonthReport(year_month: string, include_live: boolean, account_keys?: string[]): Promise<{ job_id: string }> {
  const res = await fetch(`${API_BASE}/api/report/by-month`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year_month, include_live, account_keys: account_keys || [] }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.statusText}`);
  return res.json();
}

export async function getJobStatus(job_id: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/report/status/${job_id}`);
  if (!res.ok) throw new Error(`Failed: ${res.statusText}`);
  return res.json();
}

export async function cancelJob(job_id: string): Promise<void> {
  await fetch(`${API_BASE}/api/report/cancel/${job_id}`, { method: 'POST' });
}
