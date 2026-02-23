import { SERIES_RULES } from '../constants/data';
import type { Post, PostType, EditorName } from '../types';
import { useState, useEffect } from 'react';

// --- 自動分類邏輯 ---
// 根據標題和內文，對照 SERIES_RULES 來判斷屬於哪個系列
export const autoCategorize = (title: string, content: string) => {
  const fullText = (title + ' ' + content).toLowerCase();
  
  const postType: PostType = 'editorial';
  
  let detectedSeries = '📂 待分類';
  const foundTags = new Set<string>();
  
  for (const rule of SERIES_RULES) {
    if (rule.keywords.some((k: string) => fullText.includes(k.toLowerCase()))) {
      detectedSeries = rule.name;
      foundTags.add(rule.name);
      break;
    }
  }

  return { postType, series: detectedSeries, tags: Array.from(foundTags) };
};

export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

// --- Date Parsing Helper ---
function parseDate(dateStr: string): Date | null {
  const d = new Date(dateStr);
  if (!isNaN(d.getTime()) && d.getFullYear() > 1970 && d.getFullYear() < 3000) {
    return d;
  }
  // Try MM/DD/YYYY format
  const parts = dateStr.split('/');
  if (parts.length === 3) {
    const month = parseInt(parts[0], 10) - 1;
    const day = parseInt(parts[1], 10);
    const year = parseInt(parts[2], 10);
    const parsed = new Date(year, month, day);
    if (!isNaN(parsed.getTime()) && parsed.getFullYear() === year && parsed.getMonth() === month && parsed.getDate() === day) {
      return parsed;
    }
  }
  return null;
}

