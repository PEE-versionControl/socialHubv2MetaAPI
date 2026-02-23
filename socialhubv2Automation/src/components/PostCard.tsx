import React from 'react';
import { CheckSquare, Square, Megaphone, PenTool, UserCircle, Edit2, Trash2, Heart, Share2, MousePointerClick, PlayCircle, ExternalLink } from 'lucide-react';
import { EDITORS } from '../constants/data';
import PlatformBadge from './PlatformBadge';
import type { Post } from '../types';

const PostCard = React.memo(({ post, onEdit, onDelete, onToggleType, onToggleEditor, selected, onToggleSelect }: {post: Post, onEdit: any, onDelete: any, onToggleType: any, onToggleEditor: any, selected: boolean, onToggleSelect: any}) => {
  const accountName = post.account || 'Other';
  const accountColor = accountName === 'Pestyle' ? 'bg-fuchsia-100 text-fuchsia-700' : 'bg-orange-100 text-orange-700';
  const isAd = post.postType === 'ad';
  const displayTitle = post.title && post.title.trim() !== '' ? post.title : '（無標題）';
  const editor = post.editor;
  const editorInfo = EDITORS.find(e => e.name === editor);
  const editorCode = editorInfo ? editorInfo.code : 'NA';
  const editorColor = editorInfo ? editorInfo.color : 'bg-gray-100 text-gray-400';
  let dateStr = 'Unknown Date';
  try { const dateObj = post.createdAt?.toDate ? post.createdAt.toDate() : new Date(post.createdAt); if (!isNaN(dateObj.getTime())) { const year = dateObj.getFullYear(); if (year > 2050) dateStr = "Invalid Date"; else dateStr = dateObj.toLocaleDateString('zh-HK'); } } catch (e) { console.warn("Invalid date:", post.id); }

  return (
    <div className={`bg-white rounded-xl border overflow-hidden hover:shadow-lg transition-all p-4 h-full relative group cursor-default ${selected ? 'border-indigo-500 ring-2 ring-indigo-500' : 'border-gray-200'}`} onClick={(e) => { if (!(e.target as HTMLElement).closest('button, a')) onToggleSelect(e.shiftKey); }}>
       <div className="absolute top-3 left-3 z-10"><button onClick={(e) => { e.stopPropagation(); onToggleSelect(e.shiftKey); }} className="text-gray-400 hover:text-indigo-600">{selected ? <CheckSquare size={20} className="text-indigo-600 fill-indigo-50" /> : <Square size={20} />}</button></div>
      <div className="flex flex-col h-full pl-8">
          <div className="flex justify-between items-start mb-2">
              <div className="flex flex-col gap-1">
                  <div className="flex gap-1 flex-wrap"><span className={`px-2 py-0.5 rounded text-[10px] font-bold ${accountColor}`}>{accountName}</span><span className="px-2 py-0.5 rounded text-[10px] bg-indigo-50 text-indigo-700">{post.series}</span>{post.isVideo && <span className="bg-black/80 text-white text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1"><PlayCircle size={10} className="fill-white" /> Video</span>}</div>
                  <div className="flex items-center gap-2 mt-1">
                     <div onClick={(e) => { e.preventDefault(); e.stopPropagation(); onToggleType(post); }} className="cursor-pointer hover:opacity-80 inline-flex">{isAd ? <span className="bg-pink-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1"><Megaphone size={10}/> AD</span> : <span className="bg-teal-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1"><PenTool size={10}/> E</span>}</div>
                     <div onClick={(e) => { e.preventDefault(); e.stopPropagation(); onToggleEditor(post); }} className={`cursor-pointer hover:opacity-80 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold ${editorColor}`} title="點擊切換小編"><UserCircle size={10} /> {editorCode}</div>
                  </div>
              </div>
              <div className="flex flex-col items-end gap-1"><span className="text-[10px] text-gray-400">{dateStr}</span><div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity"><button onClick={(e) => { e.stopPropagation(); onEdit(post); }} className="p-1 bg-gray-50 rounded hover:bg-gray-200"><Edit2 size={12}/></button><button onClick={(e) => { e.stopPropagation(); onDelete(post.id); }} className="p-1 bg-red-50 rounded text-red-500 hover:bg-red-100"><Trash2 size={12}/></button></div></div>
          </div>
          <h3 className="font-bold text-gray-900 text-sm line-clamp-3 mb-3 flex-1" title={post.title}>{displayTitle}</h3>
                <div className="pt-3 border-t flex justify-between items-center mt-auto">
                  <div className="flex gap-3 text-xs font-medium text-gray-500"><span className="flex items-center gap-1 text-pink-600"><Heart size={12}/> {(post.likes||0).toLocaleString()}</span><span className="flex items-center gap-1 text-green-600"><Share2 size={12}/> {(post.shares||0).toLocaleString()}</span>{(post.clicks ?? 0) > 0 && <span className="flex items-center gap-1 text-orange-600"><MousePointerClick size={12}/> {(post.clicks||0).toLocaleString()}</span>}</div>
              <div className="flex items-center gap-3"><PlatformBadge platform={post.platform} /><a href={post.postUrl} target="_blank" rel="noopener noreferrer" className="text-xs text-gray-400 hover:text-indigo-600 flex items-center gap-1" onClick={e => e.stopPropagation()}><ExternalLink size={12}/></a></div>
          </div>
      </div>
    </div>
  );
}, (prev, next) => {
    return prev.post.id === next.post.id && prev.selected === next.selected && prev.post.likes === next.post.likes && prev.post.series === next.post.series && prev.post.postType === next.post.postType && prev.post.editor === next.post.editor && prev.post.clicks === next.post.clicks; 
});

export default PostCard;
