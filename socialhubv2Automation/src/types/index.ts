export type PostType = 'ad' | 'editorial';
// 更新：Kass -> Kassandra, Ra -> Rachel, Louis -> Loris
export type EditorName = 'Kiki' | 'Chloe' | 'Kathy' | 'Kassandra' | 'Rachel' | 'Loris' | null;
export type PostStatus = 'scheduled' | 'published'; 

export interface Post {
  id: string;
  platform?: string;
  title: string; 
  content: string; 
  imageUrl: string;
  postUrl: string;
  postType: PostType;
  series: string;
  tags: string[]; 
  likes?: number;
  reach?: number;
  shares?: number;
  follows?: number; 
  clicks?: number;
  account?: string;
  editor?: EditorName;
  isVideo?: boolean;
  createdAt: any;
  status?: PostStatus;
  plannedTime?: string | null;
  fans?: number;
  channel?: string;
  comments?: number;
}

export interface ProgressState {
  isActive: boolean;
  message: string;
  current: number;
  total: number;
}