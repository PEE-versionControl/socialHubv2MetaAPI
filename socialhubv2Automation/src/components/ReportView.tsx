import { useState, useEffect, useRef, useCallback } from 'react';
import { Play, StopCircle, FileText, Link2, Calendar, ToggleLeft, ToggleRight, Loader2, AlertTriangle, CheckCircle2, Clock, ExternalLink, Save, CheckSquare, Square, X, FileSpreadsheet } from 'lucide-react';
import { collection, doc, writeBatch, serverTimestamp, Timestamp } from 'firebase/firestore';
import { signInAnonymously } from 'firebase/auth';
import { db, appId, auth } from '../config/firebase';
import { checkHealth, submitUrlReport, submitMonthReport, getJobStatus, cancelJob, fetchAccounts, downloadExcelReport } from '../utils/api';
import type { JobStatus, Account } from '../utils/api';
import type { Post } from '../types';
import { autoCategorize } from '../utils/helpers';

type InputMode = 'urls' | 'month';

// const POST_HEADERS = ['Platform', 'Post Link', 'Date Range', 'Views', 'Reach', 'Interactions', 'Likes and reactions', 'Comments', 'Shares', 'Saves', 'Link clicks'];
// const AD_HEADERS = ['Campaign Name', 'Ad Set Name', 'Date Range', 'Amount spent', 'Impression', 'Reach', 'Frequency', 'Link Clicks', 'Click(All)', 'Post engagement', 'Post reactions', 'Post comments', 'Post shares', 'Post saves', 'ThruPlays', 'Video plays at 100%'];

// CSV helper functions — disabled per user request, kept for future use
// function extractId(url: string): string {
//   const m = url.match(/\/(?:p|reels?|videos|posts)\/([^/?#&]+)/);
//   return m ? m[1] : 'unknown';
// }
// function generatePerPostCsv(r: ReportResult): string { ... }
// function downloadCsv(content: string, filename: string) { ... }

interface Props {
  existingPosts: Post[];
}

const SESSION_KEY = 'metaReport_session';

function loadSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export default function ReportView({ existingPosts }: Props) {
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  // Restore form + results from sessionStorage on first mount
  const _saved = loadSession();
  const [inputMode, setInputMode] = useState<InputMode>(_saved?.inputMode ?? 'urls');
  const [urlText, setUrlText] = useState<string>(_saved?.urlText ?? '');
  const [yearMonth, setYearMonth] = useState<string>(_saved?.yearMonth ?? '');
  const [includeLive, setIncludeLive] = useState<boolean>(_saved?.includeLive ?? false);

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([]);
  const [selectedUrlAccount, setSelectedUrlAccount] = useState<string>('');

  const [jobId, setJobId] = useState<string | null>(_saved?.jobId ?? null);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(_saved?.jobStatus ?? null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDownloadingExcel, setIsDownloadingExcel] = useState(false);
  const [saveResult, setSaveResult] = useState<{ created: number; updated: number } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Persist key state to sessionStorage whenever it changes
  useEffect(() => {
    try {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({ inputMode, urlText, yearMonth, includeLive, jobId, jobStatus }));
    } catch { /* storage full or unavailable */ }
  }, [inputMode, urlText, yearMonth, includeLive, jobId, jobStatus]);

  // Health check
  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        await checkHealth();
        if (mounted) setBackendOk(true);
      } catch {
        if (mounted) setBackendOk(false);
      }
    };
    check();
    const interval = setInterval(check, 15000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  // Fetch accounts
  useEffect(() => {
    let mounted = true;
    const loadAccounts = async () => {
      try {
        const accts = await fetchAccounts();
        if (mounted) {
          setAccounts(accts);
          // Select all accounts by default for monthly mode
          setSelectedAccounts(accts.map(a => a.key));
          // Select first account for URL mode
          if (accts.length > 0) setSelectedUrlAccount(accts[0].key);
        }
      } catch (e) {
        console.error('Failed to load accounts:', e);
      }
    };
    loadAccounts();
    return () => { mounted = false; };
  }, []);

  // Poll job status. Also resumes polling if user navigated away mid-job and came back.
  useEffect(() => {
    if (!jobId) return;
    // If the restored status is already terminal, don't re-poll
    if (jobStatus?.status === 'completed' || jobStatus?.status === 'cancelled') return;
    const poll = async () => {
      try {
        const status = await getJobStatus(jobId);
        setJobStatus(status);
        if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch {
        // Backend might be temporarily unreachable
      }
    };
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  const parseUrls = useCallback(() => {
    return urlText
      .split('\n')
      .map(line => line.trim())
      .filter(line => line && !line.startsWith('#'))
      .map(line => {
        const parts = line.split(/\s+/);
        const url = parts[0];
        const end_date = parts[1] || new Date().toISOString().slice(0, 10);
        return { url, end_date };
      });
  }, [urlText]);

  const handleSubmit = async () => {
    if (!backendOk) return;
    setIsSubmitting(true);
    setJobStatus(null);
    setSaveResult(null);

    try {
      let response;
      if (inputMode === 'urls') {
        const urls = parseUrls();
        if (!urls.length) { alert('Please enter at least one URL.'); setIsSubmitting(false); return; }
        response = await submitUrlReport(urls, includeLive, selectedUrlAccount);
      } else {
        if (!yearMonth) { alert('Please select a month.'); setIsSubmitting(false); return; }
        if (selectedAccounts.length === 0) { alert('Please select at least one account.'); setIsSubmitting(false); return; }
        response = await submitMonthReport(yearMonth, includeLive, selectedAccounts);
      }
      setJobId(response.job_id);
    } catch (e: any) {
      alert(`Error: ${e.message}`);
    }
    setIsSubmitting(false);
  };

  const handleCancel = async () => {
    if (jobId) await cancelJob(jobId);
  };

  const toggleAccount = (key: string) => {
    setSelectedAccounts(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
  };

  const toggleAllAccounts = () => {
    if (selectedAccounts.length === accounts.length) {
      setSelectedAccounts([]);
    } else {
      setSelectedAccounts(accounts.map(a => a.key));
    }
  };

  // CSV download handlers — disabled per user request, kept for future use
  // const handleDownloadAll = () => {
  //   if (!jobStatus?.results?.length) return;
  //   const csv = jobStatus.results.map(r => generatePerPostCsv(r)).join('\n\n');
  //   downloadCsv(csv, `report_combined_${new Date().toISOString().slice(0, 10)}.csv`);
  // };
  // const handleDownloadPost = (r: ReportResult) => {
  //   const prefix = r.platform === 'Instagram' ? 'IG' : 'FB';
  //   const contentId = extractId(r.url);
  //   const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  //   const filename = `report_${prefix}_${contentId}_${dateStr}.csv`;
  //   downloadCsv(generatePerPostCsv(r), filename);
  // };
  // const handleDownloadAllPerPost = () => {
  //   if (!jobStatus?.results?.length) return;
  //   for (const r of jobStatus.results) handleDownloadPost(r);
  // };

  // Save to Social Hub (Firestore) — smart merge by URL
  const handleSaveToSocialHub = async () => {
    if (!jobStatus?.results?.length) return;
    if (!confirm(`Save ${jobStatus.results.length} post(s) to Social Hub?\nExisting posts with matching URLs will be updated.`)) return;

    setIsSaving(true);
    setSaveResult(null);

    try {
      // Ensure anonymous auth is ready before any Firestore write
      if (!auth.currentUser) {
        await signInAnonymously(auth);
      }
      const normalize = (u: string) => (u || '').trim().toLowerCase().replace(/\/+$/, '');
      const urlToIdMap = new Map<string, string>();
      existingPosts.forEach(p => {
        const n = normalize(p.postUrl || '');
        if (n) urlToIdMap.set(n, p.id);
      });

      const ref = collection(db, 'artifacts', appId, 'public', 'data', 'social_posts');
      const CHUNK_SIZE = 20;
      let created = 0;
      let updated = 0;

      const tasks: { type: 'create' | 'update'; id?: string; data: any }[] = [];

      for (const r of jobStatus.results) {
        const fs = r.firestore;
        const normUrl = normalize(fs.postUrl);
        const existingId = normUrl ? urlToIdMap.get(normUrl) : undefined;

        if (existingId) {
          // Update existing post with fresh metrics
          tasks.push({
            type: 'update',
            id: existingId,
            data: {
              likes: fs.likes,
              reach: fs.reach,
              shares: fs.shares,
              comments: fs.comments,
              clicks: fs.clicks,
              isVideo: fs.isVideo,
              platform: fs.platform,
              updatedAt: serverTimestamp(),
            },
          });
          updated++;
        } else {
          // Create new post — auto-categorize series and detect editor from hashtags
          const { series, tags } = autoCategorize(fs.title || '', fs.content || '');
          const fullText = ((fs.title || '') + ' ' + (fs.content || '')).toLowerCase();
          let editor: string | null = null;
          if (fullText.includes('#psks')) editor = 'Kassandra';
          else if (fullText.includes('#pska')) editor = 'Kathy';
          else if (fullText.includes('#psr')) editor = 'Rachel';
          else if (fullText.includes('#psl')) editor = 'Loris';
          else if (fullText.includes('#psc')) editor = 'Chloe';
          else if (fullText.includes('#psk')) editor = 'Kiki';
          tasks.push({
            type: 'create',
            data: {
              postUrl: fs.postUrl,
              platform: fs.platform,
              title: fs.title,
              content: fs.content,
              likes: fs.likes,
              reach: fs.reach,
              shares: fs.shares,
              comments: fs.comments,
              clicks: fs.clicks,
              isVideo: fs.isVideo,
              account: fs.account,
              imageUrl: '',
              postType: 'editorial' as const,
              series,
              tags,
              editor,
              createdAt: fs.createdAt ? Timestamp.fromDate(new Date(fs.createdAt)) : serverTimestamp(),
            },
          });
          created++;
        }
      }

      // Write in batches
      for (let i = 0; i < tasks.length; i += CHUNK_SIZE) {
        const batch = writeBatch(db);
        const chunk = tasks.slice(i, i + CHUNK_SIZE);
        for (const task of chunk) {
          if (task.type === 'create') {
            const newDocRef = doc(ref);
            batch.set(newDocRef, task.data);
          } else {
            const docRef = doc(ref, task.id!);
            batch.update(docRef, task.data);
          }
        }
        await batch.commit();
      }

      setSaveResult({ created, updated });
    } catch (e: any) {
      alert(`Save failed: ${e.message}`);
    }
    setIsSaving(false);
  };

  const handleDownloadExcel = async () => {
    if (!jobId || isDownloadingExcel) return;
    setIsDownloadingExcel(true);
    try {
      await downloadExcelReport(jobId);
    } catch (e: any) {
      alert(`Excel download failed: ${e.message}`);
    } finally {
      setIsDownloadingExcel(false);
    }
  };

  // True whenever any async action is in flight — disables all action buttons to prevent double-clicks
  const isAnyBusy = isSaving || isDownloadingExcel;

  const isRunning = jobStatus?.status === 'running';
  const isCompleted = jobStatus?.status === 'completed';
  const progress = jobStatus ? jobStatus.progress : 0;
  const total = jobStatus ? jobStatus.total : 0;
  const eta = isRunning && progress > 0 && total > 0
    ? Math.round(((total - progress) / progress) * (progress * 3))
    : null;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Backend Status */}
      <div className="flex items-center gap-3">
        <div className={`w-2.5 h-2.5 rounded-full ${backendOk === true ? 'bg-green-500' : backendOk === false ? 'bg-red-500 animate-pulse' : 'bg-gray-400'}`} />
        <span className="text-sm text-gray-600">
          {backendOk === true ? 'Backend connected' : backendOk === false ? (
            <span>Backend offline — <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">uvicorn api_server:app --port 8000</code></span>
          ) : 'Checking...'}
        </span>
      </div>

      {/* Input Section */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <div className="flex items-center gap-4">
          <h2 className="text-lg font-bold text-gray-800 flex items-center gap-2">
            <FileText size={20} className="text-indigo-600" /> Generate Report
          </h2>
          <div className="flex bg-gray-100 rounded-lg p-0.5 ml-auto">
            <button
              onClick={() => setInputMode('urls')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${inputMode === 'urls' ? 'bg-white shadow text-indigo-600' : 'text-gray-500'}`}
            >
              <Link2 size={14} /> Paste URLs
            </button>
            <button
              onClick={() => setInputMode('month')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${inputMode === 'month' ? 'bg-white shadow text-indigo-600' : 'text-gray-500'}`}
            >
              <Calendar size={14} /> Monthly Scan
            </button>
          </div>
        </div>

        {inputMode === 'urls' ? (
          <div>
            <label className="text-xs text-gray-500 mb-1 block">One URL per line, optionally followed by end date (YYYY-MM-DD)</label>
            <textarea
              value={urlText}
              onChange={e => setUrlText(e.target.value)}
              placeholder={`https://www.facebook.com/page/videos/123456 2026-02-15\nhttps://www.instagram.com/p/ABC123 2026-02-15`}
              rows={5}
              className="w-full border border-gray-200 rounded-lg p-3 text-sm font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none resize-y"
            />
            <p className="text-xs text-gray-400 mt-1">{parseUrls().length} URL(s) detected</p>
            {accounts.length > 1 && (
              <div className="mt-2">
                <label className="text-xs text-gray-500 mb-1 block">Account</label>
                <select
                  value={selectedUrlAccount}
                  onChange={e => setSelectedUrlAccount(e.target.value)}
                  className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                >
                  {accounts.map(a => (
                    <option key={a.key} value={a.key}>{a.name}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Select month to auto-discover all FB + IG posts</label>
              <input
                type="month"
                value={yearMonth}
                onChange={e => setYearMonth(e.target.value)}
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
              />
            </div>

            {accounts.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs text-gray-500">Select accounts</label>
                  <button
                    onClick={toggleAllAccounts}
                    className="text-xs text-indigo-600 hover:text-indigo-700 font-medium"
                  >
                    {selectedAccounts.length === accounts.length ? 'Deselect All' : 'Select All'}
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {accounts.map(acct => {
                    const isSelected = selectedAccounts.includes(acct.key);
                    return (
                      <button
                        key={acct.key}
                        onClick={() => toggleAccount(acct.key)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors ${
                          isSelected
                            ? 'bg-indigo-100 text-indigo-700 border border-indigo-300'
                            : 'bg-gray-100 text-gray-600 border border-gray-200 hover:bg-gray-200'
                        }`}
                      >
                        {isSelected ? <CheckSquare size={14} /> : <Square size={14} />}
                        {acct.name}
                      </button>
                    );
                  })}
                </div>
                <p className="text-xs text-gray-400 mt-1">{selectedAccounts.length} account(s) selected</p>
              </div>
            )}
          </div>
        )}

        <div className="flex items-center justify-between pt-2">
          <button
            onClick={() => setIncludeLive(!includeLive)}
            className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-800 transition-colors"
          >
            {includeLive ? <ToggleRight size={22} className="text-indigo-600" /> : <ToggleLeft size={22} className="text-gray-400" />}
            Include live counts
            <span className="text-xs text-gray-400">(+2s per post)</span>
          </button>

          <div className="flex gap-2">
            {isRunning && (
              <button
                onClick={handleCancel}
                className="px-4 py-2 bg-red-50 text-red-600 rounded-lg text-sm font-medium hover:bg-red-100 flex items-center gap-2"
              >
                <StopCircle size={16} /> Cancel
              </button>
            )}
            <button
              onClick={handleSubmit}
              disabled={!backendOk || isRunning || isSubmitting}
              className="px-5 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
            >
              {isSubmitting ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              Generate Report
            </button>
          </div>
        </div>
        <p className="text-xs text-gray-400">For best results, generate reports once per day per account.</p>
      </div>

      {/* Progress Section */}
      {jobStatus && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {isRunning && <Loader2 size={16} className="animate-spin text-indigo-600" />}
              {isCompleted && <CheckCircle2 size={16} className="text-green-600" />}
              {jobStatus.status === 'failed' && <AlertTriangle size={16} className="text-red-600" />}
              <span className="text-sm font-medium">
                {isRunning ? 'Processing...' : isCompleted ? 'Completed' : jobStatus.status === 'failed' ? 'Failed' : 'Cancelled'}
              </span>
            </div>
            <span className="text-sm text-gray-500">
              {progress}/{total} posts
              {eta && isRunning && (
                <span className="ml-2 text-gray-400 flex items-center gap-1 inline-flex">
                  <Clock size={12} /> ~{Math.ceil(eta / 60)} min remaining
                </span>
              )}
            </span>
          </div>

          {total > 0 && (
            <div className="w-full bg-gray-100 rounded-full h-2">
              <div
                className={`h-2 rounded-full transition-all duration-500 ${isCompleted ? 'bg-green-500' : 'bg-indigo-600'}`}
                style={{ width: `${total > 0 ? (progress / total) * 100 : 0}%` }}
              />
            </div>
          )}

          {isRunning && jobStatus.current_url && (
            <p className="text-xs text-gray-400 truncate">
              Current: {jobStatus.current_url}
            </p>
          )}

          {jobStatus.status_detail && jobStatus.status !== 'completed' && (
            <p className="text-xs text-gray-500">{jobStatus.status_detail}</p>
          )}

          {jobStatus.live_fetch_paused && (
            <div className="flex items-center gap-2 text-xs text-amber-600 bg-amber-50 px-3 py-1.5 rounded">
              <AlertTriangle size={12} /> Live fetch paused (rate limit) — continuing with API data only
            </div>
          )}

          {jobStatus.errors.length > 0 && (
            <details className="text-xs text-red-600">
              <summary className="cursor-pointer">{jobStatus.errors.length} error(s)</summary>
              <ul className="mt-1 space-y-1 pl-4">
                {jobStatus.errors.map((e, i) => (
                  <li key={i}>{e.url}: {e.error}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {/* Results Table + Actions */}
      {jobStatus?.results && jobStatus.results.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-6 py-4 border-b flex-wrap gap-2">
            <h3 className="font-bold text-gray-800">{jobStatus.results.length} Results</h3>
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={handleSaveToSocialHub}
                disabled={isAnyBusy}
                className="px-4 py-2 bg-indigo-50 text-indigo-700 rounded-lg text-sm font-medium hover:bg-indigo-100 flex items-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                Save to Social Hub
              </button>
              {/* Per-Post CSVs and Combined CSV buttons hidden per user request
              <button
                onClick={handleDownloadAllPerPost}
                disabled={isAnyBusy}
                className="px-4 py-2 bg-amber-50 text-amber-700 rounded-lg text-sm font-medium hover:bg-amber-100 flex items-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <FileDown size={16} /> Per-Post CSVs
              </button>
              <button
                onClick={handleDownloadAll}
                disabled={isAnyBusy}
                className="px-4 py-2 bg-green-50 text-green-700 rounded-lg text-sm font-medium hover:bg-green-100 flex items-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Download size={16} /> Combined CSV
              </button>
              */}
              <button
                onClick={handleDownloadExcel}
                disabled={isAnyBusy}
                className="px-4 py-2 bg-emerald-50 text-emerald-700 rounded-lg text-sm font-medium hover:bg-emerald-100 flex items-center gap-2 transition-colors border border-emerald-200 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isDownloadingExcel ? <Loader2 size={16} className="animate-spin" /> : <FileSpreadsheet size={16} />}
                {isDownloadingExcel ? 'Preparing...' : 'Combined Excel'}
              </button>
              <button
                onClick={() => { setJobId(null); setJobStatus(null); setSaveResult(null); sessionStorage.removeItem(SESSION_KEY); }}
                disabled={isAnyBusy}
                className="px-4 py-2 bg-red-50 text-red-600 rounded-lg text-sm font-medium hover:bg-red-100 flex items-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Clear results and start fresh"
              >
                <X size={16} /> Clear
              </button>
            </div>
          </div>

          {saveResult && (
            <div className="px-6 py-2 bg-green-50 border-b text-xs text-green-700 flex items-center gap-2">
              <CheckCircle2 size={14} />
              Saved: {saveResult.created} created, {saveResult.updated} updated
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left text-xs text-gray-500 uppercase tracking-wider">
                  <th className="px-4 py-3">Platform</th>
                  {jobStatus.results.some(r => r.account) && <th className="px-4 py-3">Account</th>}
                  <th className="px-4 py-3">URL</th>
                  <th className="px-4 py-3 text-right">Views</th>
                  <th className="px-4 py-3 text-right">Reach</th>
                  <th className="px-4 py-3 text-right">Reactions</th>
                  <th className="px-4 py-3 text-right">Comments</th>
                  <th className="px-4 py-3 text-right">Shares</th>
                  <th className="px-4 py-3 text-right">Clicks</th>
                  <th className="px-4 py-3 text-right">Saves</th>
                  {includeLive && <>
                    <th className="px-4 py-3 text-right border-l text-indigo-600">Live React.</th>
                    <th className="px-4 py-3 text-right text-indigo-600">Live Comm.</th>
                    <th className="px-4 py-3 text-right text-indigo-600">Live Shares</th>
                  </>}
                  <th className="px-4 py-3 w-10"></th>
                </tr>
              </thead>
              <tbody>
                {jobStatus.results.map((r, i) => (
                  <tr key={i} className="border-t hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${r.platform === 'Instagram' ? 'bg-pink-100 text-pink-700' : 'bg-blue-100 text-blue-700'}`}>
                        {r.platform === 'Instagram' ? 'IG' : 'FB'}
                      </span>
                    </td>
                    {jobStatus.results.some(res => res.account) && (
                      <td className="px-4 py-3">
                        <span className="text-xs text-gray-600">{r.account || '—'}</span>
                      </td>
                    )}
                    <td className="px-4 py-3 max-w-[200px]">
                      <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:text-indigo-800 truncate block text-xs flex items-center gap-1">
                        {r.url.length > 50 ? r.url.slice(0, 50) + '...' : r.url}
                        <ExternalLink size={10} className="flex-shrink-0" />
                      </a>
                    </td>
                    <td className="px-4 py-3 text-right font-mono">{r.views.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-mono">{r.reach.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-mono">{r.reactions.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-mono">{r.comments.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-mono">{r.shares.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-mono">{r.link_clicks.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-mono">{r.saves.toLocaleString()}</td>
                    {includeLive && <>
                      <td className="px-4 py-3 text-right font-mono border-l text-indigo-600">{r.live_reactions != null ? r.live_reactions.toLocaleString() : '—'}</td>
                      <td className="px-4 py-3 text-right font-mono text-indigo-600">{r.live_comments != null ? r.live_comments.toLocaleString() : '—'}</td>
                      <td className="px-4 py-3 text-right font-mono text-indigo-600">{r.live_shares != null ? r.live_shares.toLocaleString() : '—'}</td>
                    </>}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {/* Per-post CSV icon hidden per user request
                        <button
                          onClick={() => handleDownloadPost(r)}
                          disabled={isAnyBusy}
                          className="text-gray-400 hover:text-indigo-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          title="Download per-post CSV"
                        >
                          <FileDown size={14} />
                        </button>
                        */}
                        <button
                          onClick={handleDownloadExcel}
                          disabled={isAnyBusy}
                          className="flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-50 text-green-700 border border-green-200 hover:bg-green-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          title="Download combined Excel report (.xlsx)"
                        >
                          {isDownloadingExcel ? <Loader2 size={12} className="animate-spin" /> : <FileSpreadsheet size={12} />}
                          <span>{isDownloadingExcel ? '...' : 'Excel'}</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
