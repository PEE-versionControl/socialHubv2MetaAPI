import React from 'react';
import { EDITORS } from '../constants/data';
import { Bar, ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { Video, Image, FileUp, TrendingUp, UserPlus, MousePointerClick, Heart, Share2, Download } from 'lucide-react';
import type { Post } from '../types';

const DashboardView = (_props: { filteredPosts: Post[] }) => {
  const { filteredPosts } = _props;

  const [activeTab, setActiveTab] = React.useState<'Total' | 'PlayEatEasy' | 'Pestyle'>('Total');

  // Helper to safely get editor info with mapping for old names
  const getEditorInfo = (editorName: string) => {
    const nameMap: { [key: string]: string } = { 'Ra': 'Rachel', 'Kass': 'Kassandra', 'Louis': 'Loris' };
    const mappedName = nameMap[editorName] || editorName;
    return EDITORS.find(ed => ed.name === mappedName || ed.shortCodes.includes(mappedName)) || { 
      name: editorName, 
      color: 'bg-gray-100 text-gray-500', 
      code: '??' 
    };
  };

  // Export for AI function
  const handleExportAI = () => {
    const data = filteredPosts.map(post => {
      const dateObj = post.createdAt?.toDate ? post.createdAt.toDate() : new Date();
      const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
      const content = post.content || post.title || '';
      const link = post.postUrl || '';
      let platform = 'Other';
      if (link.includes('instagram.com')) platform = 'IG';
      else if (link.includes('facebook.com')) platform = 'FB';
      return {
        Channel: post.account || '',
        Platform: platform,
        Type: post.postType === 'ad' ? 'Ad' : 'Editorial',
        Category: post.series || '',
        Format: post.isVideo ? 'Video' : 'Image',
        Title: `"${(post.title || '').replace(/"/g, "'").replace(/\n/g, ' ').replace(/,/g, ';')}"`,
        Content: `"${content.replace(/"/g, "'").replace(/\n/g, ' ').replace(/,/g, ';')}"`,
        Date: dateObj.toISOString().split('T')[0],
        Weekday: days[dateObj.getDay()],
        Likes: post.likes || 0,
        Shares: post.shares || 0,
        Comments: post.comments || 0,
        Fans: post.fans || 0,
        Editor: post.editor || ''
      };
    });

    const csvHeader = 'Channel,Platform,Type,Category,Format,Title,Content,Date,Weekday,Likes,Shares,Comments,Fans,Editor\n';
    const csvRows = data.map(row => `${row.Channel},${row.Platform},${row.Type},${row.Category},${row.Format},${row.Title},${row.Content},${row.Date},${row.Weekday},${row.Likes},${row.Shares},${row.Comments},${row.Fans},${row.Editor}`).join('\n');
    const csvContent = csvHeader + csvRows;

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    if (link.download !== undefined) {
      const url = URL.createObjectURL(blob);
      link.setAttribute('href', url);
      link.setAttribute('download', 'social_data_for_ai.csv');
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  };

  // KPI Calculations
  const kpiStats = React.useMemo(() => {
    const totalPosts = filteredPosts.length;
    const totalInteractions = filteredPosts.reduce((sum, p) => sum + (p.likes || 0) + (p.shares || 0), 0);
    const totalFans = filteredPosts.reduce((sum, p) => sum + (p.follows || 0), 0);
    const totalClicks = filteredPosts.reduce((sum, p) => sum + (p.clicks || 0), 0);
    const avgLikes = totalPosts > 0 ? Math.round(filteredPosts.reduce((sum, p) => sum + (p.likes || 0), 0) / totalPosts) : 0;
    const avgShares = totalPosts > 0 ? Math.round(filteredPosts.reduce((sum, p) => sum + (p.shares || 0), 0) / totalPosts) : 0;
    return { totalPosts, totalInteractions, totalFans, totalClicks, avgLikes, avgShares };
  }, [filteredPosts]);

  // Series Stats
  const seriesStats = React.useMemo(() => {
    const stats: { [key: string]: number } = {};
    filteredPosts.forEach(p => {
      const series = p.series || '未分類';
      stats[series] = (stats[series] || 0) + 1;
    });
    return Object.entries(stats).sort((a, b) => b[1] - a[1]);
  }, [filteredPosts]);

  // Editor Stats
  const editorStats = React.useMemo(() => {
    const stats: { [key: string]: { posts: number; likes: number; shares: number; topPosts: { title: string; likes: number; shares: number; id: string }[] } } = {};
    filteredPosts.forEach(post => {
      const editor = post.editor;
      if (editor) {
        const editorInfo = getEditorInfo(editor);
        const key = editorInfo.name as string;
        if (!stats[key]) stats[key] = { posts: 0, likes: 0, shares: 0, topPosts: [] };
        stats[key].posts += 1;
        stats[key].likes += post.likes || 0;
        stats[key].shares += post.shares || 0;
        stats[key].topPosts.push({ title: post.title || 'No title', likes: post.likes || 0, shares: post.shares || 0, id: post.id || '' });
      } else {
        const key = 'Unassigned';
        if (!stats[key]) stats[key] = { posts: 0, likes: 0, shares: 0, topPosts: [] };
        stats[key].posts += 1;
        stats[key].likes += post.likes || 0;
        stats[key].shares += post.shares || 0;
        stats[key].topPosts.push({ title: post.title || 'No title', likes: post.likes || 0, shares: post.shares || 0, id: post.id || '' });
      }
    });
    // Sort and slice top 3 for each editor
    Object.values(stats).forEach(stat => {
      stat.topPosts.sort((a, b) => ((b.likes || 0) + (b.shares || 0)) - ((a.likes || 0) + (a.shares || 0)));
      stat.topPosts.splice(3);
    });
    return stats;
  }, [filteredPosts]);

  // Format Stats
  const formatStats = React.useMemo(() => {
    const video = filteredPosts.filter(p => p.isVideo).length;
    const image = filteredPosts.filter(p => !p.isVideo).length;
    return { video, image };
  }, [filteredPosts]);

  // Channel Stats
  const channelStats = React.useMemo(() => {
    const stats: { [key: string]: number } = {};
    filteredPosts.forEach(p => {
      const account = p.account || 'Other';
      stats[account] = (stats[account] || 0) + 1;
    });
    return stats;
  }, [filteredPosts]);

  // Ad Stats
  const adStats = React.useMemo(() => {
    const adPosts = filteredPosts.filter(p => p.postType === 'ad');
    if (adPosts.length === 0) return null;
    const totalSpend = adPosts.reduce((sum, p) => sum + (p.likes || 0), 0); // Placeholder, assuming no spend field
    const totalReach = adPosts.reduce((sum, p) => sum + (p.reach || 0), 0);
    const totalClicks = adPosts.reduce((sum, p) => sum + (p.clicks || 0), 0);
    return { totalSpend, totalReach, totalClicks, count: adPosts.length };
  }, [filteredPosts]);

  // Prepare data for WeeklyTrendChart
  const chartData = React.useMemo(() => {
    const tabFilteredPosts = activeTab === 'Total' ? filteredPosts : filteredPosts.filter(p => {
      if (activeTab === 'PlayEatEasy') return p.series?.toLowerCase().includes('play') || p.account?.toLowerCase().includes('play');
      if (activeTab === 'Pestyle') return p.series?.toLowerCase().includes('pestyle') || p.account?.toLowerCase().includes('pestyle');
      return false;
    });

    // Calculate the most recent Sunday
    const today = new Date();
    const dayOfWeek = today.getDay(); // 0 = Sunday
    const currentWeekStart = new Date(today);
    currentWeekStart.setDate(today.getDate() - dayOfWeek);
    currentWeekStart.setHours(0, 0, 0, 0); // Start of day

    // Generate last 12 week starts (Sundays), from oldest to newest
    const weekStarts: Date[] = [];
    for (let i = 11; i >= 0; i--) {
      const ws = new Date(currentWeekStart);
      ws.setDate(currentWeekStart.getDate() - i * 7);
      weekStarts.push(ws);
    }

    // Initialize data arrays with 0s for all 12 weeks
    const dataImagePosts = new Array(12).fill(0);
    const dataVideoPosts = new Array(12).fill(0);
    const dataAdCount = new Array(12).fill(0);
    const dataShares = new Array(12).fill(0);
    const dataFollows = new Array(12).fill(0);

    tabFilteredPosts.forEach(p => {
      const postDate = p.createdAt?.toDate ? p.createdAt.toDate() : new Date(p.createdAt);
      // Find the Sunday of the post's week
      const postWeekStart = new Date(postDate);
      postWeekStart.setDate(postDate.getDate() - postDate.getDay());
      postWeekStart.setHours(0, 0, 0, 0);

      // Find the index in weekStarts
      const index = weekStarts.findIndex(ws => ws.getTime() === postWeekStart.getTime());
      if (index !== -1) {
        if (!p.isVideo) dataImagePosts[index] += 1;
        else dataVideoPosts[index] += 1;
        if (p.postType === 'ad') dataAdCount[index] += 1;
        dataShares[index] += p.shares || 0;
        dataFollows[index] += p.follows || 0;
      }
    });

    // Auto-hide empty latest week
    const latestIndex = 11;
    if (dataImagePosts[latestIndex] === 0 && dataVideoPosts[latestIndex] === 0 && dataAdCount[latestIndex] === 0 && dataShares[latestIndex] === 0 && dataFollows[latestIndex] === 0) {
      dataImagePosts.pop();
      dataVideoPosts.pop();
      dataAdCount.pop();
      dataShares.pop();
      dataFollows.pop();
      weekStarts.pop();
    }

    // Labels: "Jan 19-25" format
    const labels = weekStarts.map(ws => {
      const end = new Date(ws);
      end.setDate(ws.getDate() + 6);
      const startStr = ws.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      const endStr = end.toLocaleDateString('en-US', { day: 'numeric' });
      return `${startStr}-${endStr}`;
    });

    return { dataImagePosts, dataVideoPosts, dataAdCount, dataShares, dataFollows, labels };
  }, [filteredPosts, activeTab]);

  return (
    <div className="p-4 space-y-6">
      <h2 className="text-xl font-bold">Dashboard</h2>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 text-center">
          <FileUp className="w-8 h-8 mx-auto mb-2 text-blue-600" />
          <div className="text-2xl font-bold text-blue-600">{kpiStats.totalPosts}</div>
          <div className="text-sm text-gray-500">Total Posts</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 text-center">
          <TrendingUp className="w-8 h-8 mx-auto mb-2 text-green-600" />
          <div className="text-2xl font-bold text-green-600">{kpiStats.totalInteractions.toLocaleString()}</div>
          <div className="text-sm text-gray-500">Interactions</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 text-center">
          <UserPlus className="w-8 h-8 mx-auto mb-2 text-purple-600" />
          <div className="text-2xl font-bold text-purple-600">{kpiStats.totalFans.toLocaleString()}</div>
          <div className="text-sm text-gray-500">Fans</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 text-center">
          <MousePointerClick className="w-8 h-8 mx-auto mb-2 text-orange-600" />
          <div className="text-2xl font-bold text-orange-600">{kpiStats.totalClicks.toLocaleString()}</div>
          <div className="text-sm text-gray-500">Clicks</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 text-center">
          <Heart className="w-8 h-8 mx-auto mb-2 text-red-600" />
          <div className="text-2xl font-bold text-red-600">{kpiStats.avgLikes.toLocaleString()}</div>
          <div className="text-sm text-gray-500">Avg Likes</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 text-center">
          <Share2 className="w-8 h-8 mx-auto mb-2 text-yellow-600" />
          <div className="text-2xl font-bold text-yellow-600">{kpiStats.avgShares.toLocaleString()}</div>
          <div className="text-sm text-gray-500">Avg Shares</div>
        </div>
      </div>

      {/* Weekly Trends */}
      <div className="bg-white p-4 rounded shadow">
        <h3 className="font-bold mb-4">Weekly Trends</h3>
        <div className="flex gap-2 mb-4">
          <button onClick={() => setActiveTab('Total')} className={`px-4 py-2 rounded ${activeTab === 'Total' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}>Total</button>
          <button onClick={() => setActiveTab('PlayEatEasy')} className={`px-4 py-2 rounded ${activeTab === 'PlayEatEasy' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}>Play Eat Easy</button>
          <button onClick={() => setActiveTab('Pestyle')} className={`px-4 py-2 rounded ${activeTab === 'Pestyle' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}>Pestyle</button>
          <button onClick={handleExportAI} className="ml-auto px-4 py-2 border border-indigo-500 text-indigo-600 rounded hover:bg-indigo-50 flex items-center gap-2">
            <Download size={16} />
            Export for AI
          </button>
        </div>
        <div className="space-y-6">
          {/* Chart A: Production Volume (Posts) */}
          <div>
            <h4 className="text-sm font-semibold mb-2">Production Volume</h4>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={chartData.labels.map((label, index) => ({
                name: label,
                imagePosts: chartData.dataImagePosts[index],
                videoPosts: chartData.dataVideoPosts[index],
                adCount: chartData.dataAdCount[index],
              }))}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="imagePosts" name="Image Posts" stackId="a" fill="#3b82f6" />
                <Bar dataKey="videoPosts" name="Video Posts" stackId="a" fill="#f97316" />
                <Line type="monotone" dataKey="adCount" name="Ad Posts" stroke="#ef4444" strokeWidth={2} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {/* Chart B: Market Impact (Engagement) */}
          <div>
            <h4 className="text-sm font-semibold mb-2">Market Impact</h4>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={chartData.labels.map((label, index) => ({
                name: label,
                shares: chartData.dataShares[index],
                fans: chartData.dataFollows[index],
              }))}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis yAxisId="left" orientation="left" stroke="#10b981" />
                <YAxis yAxisId="right" orientation="right" stroke="#eab308" />
                <Tooltip />
                <Legend />
                <Line yAxisId="left" type="monotone" dataKey="shares" name="Shares" stroke="#10b981" strokeWidth={2} />
                <Line yAxisId="right" type="monotone" dataKey="fans" name="Fans" stroke="#eab308" strokeWidth={2} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Series Ranking and Editor Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white p-4 rounded shadow">
          <h3 className="font-bold mb-4">Series Ranking</h3>
          <ul className="space-y-2">
            {seriesStats.slice(0, 10).map(([series, count]) => {
              const percentage = (count / filteredPosts.length) * 100;
              return (
                <li key={series} className="flex justify-between items-center">
                  <span className="text-sm">{series}</span>
                  <div className="flex items-center gap-2">
                    <div className="w-20 bg-gray-200 rounded-full h-2">
                      <div className="bg-blue-600 h-2 rounded-full" style={{ width: `${percentage}%` }}></div>
                    </div>
                    <span className="text-sm font-bold">{count}</span>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="bg-white p-4 rounded shadow">
          <h3 className="font-bold mb-4">Editor Stats</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left">Editor</th>
                <th className="text-right">Posts</th>
                <th className="text-right">Likes</th>
                <th className="text-right">Shares</th>
                <th className="text-right">Avg Shares</th>
                <th className="text-left">Top 3 Posts</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(editorStats).map(([editorName, stats]) => {
                const editorInfo = getEditorInfo(editorName);
                return (
                  <tr key={editorName} className="border-b">
                    <td className={`py-2 ${editorInfo.color}`}>{editorInfo.name} ({editorInfo.code})</td>
                    <td className="text-right">{stats.posts}</td>
                    <td className="text-right">{stats.likes.toLocaleString()}</td>
                    <td className="text-right">{stats.shares.toLocaleString()}</td>
                    <td className="text-right">{stats.posts > 0 ? Math.round(stats.shares / stats.posts) : 0}</td>
                    <td className="text-left">
                      {stats.topPosts.map((post, idx) => (
                        <div className="flex flex-col mb-1" key={post.id || idx}>
                          <span className="text-sm font-medium text-gray-700 line-clamp-1">{post.title}</span>
                          <span className="text-xs text-gray-500">
                            ❤️ {post.likes?.toLocaleString() || 0} · ↗️ {post.shares?.toLocaleString() || 0}
                          </span>
                        </div>
                      ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Format & Channel Analysis */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white p-4 rounded shadow">
          <h3 className="font-bold mb-4">Format Analysis</h3>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span><Video className="inline w-4 h-4 mr-1" />Video</span>
              <span>{formatStats.video} ({filteredPosts.length > 0 ? ((formatStats.video / filteredPosts.length) * 100).toFixed(1) : 0}%)</span>
            </div>
            <div className="flex justify-between">
              <span><Image className="inline w-4 h-4 mr-1" />Image</span>
              <span>{formatStats.image} ({filteredPosts.length > 0 ? ((formatStats.image / filteredPosts.length) * 100).toFixed(1) : 0}%)</span>
            </div>
          </div>
        </div>

        <div className="bg-white p-4 rounded shadow">
          <h3 className="font-bold mb-4">Channel Analysis</h3>
          <div className="space-y-2">
            {Object.entries(channelStats).map(([account, count]) => (
              <div key={account} className="flex justify-between">
                <span>{account}</span>
                <span>{count} ({filteredPosts.length > 0 ? ((count / filteredPosts.length) * 100).toFixed(1) : 0}%)</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Ad Performance */}
      {adStats && (
        <div className="bg-white p-4 rounded shadow">
          <h3 className="font-bold mb-4">Ad Performance</h3>
          <div className="grid grid-cols-3 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold">{adStats.count}</div>
              <div className="text-sm text-gray-500">Ad Posts</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold">{adStats.totalSpend.toLocaleString()}</div>
              <div className="text-sm text-gray-500">Ad Spend (Likes)</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold">{adStats.totalReach.toLocaleString()}</div>
              <div className="text-sm text-gray-500">Ad Reach</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DashboardView;
