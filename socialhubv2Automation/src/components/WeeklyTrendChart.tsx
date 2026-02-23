import { ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const WeeklyTrendChart = ({ dataImagePosts, dataVideoPosts, dataShares, dataFollows, labels, height = 250 }: any) => {
  if (!dataImagePosts || dataImagePosts.length === 0) {
    return <div className="flex items-center justify-center h-full text-gray-400 text-sm bg-gray-50 rounded-lg" style={{ height: `${height}px` }}>暫無數據</div>;
  }

  const data = labels.map((label: string, index: number) => ({
    name: label,
    imagePosts: dataImagePosts[index] || 0,
    videoPosts: dataVideoPosts[index] || 0,
    shares: dataShares[index] || 0,
    follows: dataFollows[index] || 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" />
        <YAxis yAxisId="left" orientation="left" stroke="#8884d8" />
        <YAxis yAxisId="right" orientation="right" stroke="#82ca9d" />
        <Tooltip />
        <Legend />
        <Bar yAxisId="left" dataKey="imagePosts" name="Image Posts" stackId="a" fill="#3b82f6" />
        <Bar yAxisId="left" dataKey="videoPosts" name="Video Posts" stackId="a" fill="#f97316" />
        <Line yAxisId="right" type="monotone" dataKey="shares" name="Shares" stroke="#10b981" strokeWidth={2} />
        <Line yAxisId="right" type="monotone" dataKey="follows" name="Fans" stroke="#eab308" strokeWidth={2} />
      </ComposedChart>
    </ResponsiveContainer>
  );
};

export default WeeklyTrendChart;