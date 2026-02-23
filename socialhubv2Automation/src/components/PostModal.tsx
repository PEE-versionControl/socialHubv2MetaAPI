import { useState } from 'react';
import { X, Save } from 'lucide-react';
import { EDITORS } from '../constants/data';
import type { FormEvent } from 'react';
 

function PostModal({ post, onClose, onSave, seriesOptions }: any) {
  const [formData, setFormData] = useState(post ? { ...post, tagsString: post.tags?.join(', ') } : { title: '', platform: 'instagram', content: '', postUrl: '', postType: 'editorial', series: '', likes: 0, reach: 0, shares: 0, follows: 0, clicks: 0, account: 'Pestyle', editor: null, isVideo: false });
  const handleSubmit = (e: FormEvent) => { e.preventDefault(); onSave({ ...formData, likes: Number(formData.likes), reach: Number(formData.reach), shares: Number(formData.shares), follows: Number(formData.follows), clicks: Number(formData.clicks), tags: formData.tagsString?.split(',').filter(Boolean) || [] }); };
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
       <div className="bg-white rounded-xl w-full max-w-lg p-6">
           <div className="flex justify-between mb-4"><h2 className="font-bold">編輯貼文</h2><button onClick={onClose}><X/></button></div>
           <form onSubmit={handleSubmit} className="space-y-4">
               <div><label className="text-xs font-bold block mb-1">標題</label><input className="w-full border p-2 rounded" value={formData.title} onChange={e => setFormData({...formData, title: e.target.value})} /></div>
               <div><label className="text-xs font-bold block mb-1">連結</label><input className="w-full border p-2 rounded" value={formData.postUrl} onChange={e => setFormData({...formData, postUrl: e.target.value})} /></div>
               <div className="grid grid-cols-5 gap-2">
                   <div><label className="text-xs font-bold">Likes</label><input type="number" className="w-full border p-2 rounded" value={formData.likes} onChange={e => setFormData({...formData, likes: e.target.value})} /></div>
                   <div><label className="text-xs font-bold">Reach</label><input type="number" className="w-full border p-2 rounded" value={formData.reach} onChange={e => setFormData({...formData, reach: e.target.value})} /></div>
                   <div><label className="text-xs font-bold">Shares</label><input type="number" className="w-full border p-2 rounded" value={formData.shares} onChange={e => setFormData({...formData, shares: e.target.value})} /></div>
                   <div><label className="text-xs font-bold">Fans</label><input type="number" className="w-full border p-2 rounded" value={formData.follows} onChange={e => setFormData({...formData, follows: e.target.value})} /></div>
                   <div><label className="text-xs font-bold">Clicks</label><input type="number" className="w-full border p-2 rounded" value={formData.clicks} onChange={e => setFormData({...formData, clicks: e.target.value})} /></div>
               </div>
               <div className="grid grid-cols-2 gap-4">
                   <div><label className="text-xs font-bold block mb-1">系列 (Series)</label><input list="series-list" className="w-full border p-2 rounded" value={formData.series} onChange={e => setFormData({...formData, series: e.target.value})} /><datalist id="series-list">{seriesOptions.map((s: string) => <option key={s} value={s}/>)}</datalist></div>
                   <div><label className="text-xs font-bold block mb-1">小編 (Editor)</label><select className="w-full border p-2 rounded" value={formData.editor || ''} onChange={e => setFormData({...formData, editor: e.target.value || null})}><option value="">未分配</option>{EDITORS.map(ed => <option key={ed.name} value={ed.name || ''}>{ed.name}</option>)}</select></div>
               </div>
               <label className="flex items-center gap-2 cursor-pointer border p-2 rounded"><input type="checkbox" checked={formData.isVideo} onChange={e => setFormData({...formData, isVideo: e.target.checked})} /> 這是影片內容 (Video)</label>
               <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="px-4 py-2 bg-gray-100 rounded">取消</button><button type="submit" className="px-4 py-2 bg-indigo-600 text-white rounded"><Save size={16} className="inline mr-1"/> 儲存</button></div>
           </form>
       </div>
    </div>
  );
}

export default PostModal;