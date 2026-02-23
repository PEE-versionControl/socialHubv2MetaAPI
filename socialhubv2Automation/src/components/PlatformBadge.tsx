const PlatformBadge = ({ platform }: { platform?: string }) => {
  const label = platform === 'IG' ? 'IG' : platform === 'FB' ? 'FB' : 'Other';
  const colorClass = platform === 'IG' ? 'text-pink-600 bg-pink-50 border-pink-100' : platform === 'FB' ? 'text-blue-600 bg-blue-50 border-blue-100' : 'text-gray-500 bg-gray-50 border-gray-100';
  return <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${colorClass}`}>{label}</span>;
};

export default PlatformBadge;