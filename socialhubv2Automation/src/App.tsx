import { Suspense, lazy, useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { 
  signInAnonymously, 
  onAuthStateChanged
} from 'firebase/auth';
import { 
  collection, 
  updateDoc, 
  deleteDoc, 
  doc, 
  onSnapshot, 
  serverTimestamp, 
  Timestamp,
  getDocs,
  writeBatch,
    addDoc 
  } from 'firebase/firestore';

import { auth, db, appId } from './config/firebase';
import type { Post, ProgressState, PostType, EditorName } from './types';
import useDebounce from './hooks/Debounce';
import { parseCSV } from './utils/helpers';
import PostCard from './components/PostCard';
import PostModal from './components/PostModal';
import ProgressModal from './components/ProgressModal';
import { EDITORS } from './constants/data';
import { Lock, Unlock, Tag, X, Plus, BarChart3, Users, UserCircle, Globe, PlayCircle, Image as ImageIcon, Calendar as CalendarIcon, Heart, FileUp, Trash2, PanelLeftOpen, PanelLeftClose, Search, ArrowUpDown, Filter, AlertCircle, CheckCircle2, FolderEdit, UserCog, Copy, FileBarChart, ArrowLeft } from 'lucide-react';

const DashboardView = lazy(() => import('./components/DashboardView'));
const ReportView = lazy(() => import('./components/ReportView'));



// --- Main App Export ---
export default function App() {
  const [user, setUser] = useState<any>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // Progress State
  const [progress, setProgress] = useState<ProgressState>({ isActive: false, message: '', current: 0, total: 0 });
  const abortRef = useRef(false);

  // App Lock State
  const [isLocked, setIsLocked] = useState(() => !localStorage.getItem('app_unlocked'));
  const [passwordInput, setPasswordInput] = useState('');

  // UI State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true); 
  const [isBulkEditSeriesOpen, setIsBulkEditSeriesOpen] = useState(false); 
  const [isBulkEditEditorOpen, setIsBulkEditEditorOpen] = useState(false); 
  const [editingPost, setEditingPost] = useState<Post | null>(null);
  const [currentView, setCurrentView] = useState<'posts' | 'dashboard' | 'reports'>('posts');

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const debouncedSearchQuery = useDebounce(searchQuery, 300);
  const [sortBy, setSortBy] = useState<'date' | 'likes' | 'shares' | 'likes_asc' | 'shares_asc'>('date'); 
  const [selectedPostType, setSelectedPostType] = useState<'all' | 'ad' | 'editorial'>('all');
  const [selectedSeries, setSelectedSeries] = useState<string>('All');
  const [selectedEditor, setSelectedEditor] = useState<string>('All');
  const [selectedMediaType, setSelectedMediaType] = useState<'all' | 'video' | 'image'>('all'); 
  const [selectedAccount, setSelectedAccount] = useState<string>('all'); 
  const [selectedPlatform, setSelectedPlatform] = useState<string>('all'); 
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [minLikes, setMinLikes] = useState<number>(0);
  const [maxLikes, setMaxLikes] = useState<number>(99999); 

  const [selectedPostIds, setSelectedPostIds] = useState<Set<string>>(new Set());
  const [lastSelectedId, setLastSelectedId] = useState<string | null>(null);
  const filteredPostsRef = useRef<Post[]>([]);

  // --- Auth & Data Loading ---
  useEffect(() => {
    const initAuth = async () => { try { await signInAnonymously(auth); } catch (e: any) { setErrorMsg("登入失敗"); } };
    initAuth();
    const unsubscribe = onAuthStateChanged(auth, setUser);
    return () => unsubscribe();
  }, []);

  useEffect(() => {
    if (!user || !appId) return;
    const q = collection(db, 'artifacts', appId, 'public', 'data', 'social_posts');
    const unsubscribe = onSnapshot(q, (snapshot) => {
      const loadedPosts = snapshot.docs.map(doc => {
        const data = doc.data();
        let postType: PostType = data.postType;
        let series = data.series || data.category; 
        if (!postType) { if (series === '廣告帖文') { postType = 'ad'; series = '📂 待分類'; } else { postType = 'editorial'; } }
        return { id: doc.id, ...data, postType, series } as Post;
      });
      loadedPosts.sort((a, b) => { 
          const dateA = a.createdAt?.seconds || 0; 
          const dateB = b.createdAt?.seconds || 0; 
          return dateB - dateA; 
      });
      setPosts(loadedPosts);
      setLoading(false);
    }, () => { setLoading(false); });
    return () => unsubscribe();
  }, [user]);

  // --- Computed Options ---
  const seriesList = useMemo(() => {
    const counts: {[key: string]: number} = {};
    const seriesSet = new Set<string>();
    posts.forEach(p => { const s = p.series || '📂 待分類'; counts[s] = (counts[s] || 0) + 1; seriesSet.add(s); });
    return ['All', ...Array.from(seriesSet).sort()].map(name => ({ name, label: name, count: name === 'All' ? posts.length : (counts[name] || 0) }));
  }, [posts]);

  const typeCounts = useMemo(() => {
    const counts = { all: posts.length, ad: 0, editorial: 0 };
    posts.forEach(p => { if (p.postType === 'ad') counts.ad++; if (p.postType === 'editorial') counts.editorial++; });
    return counts;
  }, [posts]);

  // --- Filtering Logic ---
  const filteredAndSortedPosts = useMemo(() => {
    const query = debouncedSearchQuery.toLowerCase();
    const filtered = posts.filter(post => {
      const matchesSearch = query === '' || post.title.toLowerCase().includes(query) || post.content.toLowerCase().includes(query) || post.tags.some(tag => tag.toLowerCase().includes(query));
      if (!matchesSearch) return false;
      if (selectedPostType !== 'all' && post.postType !== selectedPostType) return false;
      if (selectedSeries !== 'All' && post.series !== selectedSeries) return false;
      if (selectedEditor !== 'All') { if (selectedEditor === 'Unassigned') { if (post.editor) return false; } else { if (post.editor !== selectedEditor) return false; } }
      if (selectedAccount !== 'all' && post.account !== selectedAccount && !(selectedAccount === 'all' && !post.account)) return false; 
      if (selectedAccount !== 'all' && post.account && post.account !== selectedAccount) return false;
      if (selectedPlatform !== 'all' && post.platform !== selectedPlatform) return false;
      const likes = post.likes || 0;
      if (likes < minLikes || likes > maxLikes) return false;
      let matchesMedia = true;
      if (selectedMediaType === 'video') matchesMedia = !!post.isVideo;
      if (selectedMediaType === 'image') matchesMedia = !post.isVideo;
      if (!matchesMedia) return false;
      if (startDate || endDate) {
          const postDate = post.createdAt?.toDate ? post.createdAt.toDate() : new Date(post.createdAt);
          if (startDate) { const start = new Date(startDate); start.setHours(0, 0, 0, 0); if (postDate < start) return false; }
          if (endDate) { const end = new Date(endDate); end.setHours(23, 59, 59, 999); if (postDate > end) return false; }
      }
      return true;
    });
    return filtered.sort((a, b) => {
        if (sortBy === 'likes') return (b.likes || 0) - (a.likes || 0);
        else if (sortBy === 'likes_asc') return (a.likes || 0) - (b.likes || 0);
        else if (sortBy === 'shares') return (b.shares || 0) - (a.shares || 0);
        else if (sortBy === 'shares_asc') return (a.shares || 0) - (b.shares || 0);
        else { const dateA = a.createdAt?.seconds || (a.createdAt instanceof Date ? a.createdAt.getTime()/1000 : 0); const dateB = b.createdAt?.seconds || (b.createdAt instanceof Date ? b.createdAt.getTime()/1000 : 0); return dateB - dateA; }
    });
  }, [posts, debouncedSearchQuery, selectedPostType, selectedSeries, selectedEditor, selectedMediaType, selectedAccount, selectedPlatform, minLikes, maxLikes, startDate, endDate, sortBy]);

  useEffect(() => { filteredPostsRef.current = filteredAndSortedPosts; }, [filteredAndSortedPosts]);

  // --- Handlers (Action Logic) ---
  const handleUnlock = (e: React.FormEvent) => { e.preventDefault(); if (passwordInput === '8888') { localStorage.setItem('app_unlocked', 'true'); setIsLocked(false); } else { alert('密碼錯誤！'); } };
  const handleCancelOperation = () => { abortRef.current = true; setProgress({ isActive: false, message: '', current: 0, total: 0 }); alert("操作已強制取消。"); };
  
  // 🔥 真實 Firebase 儲存邏輯 (解決 unused addDoc, updateDoc)
  const handleSave = async (data: any) => { 
      if (!user) return; 
      const ref = collection(db, 'artifacts', appId, 'public', 'data', 'social_posts'); 
      try { 
          if (editingPost) await updateDoc(doc(ref, editingPost.id), data); 
          else await addDoc(ref, { ...data, createdAt: serverTimestamp() }); 
          setIsModalOpen(false); setEditingPost(null); 
      } catch (e) { alert('儲存失敗'); } 
  };

  // 🔥 真實 Firebase 刪除邏輯 (解決 unused deleteDoc)
  const handleDelete = useCallback(async (id: string) => { 
    if (confirm('確定刪除？')) await deleteDoc(doc(db, 'artifacts', appId, 'public', 'data', 'social_posts', id)); 
  }, [appId]);
  
  const handleClearData = async () => {
    if (!user) return;
    const pwd = prompt("請輸入管理員密碼 (8888) 以清空資料庫：");
    if (pwd !== '8888') { alert("密碼錯誤！"); return; }
    if (!confirm('⚠️ 嚴重警告：即將刪除「所有」貼文資料！')) return;
    setProgress({ isActive: true, message: '正在讀取資料...', current: 0, total: 0 });
    abortRef.current = false;
    try {
      const ref = collection(db, 'artifacts', appId, 'public', 'data', 'social_posts');
      const snapshot = await getDocs(ref); // 解決 unused getDocs
      if (snapshot.empty) { alert('資料庫已經是空的了。'); setProgress({ isActive: false, message: '', current: 0, total: 0 }); return; }
      const total = snapshot.docs.length;
      setProgress({ isActive: true, message: '正在刪除資料...', current: 0, total });
      const CHUNK_SIZE = 50; const chunks = []; for (let i = 0; i < total; i += CHUNK_SIZE) chunks.push(snapshot.docs.slice(i, i + CHUNK_SIZE));
      let deletedCount = 0;
      for (const chunk of chunks) { if (abortRef.current) throw new Error("Operation cancelled"); const batch = writeBatch(db); chunk.forEach(doc => batch.delete(doc.ref)); await batch.commit(); deletedCount += chunk.length; setProgress(prev => ({ ...prev, current: deletedCount })); await new Promise(resolve => setTimeout(resolve, 100)); }
      alert(`已成功清除 ${deletedCount} 筆資料。`);
    } catch (err: any) { if (err.message !== "Operation cancelled") { console.error("Clear error:", err); alert(`清除失敗: ${err.message}`); } } finally { setProgress({ isActive: false, message: '', current: 0, total: 0 }); }
  };

  const handleBulkDelete = async () => {
      if (!user) return;
      const count = selectedPostIds.size;
      if (count === 0) return;
      if (!confirm(`⚠️ 確定要刪除選取的 ${count} 筆貼文嗎？`)) return;
      setProgress({ isActive: true, message: '正在刪除...', current: 0, total: count });
      abortRef.current = false;
      try {
          const ids = Array.from(selectedPostIds);
          const CHUNK_SIZE = 50; 
          let deletedCount = 0;
          for (let i = 0; i < ids.length; i += CHUNK_SIZE) {
              if (abortRef.current) break;
              const batch = writeBatch(db);
              const chunk = ids.slice(i, i + CHUNK_SIZE);
              chunk.forEach(id => { const docRef = doc(db, 'artifacts', appId, 'public', 'data', 'social_posts', id); batch.delete(docRef); });
              await batch.commit();
              deletedCount += chunk.length;
              setProgress(prev => ({ ...prev, current: deletedCount }));
              await new Promise(resolve => setTimeout(resolve, 100));
          }
          if (!abortRef.current) { alert(`已成功刪除 ${deletedCount} 筆貼文。`); setSelectedPostIds(new Set()); setLastSelectedId(null); }
      } catch (err: any) { if (!abortRef.current) alert(`刪除失敗: ${err.message}`); } finally { setProgress({ isActive: false, message: '', current: 0, total: 0 }); }
  };

  const handleBulkEditSeries = async (newSeries: string) => {
    if (!user) return;
    const count = selectedPostIds.size;
    if (count === 0) return;
    if (!confirm(`確定要將選取的 ${count} 筆貼文修改為系列「${newSeries}」嗎？`)) return;
    setProgress({ isActive: true, message: '正在更新...', current: 0, total: count });
    abortRef.current = false;
    try {
        const ids = Array.from(selectedPostIds);
        const CHUNK_SIZE = 50;
        let updatedCount = 0;
        for (let i = 0; i < ids.length; i += CHUNK_SIZE) {
            if (abortRef.current) break;
            const batch = writeBatch(db);
            const chunk = ids.slice(i, i + CHUNK_SIZE);
            chunk.forEach(id => { const docRef = doc(db, 'artifacts', appId, 'public', 'data', 'social_posts', id); batch.update(docRef, { series: newSeries }); });
            await batch.commit();
            updatedCount += chunk.length;
            setProgress(prev => ({ ...prev, current: updatedCount }));
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        if (!abortRef.current) { alert(`更新完成！`); setIsBulkEditSeriesOpen(false); setSelectedPostIds(new Set()); setLastSelectedId(null); }
    } catch (err: any) { if (!abortRef.current) alert(`更新失敗: ${err.message}`); } finally { setProgress({ isActive: false, message: '', current: 0, total: 0 }); }
  };

  const handleBulkEditEditor = async (newEditor: string) => {
    if (!user) return;
    const count = selectedPostIds.size;
    if (count === 0) return;
    if (!confirm(`確定要將選取的 ${count} 筆貼文分配給小編「${newEditor}」嗎？`)) return;
    setProgress({ isActive: true, message: '正在更新...', current: 0, total: count });
    abortRef.current = false;
    try {
        const ids = Array.from(selectedPostIds);
        const CHUNK_SIZE = 50;
        let updatedCount = 0;
        for (let i = 0; i < ids.length; i += CHUNK_SIZE) {
            if (abortRef.current) break;
            const batch = writeBatch(db);
            const chunk = ids.slice(i, i + CHUNK_SIZE);
            chunk.forEach(id => { const docRef = doc(db, 'artifacts', appId, 'public', 'data', 'social_posts', id); batch.update(docRef, { editor: newEditor === 'unassigned' ? null : newEditor }); });
            await batch.commit();
            updatedCount += chunk.length;
            setProgress(prev => ({ ...prev, current: updatedCount }));
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        if (!abortRef.current) { alert(`更新完成！`); setIsBulkEditEditorOpen(false); setSelectedPostIds(new Set()); setLastSelectedId(null); }
    } catch (err: any) { if (!abortRef.current) alert(`更新失敗: ${err.message}`); } finally { setProgress({ isActive: false, message: '', current: 0, total: 0 }); }
  };

  const handleUploadClick = () => { const pwd = prompt("請輸入管理員密碼 (8888) 以匯入資料："); if (pwd === '8888') fileInputRef.current?.click(); else alert("密碼錯誤！"); };

  // 🔥 Smart Merge + Firebase Write Logic
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file || !user) return;
      if (!auth.currentUser) { try { await signInAnonymously(auth); } catch(e) { alert("無法登入 Firebase。"); if(fileInputRef.current) fileInputRef.current.value = ''; return; } }
      const reader = new FileReader();
      reader.onload = async (ev) => {
          const text = ev.target?.result as string;
          const rows: any[] = parseCSV(text || '');
          if (!rows || rows.length === 0) { alert('CSV 內容為空'); return; }
              // helper: normalize URL and fallback keys
              const normalize = (u: string) => (u || '').toString().trim().toLowerCase().replace(/\/*$/, '');

              // 1. Build Map of existing URLs (Smart Merge 關鍵)
              const urlToIdMap = new Map<string, string>();
              posts.forEach(p => {
                const raw = (p.postUrl || '').toString();
                const n = normalize(raw);
                if (n) urlToIdMap.set(n, p.id);
                // also index fallback key by title+account to help matching when URL missing
                const titleKey = (p.title || '').toString().trim().toLowerCase();
                const accKey = (p.account || '').toString().trim().toLowerCase();
                if (titleKey || accKey) urlToIdMap.set(`${titleKey}||${accKey}`, p.id);
              });
          
          const updates: { id: string, data: any }[] = [];
          const creates: any[] = [];
          
            const seenUrls = new Set<string>();
            const seenFallback = new Set<string>();

            rows.forEach(p => {
             const rawUrl = (p.postUrl || p.post_url || p.link || '').toString().trim();
             const normUrl = normalize(rawUrl);
             // try direct url match first
             let existingId = normUrl ? urlToIdMap.get(normUrl) : undefined;

             // if no url match, try fallback title+account
             if (!existingId) {
               const titleKey = (p.title || p.title_text || '').toString().trim().toLowerCase();
               const accKey = (p.account || '').toString().trim().toLowerCase();
               const fallbackKey = `${titleKey}||${accKey}`;
               existingId = urlToIdMap.get(fallbackKey);
             }

             if (existingId) {
               const existingPost = posts.find(post => post.id === existingId);
               if (!existingPost) return; // shouldn't happen
               const updateData: any = {
                 content: p.content || p.message || existingPost.content || '',
                 updatedAt: serverTimestamp(),
               };
               if (p.likes !== undefined) updateData.likes = Number(p.likes);
               if (p.shares !== undefined) updateData.shares = Number(p.shares);
               if (p.comments !== undefined) updateData.comments = Number(p.comments);
               if (p.reach !== undefined) updateData.reach = Number(p.reach);
               if (p.follows !== undefined) updateData.follows = Number(p.follows);
               if (p.clicks !== undefined) updateData.clicks = Number(p.clicks);
               if (p.fans !== undefined) updateData.fans = Number(p.fans);
               if (p.series && p.series.trim()) {
                 updateData.series = p.series;
               } else if (existingPost.series) {
                 updateData.series = existingPost.series;
               }
               if (p.editor && p.editor.trim()) {
                 updateData.editor = p.editor;
               } else if (existingPost.editor) {
                 updateData.editor = existingPost.editor;
               }
               if (p.isVideo !== undefined) {
                 updateData.isVideo = p.isVideo;
               } else if (existingPost.isVideo !== undefined) {
                 updateData.isVideo = existingPost.isVideo;
               }
               // Always update platform and channel if provided
               if (p.platform) updateData.platform = p.platform;
               if (p.channel) updateData.channel = p.channel;
               updates.push({ id: existingId, data: updateData });
             } else {
               // dedupe rows in CSV itself
               if (normUrl) {
                 if (seenUrls.has(normUrl)) return; // skip duplicate row
                 seenUrls.add(normUrl);
               } else {
                 const titleKey = (p.title || '').toString().trim().toLowerCase();
                 const accKey = (p.account || '').toString().trim().toLowerCase();
                 const fallback = `${titleKey}||${accKey}`;
                 if (seenFallback.has(fallback)) return; // skip duplicate row
                 seenFallback.add(fallback);
               }
               const data = { ...p, createdAt: Timestamp.fromDate(p.createdAt), postUrl: rawUrl || '', plannedTime: p.plannedTime || null, editor: p.editor || null };
               creates.push({ type: 'create', data });
             }
            });

          if (updates.length === 0 && creates.length === 0) { alert('沒有資料需更新。'); if(fileInputRef.current) fileInputRef.current.value = ''; return; }
          
          if(confirm(`新增：${creates.length} 筆\n更新：${updates.length} 筆\n確定執行？`)) {
             const totalOps = creates.length + updates.length;
             setProgress({ isActive: true, message: '處理中...', current: 0, total: totalOps });
             abortRef.current = false;
             const ref = collection(db, 'artifacts', appId, 'public', 'data', 'social_posts');
             const CHUNK_SIZE = 20; let processedCount = 0;
             
             // Merge lists
             const allTasks = [
                 ...creates,  // Already has correct structure from line 364
                 ...updates.map(u => ({ type: 'update', id: u.id, data: u.data }))
             ];

             try {
                for (let i = 0; i < allTasks.length; i += CHUNK_SIZE) {
                    if (abortRef.current) break;
                    const batch = writeBatch(db);
                    const chunk = allTasks.slice(i, i + CHUNK_SIZE);
                    chunk.forEach((task: any) => {
                        if (task.type === 'create') { const newDocRef = doc(ref); batch.set(newDocRef, task.data); } 
                        else { const docRef = doc(ref, task.id); batch.update(docRef, task.data); }
                    });
                    await batch.commit();
                    processedCount += chunk.length;
                    setProgress(prev => ({ ...prev, current: processedCount }));
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                if (!abortRef.current) alert('完成！');
             } catch (err: any) { if (!abortRef.current) alert(`中斷: ${err.message}`); } finally { setProgress({ isActive: false, message: '', current: 0, total: 0 }); }
         }
      };
      reader.readAsText(file);
      if(fileInputRef.current) fileInputRef.current.value = '';
  };
  
  const handleEditClick = useCallback((post: Post) => { setEditingPost(post); setIsModalOpen(true); }, []);
  const handleToggleTypeClick = useCallback(async (post: Post) => { if(!user) return; if (post.postType === 'ad') { if (!confirm('取消廣告標記？')) return; } const newType = post.postType === 'ad' ? 'editorial' : 'ad'; await updateDoc(doc(db, 'artifacts', appId, 'public', 'data', 'social_posts', post.id), { postType: newType }); }, [user, appId, db]);
  const handleToggleEditorClick = useCallback(async (post: Post) => { if(!user) return; let nextEditor: EditorName = null; if (!post.editor) nextEditor = 'Kiki'; else if (post.editor === 'Kiki') nextEditor = 'Chloe'; else if (post.editor === 'Chloe') nextEditor = 'Kathy'; else if (post.editor === 'Kathy') nextEditor = 'Kassandra'; else if (post.editor === 'Kassandra') nextEditor = 'Rachel'; else if (post.editor === 'Rachel') nextEditor = 'Loris'; else if (post.editor === 'Loris') nextEditor = null; await updateDoc(doc(db, 'artifacts', appId, 'public', 'data', 'social_posts', post.id), { editor: nextEditor }); }, [user, appId, db]);
  const handleSelection = useCallback((id: string, shiftKey: boolean) => { const currentList = filteredPostsRef.current; const currentPostIndex = currentList.findIndex(p => p.id === id); if (currentPostIndex === -1) return; setSelectedPostIds(prev => { let newSelected = new Set(prev); if (shiftKey && lastSelectedId) { const lastIndex = currentList.findIndex(p => p.id === lastSelectedId); if (lastIndex !== -1) { const start = Math.min(lastIndex, currentPostIndex); const end = Math.max(lastIndex, currentPostIndex); for (let i = start; i <= end; i++) newSelected.add(currentList[i].id); } else { if (newSelected.has(id)) newSelected.delete(id); else newSelected.add(id); setLastSelectedId(id); } } else { if (newSelected.has(id)) { newSelected.delete(id); setLastSelectedId(id); } else { newSelected.add(id); setLastSelectedId(id); } } return newSelected; }); setLastSelectedId(id); }, [lastSelectedId]);
  const handleSelectAll = () => { if (selectedPostIds.size === filteredAndSortedPosts.length && filteredAndSortedPosts.length > 0) setSelectedPostIds(new Set()); else setSelectedPostIds(new Set(filteredAndSortedPosts.map(p => p.id))); };
  const handleCopySelected = () => { const selected = posts.filter(p => selectedPostIds.has(p.id)); const text = selected.map(p => `【${p.account}】${p.title} ${p.isVideo ? '(Video)' : ''}\n❤️ Likes: ${p.likes} | 🔗 ${p.postUrl}`).join('\n\n'); const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); alert(`已複製 ${selected.length} 筆`); setSelectedPostIds(new Set()); setLastSelectedId(null); };
  
  if (isLocked) { return ( <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4"> <div className="bg-white rounded-xl shadow-2xl p-8 w-full max-w-sm text-center"> <div className="bg-indigo-100 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4"><Lock size={32} className="text-indigo-600" /></div> <h1 className="text-2xl font-bold text-gray-800 mb-2">Sales Hub</h1> <p className="text-gray-500 mb-6 text-sm">請輸入存取密碼</p> <form onSubmit={handleUnlock} className="space-y-4"> <input type="password" placeholder="密碼" value={passwordInput} onChange={(e) => setPasswordInput(e.target.value)} className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all text-center text-lg tracking-widest" autoFocus /> <button type="submit" className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 rounded-lg transition-colors flex items-center justify-center gap-2"><Unlock size={18} /> 解鎖進入</button> </form> </div> </div> ); }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col md:flex-row text-slate-800 font-sans pb-20 md:pb-0">
      <ProgressModal progress={progress} onCancel={handleCancelOperation} />
      {isBulkEditSeriesOpen && ( <div className="fixed inset-0 bg-black/60 z-[70] flex items-center justify-center p-4 backdrop-blur-sm"> <div className="bg-white rounded-xl w-full max-w-sm p-6 shadow-2xl animate-fade-in"> <h3 className="font-bold text-lg mb-4">批量修改系列 ({selectedPostIds.size} 筆)</h3> <div className="space-y-2 max-h-60 overflow-y-auto custom-scrollbar border rounded p-2 mb-4"> {seriesList.filter(s => s.name !== 'All').map(s => ( <button key={s.name} onClick={() => handleBulkEditSeries(s.name)} className="w-full text-left px-3 py-2 hover:bg-indigo-50 rounded text-sm transition-colors text-gray-700 hover:text-indigo-700 flex justify-between"> <span>{s.label}</span><span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded-full">{s.count}</span> </button> ))} </div> <button onClick={() => setIsBulkEditSeriesOpen(false)} className="w-full py-2 bg-gray-100 rounded text-gray-600 font-medium">取消</button> </div> </div> )}
      {isBulkEditEditorOpen && ( <div className="fixed inset-0 bg-black/60 z-[70] flex items-center justify-center p-4 backdrop-blur-sm"> <div className="bg-white rounded-xl w-full max-w-sm p-6 shadow-2xl animate-fade-in"> <h3 className="font-bold text-lg mb-4">批量分配小編 ({selectedPostIds.size} 筆)</h3> <div className="space-y-2 mb-4"> {EDITORS.map(editor => ( <button key={editor.name} onClick={() => handleBulkEditEditor(editor.name!)} className={`w-full text-left px-4 py-3 rounded-lg text-sm font-bold transition-colors flex items-center justify-between ${editor.color} hover:opacity-80`}> <span>{editor.name}</span><span className="text-xs opacity-70">({editor.code})</span> </button> ))} <button onClick={() => handleBulkEditEditor('unassigned')} className="w-full text-left px-4 py-3 rounded-lg text-sm font-bold bg-gray-100 text-gray-600 hover:bg-gray-200"> 未分配 (Clear) </button> </div> <button onClick={() => setIsBulkEditEditorOpen(false)} className="w-full py-2 bg-gray-100 rounded text-gray-600 font-medium">取消</button> </div> </div> )}

      <aside className={`fixed inset-y-0 left-0 z-50 w-72 bg-white border-r border-gray-200 flex flex-col h-screen transform transition-transform duration-300 ${isSidebarOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'} md:translate-x-0 md:static`}>
        <div className="p-6 border-b flex justify-between items-center"> <h1 className="text-xl font-bold text-indigo-600 flex items-center gap-2"><Tag className="w-6 h-6"/> Social Hub</h1> <div className="flex gap-2 md:hidden"><button onClick={() => setIsSidebarOpen(false)}><X /></button></div> </div>
        <div className="p-4 space-y-6 overflow-y-auto flex-1 custom-scrollbar">
             <button onClick={() => { setEditingPost(null); setIsModalOpen(true); }} className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 font-medium transition-colors shadow-sm"><Plus size={18} /> 新增貼文素材</button>
             <button onClick={() => { setCurrentView(currentView === 'dashboard' ? 'posts' : 'dashboard'); if (window.innerWidth < 768) setIsSidebarOpen(false); }} className={`w-full mt-2 border text-indigo-600 hover:bg-indigo-50 py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 font-medium transition-colors shadow-sm ${currentView === 'dashboard' ? 'bg-indigo-50 border-indigo-200 ring-2 ring-indigo-100' : 'bg-white border-indigo-200'}`}>{currentView === 'dashboard' ? <><ArrowLeft size={18} /> 返回列表</> : <><BarChart3 size={18} /> 數據分析看板</>}</button>
             <button onClick={() => { setCurrentView(currentView === 'reports' ? 'posts' : 'reports'); if (window.innerWidth < 768) setIsSidebarOpen(false); }} className={`w-full mt-2 border text-indigo-600 hover:bg-indigo-50 py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 font-medium transition-colors shadow-sm ${currentView === 'reports' ? 'bg-indigo-50 border-indigo-200 ring-2 ring-indigo-100' : 'bg-white border-indigo-200'}`}>{currentView === 'reports' ? <><ArrowLeft size={18} /> 返回列表</> : <><FileBarChart size={18} /> Meta Performance Metrics Report</>}</button>
             {/* Account Filter */}
             <div><label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1"><Users size={12}/> 帳號篩選</label>{['all', 'Pestyle', 'Play Eat Easy'].map(acc => (<button key={acc} onClick={() => setSelectedAccount(acc)} className={`w-full text-left px-3 py-2 rounded-md text-sm ${selectedAccount === acc ? 'bg-indigo-50 text-indigo-700 font-bold' : 'hover:bg-gray-100'}`}>{acc === 'all' ? '全部帳號' : acc}</button>))}</div>
             {/* Editor Filter */}
             <div><label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1"><UserCircle size={12}/> 小編篩選</label><div className="flex flex-wrap gap-1"><button onClick={() => setSelectedEditor('All')} className={`px-2 py-1 rounded text-xs ${selectedEditor === 'All' ? 'bg-indigo-50 text-indigo-700 font-bold' : 'bg-gray-100 text-gray-600'}`}>All</button>{EDITORS.map(ed => (<button key={ed.name} onClick={() => setSelectedEditor(ed.name!)} className={`px-2 py-1 rounded text-xs ${selectedEditor === ed.name ? 'bg-indigo-50 text-indigo-700 font-bold' : 'bg-gray-100 text-gray-600'}`}>{ed.code}</button>))}<button onClick={() => setSelectedEditor('Unassigned')} className={`px-2 py-1 rounded text-xs ${selectedEditor === 'Unassigned' ? 'bg-indigo-50 text-indigo-700 font-bold' : 'bg-gray-100 text-gray-600'}`}>NA</button></div></div>
             {/* Platform Filter */}
             <div><label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1"><Globe size={12}/> 平台</label><div className="flex gap-2 bg-gray-100 p-1 rounded"><button onClick={() => setSelectedPlatform('all')} className={`flex-1 text-xs py-1 rounded ${selectedPlatform === 'all' ? 'bg-white shadow text-indigo-600' : 'text-gray-500'}`}>全部</button><button onClick={() => setSelectedPlatform('instagram')} className={`flex-1 text-xs py-1 rounded ${selectedPlatform === 'instagram' ? 'bg-white shadow text-pink-600' : 'text-gray-500'}`}>IG</button><button onClick={() => setSelectedPlatform('facebook')} className={`flex-1 text-xs py-1 rounded ${selectedPlatform === 'facebook' ? 'bg-white shadow text-blue-600' : 'text-gray-500'}`}>FB</button></div></div>
             {/* Media Type Filter */}
             <div><label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1"><PlayCircle size={12}/> 媒體類型</label><div className="flex gap-2 bg-gray-100 p-1 rounded"><button onClick={() => setSelectedMediaType('all')} className={`flex-1 text-xs py-1 rounded ${selectedMediaType === 'all' ? 'bg-white shadow text-indigo-600' : 'text-gray-500'}`}>全部</button><button onClick={() => setSelectedMediaType('video')} className={`flex-1 text-xs py-1 rounded flex items-center justify-center gap-1 ${selectedMediaType === 'video' ? 'bg-white shadow text-indigo-600' : 'text-gray-500'}`}><PlayCircle size={10}/> 影片</button><button onClick={() => setSelectedMediaType('image')} className={`flex-1 text-xs py-1 rounded flex items-center justify-center gap-1 ${selectedMediaType === 'image' ? 'bg-white shadow text-indigo-600' : 'text-gray-500'}`}><ImageIcon size={10}/> 圖片</button></div></div>
             {/* Date Range Filter */}
             <div className="bg-slate-50 p-3 rounded-lg border border-slate-100"><label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1"><CalendarIcon size={12} /> 日期範圍</label><div className="flex flex-col gap-2"><div className="flex items-center gap-2"><span className="text-[10px] text-gray-500 w-6">From</span><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full text-xs border border-gray-200 rounded px-2 py-1"/></div><div className="flex items-center gap-2"><span className="text-[10px] text-gray-500 w-6">To</span><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-full text-xs border border-gray-200 rounded px-2 py-1"/></div></div></div>
             {/* Type Filter */}
             <div><label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 block">類型</label><div className="flex gap-2 bg-gray-100 p-1 rounded">{['all', 'ad', 'editorial'].map(t => { const typeKey = t as 'all' | 'ad' | 'editorial'; const label = t === 'all' ? '全部' : t === 'ad' ? '廣告' : '編輯'; return (<button key={t} onClick={() => setSelectedPostType(typeKey)} className={`flex-1 text-xs py-1 rounded capitalize ${selectedPostType === t ? 'bg-white shadow text-indigo-600 font-bold' : 'text-gray-500'}`}>{label} <span className="text-[10px] opacity-70">({typeCounts[typeKey]})</span></button>);})}</div></div>
             {/* Series Classification */}
             <div><label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 block">系列分類 (Series)</label><div className="space-y-1 max-h-40 overflow-y-auto pr-1 custom-scrollbar">{seriesList.map(s => (<button key={s.name} onClick={() => setSelectedSeries(s.name)} className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between group ${selectedSeries === s.name ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-gray-600 hover:bg-gray-100'}`}><span className="truncate">{s.label}</span><span className="text-[10px] bg-gray-200 text-gray-600 px-1.5 py-0.5 rounded-full">{s.count}</span></button>))}</div></div>
             {/* Likes Range Filter */}
             <div><label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1"><Heart size={12}/> Likes 範圍</label><div className="flex gap-2 items-center"><input type="number" value={minLikes} onChange={(e) => setMinLikes(Number(e.target.value))} placeholder="Min" className="w-full border border-gray-200 rounded px-2 py-1 text-xs"/><span className="text-gray-400">-</span><input type="number" value={maxLikes} onChange={(e) => setMaxLikes(Number(e.target.value))} placeholder="Max" className="w-full border border-gray-200 rounded px-2 py-1 text-xs"/></div></div>
             <div className="pt-4 border-t space-y-2"><button onClick={handleUploadClick} className="w-full py-2 bg-indigo-50 text-indigo-700 rounded text-sm flex justify-center gap-2"><FileUp size={16}/> 匯入 CSV</button><input type="file" ref={fileInputRef} onChange={handleFileUpload} accept=".csv" className="hidden" /><button onClick={handleClearData} className="w-full py-2 border border-red-200 text-red-500 rounded text-sm flex justify-center gap-2"><Trash2 size={16}/> 清空</button></div>
        </div>
      </aside>

      {isSidebarOpen && <div className="fixed inset-0 bg-black/50 z-40 md:hidden animate-fade-in" onClick={() => setIsSidebarOpen(false)} />}

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden relative">
        <header className="bg-white border-b px-6 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 md:hidden"><button onClick={() => setIsSidebarOpen(true)} className="p-2 -ml-2 text-gray-600 hover:bg-gray-100 rounded-lg"><PanelLeftOpen size={24} /></button><button onClick={() => setIsSidebarOpen(!isSidebarOpen)} className="hidden md:block p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">{isSidebarOpen ? <PanelLeftClose size={20} /> : <PanelLeftOpen size={20} />}</button></div>
          <div className="relative flex-1 max-w-2xl"><div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"><Search size={18} /></div><input type="text" placeholder="搜尋關鍵字..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="w-full pl-10 pr-4 py-2.5 bg-gray-100 border-none rounded-lg focus:bg-white focus:ring-2 focus:ring-indigo-500 transition-all text-sm"/></div>
          <div className="flex gap-2">
             <div className="relative"><select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)} className="bg-gray-100 border-none rounded-lg py-2 pl-3 pr-8 text-sm font-medium appearance-none cursor-pointer"><option value="date">最新發佈</option><option value="likes">最多 Likes</option><option value="shares">最多 Shares</option><option value="likes_asc">最少 Likes</option><option value="shares_asc">最少 Shares</option></select><ArrowUpDown size={14} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" /></div>
             <button onClick={() => setIsSidebarOpen(true)} className="md:hidden p-2 bg-gray-100 rounded-lg"><Filter size={18}/></button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-6 bg-slate-50">
             {errorMsg && <div className="bg-red-50 border-l-4 border-red-500 p-4 mb-4 rounded-r flex items-center text-red-700"><AlertCircle size={20} className="mr-2"/>{errorMsg}</div>}
             {currentView === 'dashboard' ? (
                 <Suspense fallback={<div className="text-center py-10">載入儀表板...</div>}>
                    <DashboardView filteredPosts={filteredAndSortedPosts} />
                 </Suspense>
             ) : currentView === 'reports' ? (
                 <Suspense fallback={<div className="text-center py-10">載入報告模組...</div>}>
                    <ReportView existingPosts={posts} />
                 </Suspense>
             ) : (
                 <>
                     <div className="flex items-center gap-4 mb-4"><div className="text-sm text-gray-500 font-medium">共搜尋到 {filteredAndSortedPosts.length} 筆結果</div><button onClick={handleSelectAll} className="text-xs bg-indigo-50 text-indigo-600 px-3 py-1 rounded hover:bg-indigo-100 transition-colors">{selectedPostIds.size === filteredAndSortedPosts.length && filteredAndSortedPosts.length > 0 ? '取消全選' : '全選此頁'}</button></div>
                     {loading ? <div className="text-center text-gray-400 py-20">載入中...</div> : 
                      filteredAndSortedPosts.length === 0 ? <div className="text-center text-gray-400 py-20">找不到符合 "{searchQuery}" 的貼文</div> :
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                         {filteredAndSortedPosts.map(post => (
                             <PostCard key={post.id} post={post} selected={selectedPostIds.has(post.id)} onToggleSelect={(shift: boolean) => handleSelection(post.id, shift)} onEdit={handleEditClick} onDelete={handleDelete} onToggleType={handleToggleTypeClick} onToggleEditor={handleToggleEditorClick} />
                         ))}
                      </div>
                     }
                 </>
             )}
        </div>
      </main>

      {selectedPostIds.size > 0 && currentView === 'posts' && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-white text-gray-900 px-6 py-3 rounded-full shadow-2xl flex items-center gap-6 border border-gray-200 z-50 animate-in slide-in-from-bottom-10">
            <span className="font-bold text-sm flex items-center gap-2"><CheckCircle2 size={18} className="text-indigo-600"/> 已選 {selectedPostIds.size} 則</span>
            <div className="h-6 w-px bg-gray-200"></div>
            <button onClick={() => setIsBulkEditSeriesOpen(true)} className="flex items-center gap-2 text-sm font-medium hover:text-indigo-600"><FolderEdit size={16} /> 修改系列</button>
            <div className="h-6 w-px bg-gray-200"></div>
            <button onClick={() => setIsBulkEditEditorOpen(true)} className="flex items-center gap-2 text-sm font-medium hover:text-indigo-600"><UserCog size={16} /> 修改小編</button>
            <div className="h-6 w-px bg-gray-200"></div>
            <button onClick={handleCopySelected} className="flex items-center gap-2 text-sm font-medium hover:text-indigo-600"><Copy size={16}/> 複製提案</button>
            <button onClick={handleBulkDelete} className="flex items-center gap-2 text-sm font-medium hover:text-red-600 text-red-500"><Trash2 size={16}/> 刪除</button>
            <button onClick={() => setSelectedPostIds(new Set())} className="text-gray-400 hover:text-gray-600"><X size={16}/></button>
        </div>
      )}

      {isModalOpen && <PostModal post={editingPost} onClose={() => setIsModalOpen(false)} onSave={handleSave} seriesOptions={seriesList.map(s => s.name)}/>}
    </div>
  );
}