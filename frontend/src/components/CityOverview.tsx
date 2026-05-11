import React from 'react';
import { type City } from '../data/mockData';
import { type TrafficSummary } from './MapboxMap';
import SegmentCard from './SegmentCard';

interface CityOverviewProps {
  city: City;
  summary: TrafficSummary | null;
  onSegmentClick: (id: string) => void;
}

const CityOverview: React.FC<CityOverviewProps> = ({ city, summary, onSegmentClick }) => {
  const topBottlenecks = summary?.top_bottlenecks ?? [];
  const avgSpeed = summary?.avg_speed != null ? summary.avg_speed.toFixed(1) : 'N/A';
  const topCorridorName = summary?.top_corridor_name || 'N/A';
  const activeSegments = summary?.active_segments ?? 0;
  const statusLabel = summary?.status === 'live' ? 'Live Data' : 'Loading';
  const statusColor = summary?.status === 'live' ? 'text-[#10B981]' : 'text-gray-400';

  return (
    <div className="animate-in fade-in slide-in-from-right-4 duration-300">
      <h2 className="text-xl font-semibold mb-6 text-white">{city.name} Real-Time Overview</h2>
      
      <div className="grid grid-cols-2 gap-4 mb-8">
        <div className="card p-4">
          <p className="label-text mb-1">Most congested corridor</p>
          <p className="font-semibold text-sm truncate text-white" title={topCorridorName}>{topCorridorName}</p>
        </div>
        <div className="card p-4">
          <p className="label-text mb-1">Avg city speed</p>
          <p className="font-semibold text-2xl text-white">{avgSpeed} <span className="text-sm font-normal text-gray-400">km/h</span></p>
        </div>
        <div className="card p-4">
          <p className="label-text mb-1">Active Segments</p>
          <p className="font-semibold text-lg text-white">{activeSegments}</p>
        </div>
        <div className="card p-4">
          <p className="label-text mb-1">Status</p>
          <p className={`font-semibold text-lg ${statusColor}`}>{statusLabel}</p>
        </div>
      </div>

      <h3 className="font-semibold mb-4 text-white">Top 10 Live Bottlenecks</h3>
      <div className="space-y-3 pb-8">
        {topBottlenecks.map((feature, idx) => {
          return (
            <SegmentCard
              key={feature.id}
              rank={idx + 1}
              name={feature.name || 'Unknown Road'}
              cfi={Math.round(feature.cfi)}
              statLabel="Current speed"
              statValue={feature.speed != null ? `${Math.round(feature.speed)} km/h` : 'N/A'}
              onClick={() => onSegmentClick(String(feature.id))}
            />
          );
        })}
        {topBottlenecks.length === 0 && (
          <p className="text-gray-500 text-sm italic">No active traffic data available for this time.</p>
        )}
      </div>
    </div>
  );
};
export default CityOverview;
