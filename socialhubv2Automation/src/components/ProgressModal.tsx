import { Loader2, XCircle } from 'lucide-react';
import type { ProgressState } from '../types';

const ProgressModal = ({ progress, onCancel }: { progress: ProgressState, onCancel: () => void }) => {
  if (!progress.isActive) return null;
  const percentage = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;
  return (
    <div className="fixed inset-0 bg-black/60 z-[60] flex items-center justify-center backdrop-blur-sm">
      <div className="bg-white rounded-xl p-8 w-full max-w-md shadow-2xl flex flex-col items-center animate-fade-in">
        <Loader2 className="w-10 h-10 text-indigo-600 animate-spin mb-4" />
        <h3 className="text-lg font-bold text-gray-800 mb-2">{progress.message}</h3>
        <div className="w-full bg-gray-200 rounded-full h-2.5 mb-2 overflow-hidden">
          <div className="bg-indigo-600 h-2.5 rounded-full transition-all duration-300" style={{ width: `${percentage}%` }}></div>
        </div>
        <p className="text-sm text-gray-500 font-medium mb-6">{progress.current} / {progress.total} ({percentage}%)</p>
        <button onClick={onCancel} className="flex items-center gap-2 px-4 py-2 border border-red-200 text-red-600 rounded-lg hover:bg-red-50 text-sm font-medium transition-colors"><XCircle size={16} /> 強制取消</button>
      </div>
    </div>
  );
};

export default ProgressModal;