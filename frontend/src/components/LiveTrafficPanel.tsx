import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Database, Zap, CheckCircle, AlertCircle, Clock } from 'lucide-react';
import { apiUrl } from '../lib/api';

interface FetchStats {
  fetched: number;
  failed: number;
  skipped?: number;
  snapshot_time?: string;
  city?: string;
  error?: string;
}

interface LatestStats {
  total_records: number;
  latest_snapshot: string | null;
  earliest_snapshot: string | null;
  unique_segments: number;
  avg_speed: number | null;
  city: string;
  error?: string;
}

interface LiveTrafficPanelProps {
  cityId: string;
  onFetchComplete?: () => void;
}

const LiveTrafficPanel: React.FC<LiveTrafficPanelProps> = ({ cityId, onFetchComplete }) => {
  const [isFetching, setIsFetching] = useState(false);
  const [lastFetch, setLastFetch] = useState<FetchStats | null>(null);
  const [dbStats, setDbStats] = useState<LatestStats | null>(null);
  const [segmentLimit, setSegmentLimit] = useState(50);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const loadDbStats = useCallback(async () => {
    try {
      const res = await fetch(apiUrl(`/api/traffic/latest?city=${encodeURIComponent(cityId)}`));
      const data = await res.json();
      if (!data.error) setDbStats(data);
    } catch {
      // silently ignore
    }
  }, [cityId]);

  useEffect(() => {
    loadDbStats();
  }, [loadDbStats]);

  const handleFetch = async () => {
    setIsFetching(true);
    setFetchError(null);
    setLastFetch(null);
    try {
      const res = await fetch(
        apiUrl(`/api/traffic/fetch?city=${encodeURIComponent(cityId)}&limit=${segmentLimit}`),
        { method: 'POST' }
      );
      const data: FetchStats = await res.json();
      if (data.error) {
        setFetchError(data.error);
      } else {
        setLastFetch(data);
        await loadDbStats();
        onFetchComplete?.();
      }
    } catch (e) {
      setFetchError('Network error — is the backend running?');
    } finally {
      setIsFetching(false);
    }
  };

  const formatTime = (iso: string | null) => {
    if (!iso) return 'N/A';
    const d = new Date(iso);
    return d.toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' });
  };

  const timeSince = (iso: string | null) => {
    if (!iso) return null;
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  };

  return (
    <div className="card p-5 mb-6 border border-brand-border">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-brand-amber" />
          <h3 className="text-sm font-semibold text-white">Manual Traffic Ingest</h3>
        </div>
        <span className="text-[10px] text-gray-500 bg-brand-bg px-2 py-0.5 rounded-full border border-brand-border">
          TomTom API
        </span>
      </div>

      {/* DB Stats */}
      {dbStats && (
        <div className="grid grid-cols-2 gap-2 mb-4">
          <div className="bg-brand-bg rounded-lg p-3 border border-brand-border">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Records stored</p>
            <p className="text-lg font-bold text-white">{Number(dbStats.total_records).toLocaleString()}</p>
          </div>
          <div className="bg-brand-bg rounded-lg p-3 border border-brand-border">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Segments observed</p>
            <p className="text-lg font-bold text-white">{Number(dbStats.unique_segments).toLocaleString()}</p>
          </div>
          <div className="bg-brand-bg rounded-lg p-3 border border-brand-border">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Avg speed stored</p>
            <p className="text-lg font-bold text-white">
              {dbStats.avg_speed != null ? `${dbStats.avg_speed} km/h` : 'N/A'}
            </p>
          </div>
          <div className="bg-brand-bg rounded-lg p-3 border border-brand-border">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Last snapshot</p>
            <p className="text-sm font-semibold text-white flex items-center gap-1">
              <Clock className="w-3 h-3 text-gray-400" />
              {timeSince(dbStats.latest_snapshot) ?? 'None yet'}
            </p>
          </div>
        </div>
      )}

      {dbStats && dbStats.earliest_snapshot && (
        <div className="text-[10px] text-gray-500 mb-4 flex items-center gap-1.5">
          <Database className="w-3 h-3" />
          History: {formatTime(dbStats.earliest_snapshot)} → {formatTime(dbStats.latest_snapshot)}
        </div>
      )}

      {/* Controls */}
      <div className="flex items-center gap-3 mb-3">
        <div className="flex-1">
          <label className="text-[10px] text-gray-500 uppercase tracking-wider mb-1 block">
            Request size
          </label>
          <select
            value={segmentLimit}
            onChange={(e) => setSegmentLimit(Number(e.target.value))}
            disabled={isFetching}
            className="w-full bg-brand-bg border border-brand-border text-white text-sm rounded-lg p-2 outline-none focus:border-brand-amber cursor-pointer disabled:opacity-50"
          >
            <option value={25}>Small ingest</option>
            <option value={50}>Medium ingest</option>
            <option value={100}>Large ingest</option>
            <option value={200}>Extended ingest</option>
          </select>
        </div>
        <button
          onClick={handleFetch}
          disabled={isFetching}
          className="mt-5 flex items-center gap-2 px-4 py-2 bg-brand-amber text-brand-bg font-semibold text-sm rounded-lg hover:bg-yellow-400 transition-colors disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer whitespace-nowrap"
        >
          <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
          {isFetching ? 'Fetching…' : 'Fetch Now'}
        </button>
      </div>

      {/* Result */}
      {isFetching && (
        <div className="flex items-center gap-2 text-sm text-gray-400 mt-2">
          <RefreshCw className="w-3.5 h-3.5 animate-spin text-brand-amber" />
          Running TomTom discovery ingest for this city…
        </div>
      )}

      {lastFetch && !isFetching && (
        <div className="flex items-start gap-2 mt-2 text-sm bg-green-900/20 border border-green-800/40 rounded-lg p-3">
          <CheckCircle className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-green-300 font-medium">Ingest complete</p>
            <p className="text-green-400/80 text-xs mt-0.5">
              {lastFetch.fetched} observations stored &bull; {lastFetch.failed} failed
              {lastFetch.skipped ? ` · ${lastFetch.skipped} skipped` : ''}
            </p>
          </div>
        </div>
      )}

      {fetchError && !isFetching && (
        <div className="flex items-start gap-2 mt-2 text-sm bg-red-900/20 border border-red-800/40 rounded-lg p-3">
          <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-red-300 font-medium">Fetch failed</p>
            <p className="text-red-400/80 text-xs mt-0.5">{fetchError}</p>
          </div>
        </div>
      )}

      <p className="text-[10px] text-gray-600 mt-3 leading-relaxed">
        Fetches real-time speed &amp; travel time from TomTom for each road segment's midpoint.
        Data is stored in Supabase for historical trend analysis.
      </p>
    </div>
  );
};

export default LiveTrafficPanel;
