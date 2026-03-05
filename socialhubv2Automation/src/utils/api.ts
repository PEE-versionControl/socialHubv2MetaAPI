// In production, VITE_API_BASE_URL points to the Railway backend.
// In dev mode (Vite on :5173), falls through to localhost:8000.
const API_BASE = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '');

const API_KEY = import.meta.env.VITE_API_KEY || '';

function apiHeaders(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...extra };
  if (API_KEY) h['X-API-Key'] = API_KEY;
  return h;
}

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
  const res = await fetch(`${API_BASE}/api/health`, { headers: apiHeaders() });
  if (!res.ok) throw new Error('Backend unavailable');
  return res.json();
}

export async function fetchAccounts(): Promise<Account[]> {
  const res = await fetch(`${API_BASE}/api/accounts`, { headers: apiHeaders() });
  if (!res.ok) throw new Error('Failed to fetch accounts');
  return res.json();
}

export async function submitUrlReport(urls: ReportUrlEntry[], include_live: boolean, account_key?: string): Promise<{ job_id: string }> {
  const res = await fetch(`${API_BASE}/api/report/by-urls`, {
    method: 'POST',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ urls, include_live, account_key: account_key || '' }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.statusText}`);
  return res.json();
}

export async function submitMonthReport(year_month: string, include_live: boolean, account_keys?: string[]): Promise<{ job_id: string }> {
  const res = await fetch(`${API_BASE}/api/report/by-month`, {
    method: 'POST',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ year_month, include_live, account_keys: account_keys || [] }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.statusText}`);
  return res.json();
}

export async function getJobStatus(job_id: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/report/status/${job_id}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(`Failed: ${res.statusText}`);
  return res.json();
}

export async function cancelJob(job_id: string): Promise<void> {
  await fetch(`${API_BASE}/api/report/cancel/${job_id}`, { method: 'POST', headers: apiHeaders() });
}

export async function downloadExcelReport(job_id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/report/excel/${job_id}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(`Download failed: ${res.statusText}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const cd = res.headers.get('content-disposition');
  const match = cd?.match(/filename[^;=\n]*=['"]?([^'";\n]+)/i);
  a.download = match?.[1] || `report_${job_id}.xlsx`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