// --- CSV 解析邏輯 ---
// 將上傳的 CSV 文字轉換為 Post 物件陣列
// 注意：這裡回傳的是 Omit<Post, 'id'>，因為這些新資料還沒有 Firebase 的 ID
export const parseCSV = (text: string): Omit<Post, 'id'>[] => {
  const result: string[][] = [];
  let currentRow: string[] = [];
  let currentField = '';
  let inQuote = false;
  
  // Normalize line endings
  const cleanText = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

  // Parse CSV character by character to handle quotes correctly
  for (let i = 0; i < cleanText.length; i++) {
    const char = cleanText[i];
    const nextChar = cleanText[i+1];
    if (char === '"') {
      if (inQuote && nextChar === '"') {
        currentField += '"';
        i++;
      } else {
        inQuote = !inQuote;
      }
    } else if (char === ',' && !inQuote) {
      currentRow.push(currentField);
      currentField = '';
    } else if (char === '\n' && !inQuote) {
      currentRow.push(currentField);
      if (currentRow.some(c => c.trim())) { 
          result.push(currentRow); 
      }
      currentRow = [];
      currentField = '';
    } else {
      currentField += char;
    }
  }
  // Handle last row
  if (currentField || currentRow.length > 0) {
      currentRow.push(currentField);
      if (currentRow.some(c => c.trim())) result.push(currentRow);
  }

  if (result.length < 2) return [];

  // Identify Headers
  const headers = result[0].map(h => h.trim().toLowerCase().replace(/[\s_"]/g, ''));

  const getIndex = (patterns: string[]) => {
      let idx = headers.findIndex(h => patterns.includes(h));
      if (idx !== -1) return idx;
      return headers.findIndex(h => patterns.some(p => h.includes(p)));
  };

  // Map CSV columns to internal fields
  const idxTitle = getIndex(['title', 'posttitle', 'headline', 'name']);
  const idxContent = getIndex(['description', 'message', 'caption', 'text', 'body']);
  const idxUrl = getIndex(['permalink', 'link', 'url']);
  const idxLikes = getIndex(['likes', 'reaction', 'like']);
  const idxShares = getIndex(['shares', 'share', 'shared']);
  const idxReach = getIndex(['reach', 'impression']);
  const idxFollows = getIndex(['follows', 'follow', 'new fans', 'fans', 'Follows']);
  const idxClicks = getIndex(['link clicks', 'url clicks', 'clicks', 'total clicks']);
  const idxDate = getIndex(['publishtime', 'date', 'posted', 'time', 'created']);
  const idxImage = getIndex(['imageurl', 'mediaurl', 'thumbnail']);
  
  const idxDuration = getIndex(['duration', 'length', 'seconds']);
  const idxFormat = getIndex(['post type', 'type', 'media type', 'format']);
  const idxComments = getIndex(['comments', 'comment', 'Comments']);

  const idxAccount = headers.findIndex(h => {
      if (h.includes('id')) return false; 
      return ['accountname', 'accountusername', 'username', 'pagename', 'account'].some(p => h.includes(p));
  });

  if (idxContent === -1 && idxUrl === -1 && idxTitle === -1) {
      console.warn("Header mismatch: No Title, Description or URL found");
      return [];
  }

  // Map Rows to Post Objects
  return result.slice(1).map(cols => {
      const getVal = (i: number, defaultVal = '') => (i >= 0 && i < cols.length) ? cols[i].trim() : defaultVal;

      const titleRaw = getVal(idxTitle);
      const content = getVal(idxContent);
      let postUrl = getVal(idxUrl);
      
      if (!postUrl || !postUrl.startsWith('http')) {
          return null; 
      }
      
      const likesStr = getVal(idxLikes, '0');
      const sharesStr = getVal(idxShares, '0');
      const reachStr = getVal(idxReach, '0');
      const followsStr = getVal(idxFollows, '0');
      const clicksStr = getVal(idxClicks, '0');
      const commentsStr = getVal(idxComments, '0');
      const dateStr = getVal(idxDate);
      const imageUrl = getVal(idxImage);
      
      const durationStr = getVal(idxDuration, '0');
      const formatStr = getVal(idxFormat).toLowerCase();
      let isVideo = false;

      if (parseFloat(durationStr) > 0) {
          isVideo = true;
      } 
      else if (formatStr.includes('reel') || formatStr.includes('video') || formatStr.includes('clip')) {
          isVideo = true;
      }

      const accountRaw = getVal(idxAccount).toLowerCase().replace(/[\s\.]/g, ''); 
      let account = 'Other';
      if (accountRaw.includes('pestyle')) account = 'Pestyle';
      else if (accountRaw.includes('playeateasy') || accountRaw.includes('玩食易') || (accountRaw.includes('play') && accountRaw.includes('eat'))) account = 'Play Eat Easy';

      let platform = 'Other';
      if (postUrl && postUrl.includes('instagram')) platform = 'IG';
      else if (postUrl && postUrl.includes('facebook')) platform = 'FB';

      let title = titleRaw;
      const isIGPost = formatStr.includes('ig');
      
      if (isIGPost && content) {
          title = content; 
      } else if (platform === 'facebook' && isVideo && content) {
           title = content; 
      } else if (!title) {
           title = content ? (content.substring(0, 30) + (content.length > 30 ? '...' : '')) : '匯入的貼文';
      }
      
      const { postType, series, tags } = autoCategorize(title, content || '');

      // Hashtag Auto-Assign Logic (check longer hashtags first to avoid overlap)
      let editor: EditorName = null;
      const fullText = (title + ' ' + content).toLowerCase();
      if (fullText.includes('#psks')) editor = 'Kassandra';
      else if (fullText.includes('#pska')) editor = 'Kathy';
      else if (fullText.includes('#psr')) editor = 'Rachel';
      else if (fullText.includes('#psl')) editor = 'Loris';
      else if (fullText.includes('#psc')) editor = 'Chloe';
      else if (fullText.includes('#psk')) editor = 'Kiki';

      let validDate = new Date();
      if (dateStr) {
          const parsed = parseDate(dateStr);
          if (parsed) {
              validDate = parsed;
          }
      }

      const newPost: Omit<Post, 'id'> = {
          title: title,
          content: content,
          postUrl: postUrl,
          imageUrl: imageUrl || '', 
          likes: idxLikes >= 0 ? parseInt(String(likesStr).replace(/[^0-9]/g, '')) || 0 : undefined,
          shares: idxShares >= 0 ? parseInt(String(sharesStr).replace(/[^0-9]/g, '')) || 0 : undefined,
          reach: idxReach >= 0 ? parseInt(String(reachStr).replace(/[^0-9]/g, '')) || 0 : undefined,
          follows: idxFollows >= 0 ? parseInt(String(followsStr).replace(/[^0-9]/g, '')) || 0 : undefined,
          clicks: idxClicks >= 0 ? parseInt(String(clicksStr).replace(/[^0-9]/g, '')) || 0 : undefined,
          comments: idxComments >= 0 ? parseInt(String(commentsStr).replace(/[^0-9]/g, '')) || 0 : undefined,
          fans: idxFollows >= 0 ? parseInt(String(followsStr).replace(/[^0-9]/g, '')) || 0 : undefined,
          account: account,
          platform: platform,
          channel: account,
          postType: postType,
          series: series,
          tags: tags,
          editor: editor,
          createdAt: validDate,
          isVideo: isVideo,
          status: 'published',
          plannedTime: null
      };

      // Ensure numeric fields have defaults for create
      newPost.likes = newPost.likes || 0;
      newPost.shares = newPost.shares || 0;
      newPost.reach = newPost.reach || 0;
      newPost.follows = newPost.follows || 0;
      newPost.clicks = newPost.clicks || 0;
      newPost.comments = newPost.comments || 0;
      newPost.fans = newPost.fans || 0;

      return newPost;
  }).filter((item): item is Omit<Post, 'id'> => item !== null);
};