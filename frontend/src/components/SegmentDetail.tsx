import React, { useMemo } from 'react';
import { ArrowLeft, Clock, AlertTriangle, TrendingUp } from 'lucide-react';
import { type Segment } from '../data/mockData';
import CFIScoreBadge from './CFIScoreBadge';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

interface SegmentDetailProps {
  segment: Segment;
  onBack: () => void;
  onCompare: () => void;
}

const SegmentDetail: React.FC<SegmentDetailProps> = ({ segment, onBack, onCompare }) => {
  const chartData = useMemo(() => {
    return Array.from({ length: 24 }).map((_, i) => ({
      hour: `${i}:00`,
      weekday: segment.weekdaySpeedProfile[i],
      weekend: segment.weekendSpeedProfile[i]
    }));
  }, [segment]);

  return (
    <div className="animate-in fade-in slide-in-from-right-4 duration-300 pb-8">
      <button 
        onClick={onBack}
        className="flex items-center gap-2 text-brand-amber text-sm font-medium hover:text-white transition-colors mb-6 cursor-pointer"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to city overview
      </button>

      {/* Section A - Header */}
      <div className="mb-8">
        <h2 className="text-[20px] font-semibold text-white mb-1">{segment.name}</h2>
        <p className="text-gray-400 text-sm mb-6">
          {segment.city} &bull; {segment.type.charAt(0).toUpperCase() + segment.type.slice(1)} &bull; Segment
        </p>
        
        <div className="flex items-center gap-4 mb-6">
          <CFIScoreBadge score={segment.cfi} size="lg" />
          <div>
            <p className="text-sm font-medium text-white">Congestion Frequency Index</p>
            <p className="text-xs text-gray-400">Based on trailing 30 days</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <div className="bg-brand-card border border-brand-border rounded-full px-3 py-1.5 text-xs font-medium text-gray-300 flex items-center gap-1.5 shadow-sm">
            <TrendingUp className="w-3.5 h-3.5 text-gray-400" /> Avg speed: {segment.avgSpeed} km/h
          </div>
          <div className="bg-brand-card border border-brand-border rounded-full px-3 py-1.5 text-xs font-medium text-gray-300 flex items-center gap-1.5 shadow-sm">
            <Clock className="w-3.5 h-3.5 text-brand-amber" /> Peak delay: +{segment.peakDelay} min
          </div>
          <div className="bg-brand-card border border-brand-border rounded-full px-3 py-1.5 text-xs font-medium text-gray-300 flex items-center gap-1.5 shadow-sm">
            <AlertTriangle className="w-3.5 h-3.5 text-cfi-red" /> Accident reports: {segment.accidentCount}
          </div>
        </div>
      </div>

      {/* Section B - Line Chart */}
      <div className="mb-8 card p-5 shadow-sm">
        <h3 className="text-sm font-semibold mb-4 text-white">Typical speed by hour</h3>
        <div className="h-[200px] w-full -ml-4">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
              <XAxis dataKey="hour" stroke="#4B5563" fontSize={10} tickMargin={8} minTickGap={20} tickLine={false} axisLine={false} />
              <YAxis stroke="#4B5563" fontSize={10} domain={[0, 60]} tickLine={false} axisLine={false} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1A1D27', borderColor: 'rgba(255,255,255,0.08)', borderRadius: '8px', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.4)' }}
                itemStyle={{ fontSize: '12px' }}
                labelStyle={{ fontSize: '12px', color: '#9CA3AF', marginBottom: '4px' }}
                cursor={{ stroke: 'rgba(255,255,255,0.1)', strokeWidth: 1 }}
              />
              <Line type="monotone" dataKey="weekday" name="Weekday (km/h)" stroke="#F59E0B" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
              <Line type="monotone" dataKey="weekend" name="Weekend (km/h)" stroke="#10B981" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Section C - Heatmap */}
      <div className="mb-8 card p-5 shadow-sm">
        <h3 className="text-sm font-semibold mb-4 text-white">Congestion by day and hour</h3>
        <div className="flex flex-col gap-1">
          {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((day, dIdx) => (
            <div key={day} className="flex items-center gap-2">
              <span className="text-[10px] text-gray-400 w-6 shrink-0">{day}</span>
              <div className="flex-1 flex gap-0.5 h-3">
                {Array.from({ length: 24 }).map((_, hIdx) => {
                  const isWeekend = dIdx >= 5;
                  const profile = isWeekend ? segment.weekendSpeedProfile : segment.weekdaySpeedProfile;
                  const speed = profile[hIdx];
                  // Lower speed = worse = more red
                  let bg = 'bg-[#10B981]'; // Green
                  if (speed < segment.avgSpeed - 5) bg = 'bg-[#EF4444]';
                  else if (speed < segment.avgSpeed - 2) bg = 'bg-[#F97316]';
                  else if (speed < segment.avgSpeed + 2) bg = 'bg-[#F59E0B]';
                  else if (speed < segment.avgSpeed + 8) bg = 'bg-[#84CC16]';
                  
                  return (
                    <div 
                      key={hIdx} 
                      className={`flex-1 ${bg} rounded-sm opacity-90 transition-opacity hover:opacity-100 cursor-help`} 
                      title={`${day} ${hIdx}:00 - ${Math.round(speed)} km/h`} 
                    />
                  )
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="flex justify-end items-center gap-2 mt-3 text-[10px] text-gray-400">
          <span>Heavy Traffic</span>
          <div className="flex gap-0.5">
            <div className="w-2 h-2 bg-[#EF4444] rounded-sm" />
            <div className="w-2 h-2 bg-[#F97316] rounded-sm" />
            <div className="w-2 h-2 bg-[#F59E0B] rounded-sm" />
            <div className="w-2 h-2 bg-[#84CC16] rounded-sm" />
            <div className="w-2 h-2 bg-[#10B981] rounded-sm" />
          </div>
          <span>Free Flow</span>
        </div>
      </div>

      {/* Section D - Quick Insights */}
      <div className="mb-8">
        <h3 className="text-sm font-semibold mb-4 text-white">Key insights</h3>
        <div className="space-y-3">
          <div className="card p-4 flex gap-3 items-start border-l-4 border-l-brand-emerald shadow-sm">
            <Clock className="w-5 h-5 text-brand-emerald shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-white">Best time to travel</p>
              <p className="text-xs text-gray-400">11:30 AM – 2:00 PM (weekdays)</p>
            </div>
          </div>
          <div className="card p-4 flex gap-3 items-start border-l-4 border-l-cfi-red shadow-sm">
            <Clock className="w-5 h-5 text-cfi-red shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-white">Worst time to travel</p>
              <p className="text-xs text-gray-400">{segment.peakHour} – {segment.peakHour.replace(/(\d+)/, (m) => String(Number(m) + 2))} (weekdays)</p>
            </div>
          </div>
          <div className="card p-4 flex gap-3 items-start border-l-4 border-l-brand-amber shadow-sm">
            <AlertTriangle className="w-5 h-5 text-brand-amber shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-white">Construction impact</p>
              <p className="text-xs text-gray-400">Active roadwork detected nearby. Adds ~8 min avg delay.</p>
            </div>
          </div>
        </div>
      </div>

      {/* Section E - Compare Button */}
      <button 
        onClick={onCompare}
        className="w-full py-3 border border-brand-amber text-brand-amber rounded-lg font-medium hover:bg-brand-amber hover:text-brand-bg transition-colors cursor-pointer shadow-sm"
      >
        + Compare with another segment
      </button>
    </div>
  );
};
export default SegmentDetail;
