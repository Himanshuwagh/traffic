import React, { useState, useEffect, useCallback } from 'react';
import { type City } from '../data/mockData';
import { type TrafficSummary } from './MapboxMap';
import SegmentCard from './SegmentCard';
import { BarChart2, Activity, TrendingDown } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  Cell, ReferenceLine,
} from 'recharts';
import { apiUrl } from '../lib/api';

interface CityOverviewProps {
  city: City;
  summary: TrafficSummary | null;
  onSegmentClick: (id: string) => void;
}

interface HourlyBucket {
  hour: string;
  avg_speed: number | null;
  count: number;
}

const speedColor = (speed: number | null) => {
  if (speed == null) return '#6B7280';
  if (speed >= 40) return '#00C700';
  if (speed >= 25) return '#FACC15';
  if (speed >= 15) return '#F97316';
  return '#EF4444';
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const speed = payload[0]?.value as number | null;
  return (
    <div className="bg-[#1A1D27] border border-white/10 rounded-lg px-3 py-2 shadow-xl text-xs">
      <p className="text-gray-400 mb-1">{label}</p>
      <p className="font-semibold" style={{ color: speedColor(speed) }}>
        {speed != null ? `${speed} km/h` : 'No data'}
      </p>
    </div>
  );
};

const CityOverview: React.FC<CityOverviewProps> = ({ city, summary, onSegmentClick }) => {
  const topBottlenecks = summary?.top_bottlenecks ?? [];
  const avgSpeed = summary?.avg_speed != null ? summary.avg_speed.toFixed(1) : 'N/A';
  const topCorridorName = summary?.top_corridor_name || 'N/A';
  const activeSegments = summary?.active_segments ?? 0;
  const activeHotspots = summary?.active_hotspots ?? activeSegments;
  const worstCongestion =
    summary?.worst_congestion_index != null ? `${Math.round(summary.worst_congestion_index)} CFI` : 'N/A';
  const statusLabel = summary?.status === 'live' ? 'Live Data' : 'Loading';
  const statusColor = summary?.status === 'live' ? 'text-[#10B981]' : 'text-gray-400';

  const [hourlyData, setHourlyData] = useState<HourlyBucket[]>([]);
  const [loadingChart, setLoadingChart] = useState(false);

  const loadHourlyChart = useCallback(async () => {
    setLoadingChart(true);
    try {
      const res = await fetch(apiUrl(`/api/traffic/hourly?city=${encodeURIComponent(city.id)}`));
      const data = await res.json();
      if (Array.isArray(data)) setHourlyData(data);
    } catch {
      // silently ignore
    } finally {
      setLoadingChart(false);
    }
  }, [city.id]);

  useEffect(() => {
    loadHourlyChart();
  }, [loadHourlyChart]);

  return (
    <div className="animate-in fade-in slide-in-from-right-4 duration-300">
      <h2 className="text-xl font-semibold mb-6 text-white">{city.name} Traffic Overview</h2>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        <div className="card p-4">
          <p className="label-text mb-1 text-[10px] text-gray-500 uppercase tracking-wider">Most congested</p>
          <p className="font-semibold text-sm truncate text-white" title={topCorridorName}>{topCorridorName}</p>
        </div>
        <div className="card p-4">
          <p className="label-text mb-1 text-[10px] text-gray-500 uppercase tracking-wider">Avg observed speed</p>
          <p className="font-semibold text-2xl text-white">{avgSpeed} <span className="text-sm font-normal text-gray-400">km/h</span></p>
        </div>
        <div className="card p-4">
          <p className="label-text mb-1 text-[10px] text-gray-500 uppercase tracking-wider">Active hotspots</p>
          <p className="font-semibold text-lg text-white">{activeHotspots}</p>
        </div>
        <div className="card p-4">
          <p className="label-text mb-1 text-[10px] text-gray-500 uppercase tracking-wider">Worst congestion</p>
          <p className={`font-semibold text-lg ${statusColor} flex items-center gap-1.5`}>
            <Activity className="w-4 h-4" />
            {worstCongestion === 'N/A' ? statusLabel : worstCongestion}
          </p>
        </div>
      </div>

      {/* Hourly speed chart */}
      <div className="card p-5 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <BarChart2 className="w-4 h-4 text-brand-amber" />
            <h3 className="text-sm font-semibold text-white">Avg Speed by Hour of Day</h3>
          </div>
          <span className="text-[10px] text-gray-500">from stored traffic_data</span>
        </div>

        {loadingChart ? (
          <div className="h-[160px] flex items-center justify-center text-gray-500 text-sm">
            Loading chart…
          </div>
        ) : hourlyData.length > 0 ? (
          <div className="h-[160px] w-full min-w-0">
            <ResponsiveContainer width="99%" height="100%">
              <BarChart data={hourlyData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <XAxis
                  dataKey="hour"
                  stroke="#374151"
                  tick={{ fill: '#9CA3AF', fontSize: 9 }}
                  tickLine={false}
                  axisLine={false}
                  interval={3}
                />
                <YAxis
                  stroke="#374151"
                  tick={{ fill: '#9CA3AF', fontSize: 9 }}
                  tickLine={false}
                  axisLine={false}
                  domain={[0, 'auto']}
                />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                <ReferenceLine y={25} stroke="#F97316" strokeDasharray="3 3" strokeWidth={1} />
                <Bar dataKey="avg_speed" radius={[3, 3, 0, 0]}>
                  {hourlyData.map((entry, index) => (
                    <Cell key={index} fill={speedColor(entry.avg_speed)} fillOpacity={0.85} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="h-[160px] flex flex-col items-center justify-center gap-2 text-gray-600 text-sm">
            <TrendingDown className="w-8 h-8 text-gray-700" />
            <span>No stored traffic history available for this city yet.</span>
          </div>
        )}

        <div className="flex items-center justify-end gap-4 mt-2 text-[10px] text-gray-500">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm inline-block" style={{background:'#00C700'}} />Free flow (≥40)</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm inline-block" style={{background:'#FACC15'}} />Moderate (25-40)</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm inline-block" style={{background:'#EF4444'}} />Congested (&lt;15)</span>
        </div>
      </div>

      {/* Top Bottlenecks */}
      <h3 className="font-semibold mb-4 text-white">Top 10 Bottlenecks</h3>
      <div className="space-y-3 pb-8">
        {topBottlenecks.map((feature, idx) => (
          <SegmentCard
            key={feature.id}
            rank={idx + 1}
            name={feature.name || 'Unknown Road'}
            cfi={Math.round(feature.cfi)}
            statLabel={feature.jam_level ? `${feature.jam_level} congestion` : 'Observed speed'}
            statValue={feature.speed != null ? `${Math.round(feature.speed)} km/h` : 'N/A'}
            onClick={() => onSegmentClick(String(feature.id))}
          />
        ))}
        {topBottlenecks.length === 0 && (
          <p className="text-gray-500 text-sm italic">
            No bottlenecks were recorded for the selected city, date, and hour.
          </p>
        )}
      </div>
    </div>
  );
};

export default CityOverview;
