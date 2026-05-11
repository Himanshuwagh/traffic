import React, { useState, useMemo } from 'react';
import { Search, ArrowUpDown, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { segments } from '../data/mockData';
import CFIScoreBadge from '../components/CFIScoreBadge';

type SortConfig = { key: keyof typeof segments[0] | ''; direction: 'asc' | 'desc' };

const Rankings: React.FC = () => {
  const [cityFilter, setCityFilter] = useState('All');
  const [typeFilter, setTypeFilter] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');
  const [cfiRange, setCfiRange] = useState<number>(0);
  
  const [sortConfig, setSortConfig] = useState<SortConfig>({ key: 'cfi', direction: 'desc' });

  const filteredData = useMemo(() => {
    return segments.filter(seg => {
      const matchCity = cityFilter === 'All' || seg.city.toLowerCase() === cityFilter.toLowerCase();
      const matchType = typeFilter === 'All' || seg.type.toLowerCase() === typeFilter.toLowerCase();
      const matchCFI = seg.cfi >= cfiRange;
      const matchSearch = seg.name.toLowerCase().includes(searchQuery.toLowerCase());
      return matchCity && matchType && matchCFI && matchSearch;
    }).sort((a, b) => {
      if (!sortConfig.key) return 0;
      const aVal = a[sortConfig.key];
      const bVal = b[sortConfig.key];
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [cityFilter, typeFilter, searchQuery, cfiRange, sortConfig]);

  const handleSort = (key: keyof typeof segments[0]) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  const renderTrend = (trend: number) => {
    if (trend > 0) return <span className="flex items-center text-cfi-red gap-1" title="Worse this month"><TrendingUp className="w-3 h-3"/> {trend}%</span>;
    if (trend < 0) return <span className="flex items-center text-brand-emerald gap-1" title="Improved this month"><TrendingDown className="w-3 h-3"/> {Math.abs(trend)}%</span>;
    return <span className="flex items-center text-gray-500 gap-1"><Minus className="w-3 h-3"/> 0%</span>;
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 w-full flex-1">
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2 text-white">India Traffic Bottleneck Rankings</h1>
        <p className="text-gray-400">Road segments ranked by Congestion Frequency Index (CFI). Updated weekly.</p>
      </div>
      
      {/* Filters */}
      <div className="flex flex-wrap gap-4 mb-6 bg-brand-card p-4 rounded-xl border border-brand-border shadow-sm">
        <select 
          value={cityFilter} onChange={e => setCityFilter(e.target.value)}
          className="bg-[#0F1117] border border-brand-border text-sm rounded-lg p-2.5 outline-none text-white focus:border-brand-amber cursor-pointer"
        >
          <option value="All">All Cities</option>
          <option value="Bengaluru">Bengaluru</option>
          <option value="Pune">Pune</option>
          <option value="Mumbai">Mumbai</option>
          <option value="Delhi">Delhi</option>
          <option value="Hyderabad">Hyderabad</option>
          <option value="Chennai">Chennai</option>
        </select>

        <select 
          value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
          className="bg-[#0F1117] border border-brand-border text-sm rounded-lg p-2.5 outline-none text-white focus:border-brand-amber cursor-pointer"
        >
          <option value="All">All Types</option>
          <option value="highway">Highway</option>
          <option value="arterial">Arterial</option>
          <option value="junction">Junction</option>
          <option value="local">Local</option>
        </select>

        <div className="flex items-center gap-3 bg-[#0F1117] border border-brand-border rounded-lg px-4 flex-1 min-w-[200px]">
          <span className="text-sm text-gray-400 whitespace-nowrap">Min CFI: {cfiRange}</span>
          <input 
            type="range" min="0" max="100" value={cfiRange} onChange={e => setCfiRange(Number(e.target.value))}
            className="w-full accent-brand-amber cursor-pointer h-2 bg-gray-700 rounded-lg appearance-none"
          />
        </div>

        <div className="relative flex-1 min-w-[250px]">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
            <Search className="h-4 w-4 text-gray-400" />
          </div>
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="block w-full pl-10 pr-3 py-2.5 bg-[#0F1117] border border-brand-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-brand-amber text-sm transition-colors"
            placeholder="Search road name..."
          />
        </div>
      </div>

      <div className="mb-4 text-sm text-gray-400 font-medium">
        Showing {filteredData.length} segments
      </div>
      
      {/* Table */}
      <div className="bg-brand-card rounded-xl border border-brand-border overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left text-gray-300">
            <thead className="text-xs uppercase bg-[#0F1117] text-gray-400 border-b border-brand-border">
              <tr>
                <th className="px-6 py-4 font-semibold text-brand-amber">Rank</th>
                {[
                  { key: 'name', label: 'Road Segment' },
                  { key: 'city', label: 'City' },
                  { key: 'type', label: 'Road Type' },
                  { key: 'cfi', label: 'CFI Score' },
                  { key: 'peakHour', label: 'Peak Hour' },
                  { key: 'peakDelay', label: 'Avg Delay' },
                  { key: 'trend', label: 'Trend' },
                ].map(({ key, label }) => (
                  <th 
                    key={key} 
                    onClick={() => handleSort(key as any)}
                    className="px-6 py-4 font-semibold cursor-pointer hover:text-white transition-colors group select-none"
                  >
                    <div className="flex items-center gap-1">
                      {label}
                      <ArrowUpDown className={`w-3 h-3 ${sortConfig.key === key ? 'text-brand-amber' : 'opacity-0 group-hover:opacity-50 transition-opacity'}`} />
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredData.length > 0 ? (
                filteredData.map((seg, idx) => (
                  <tr key={seg.id} className="border-b border-brand-border/50 hover:bg-white/5 transition-colors cursor-pointer group">
                    <td className="px-6 py-4 font-bold text-brand-amber">{idx + 1}</td>
                    <td className="px-6 py-4 font-medium text-white group-hover:text-brand-amber transition-colors">{seg.name}</td>
                    <td className="px-6 py-4">{seg.city}</td>
                    <td className="px-6 py-4 capitalize">{seg.type}</td>
                    <td className="px-6 py-4">
                      <CFIScoreBadge score={seg.cfi} size="sm" />
                    </td>
                    <td className="px-6 py-4">{seg.peakHour}</td>
                    <td className="px-6 py-4">+{seg.peakDelay} min</td>
                    <td className="px-6 py-4">{renderTrend(seg.trend)}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} className="px-6 py-12 text-center text-gray-500">
                    No segments found matching the filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Rankings;
