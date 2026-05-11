import React, { useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ZoomIn, ZoomOut, CloudRain, Sun, Cloud, CloudLightning, Snowflake } from 'lucide-react';
import { cities, segments } from '../data/mockData';
import MapboxMap, { type TrafficSummary } from '../components/MapboxMap';
import CityOverview from '../components/CityOverview';
import SegmentDetail from '../components/SegmentDetail';
import Toast from '../components/Toast';
import { apiUrl } from '../lib/api';

const Explore: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const cityParam = searchParams.get('city') || 'bengaluru';
  
  const [selectedCityId, setSelectedCityId] = useState(cityParam);
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null);
  const [timeHour, setTimeHour] = useState<number>(8);
  const [selectedDate, setSelectedDate] = useState<string>(new Date().toISOString().split('T')[0]);
  const [showToast, setShowToast] = useState(false);
  
  const [weather, setWeather] = useState<{ condition: string; temperature: number; precipitation: number } | null>(null);
  const [trafficSummary, setTrafficSummary] = useState<TrafficSummary | null>(null);

  // Auto-select Silk Board Junction for Bengaluru demo
  React.useEffect(() => {
    if (selectedCityId === 'bengaluru' && !selectedSegmentId) {
      setSelectedSegmentId('blr-2'); // Silk Board
    }
  }, [selectedCityId]);

  const handleCityChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newCity = e.target.value;
    setSelectedCityId(newCity);
    setSelectedSegmentId(null);
    setSearchParams({ city: newCity });
  };

  const city = useMemo(() => cities.find(c => c.id === selectedCityId) || cities[0], [selectedCityId]);
  const selectedSegment = useMemo(() => segments.find(s => s.id === selectedSegmentId), [selectedSegmentId]);

  const formatTime = (hour: number) => {
    const ampm = hour >= 12 ? 'PM' : 'AM';
    const h = hour % 12 || 12;
    return `${h.toString().padStart(2, '0')}:00 ${ampm}`;
  };

  React.useEffect(() => {
    const fetchWeather = async () => {
      try {
        const [year, month, day] = selectedDate.split('-').map(Number);
        const targetTime = new Date(year, month - 1, day, timeHour, 0, 0);
        const dateStr = targetTime.toISOString().split('.')[0];
        
        const res = await fetch(apiUrl(`/api/weather/${dateStr}?city=${selectedCityId}`));
        const data = await res.json();
        if (!data.error) {
          setWeather(data);
        } else {
          setWeather(null);
        }
      } catch (e) {
        setWeather(null);
      }
    };
    fetchWeather();
  }, [selectedDate, timeHour, selectedCityId]);

  const getWeatherIcon = (condition: string) => {
    switch (condition) {
      case 'Rain': return <CloudRain className="w-5 h-5 text-blue-400" />;
      case 'Clear': return <Sun className="w-5 h-5 text-yellow-400" />;
      case 'Cloudy': return <Cloud className="w-5 h-5 text-gray-400" />;
      case 'Fog': return <Cloud className="w-5 h-5 text-gray-300" />;
      case 'Thunderstorm': return <CloudLightning className="w-5 h-5 text-purple-400" />;
      case 'Snow': return <Snowflake className="w-5 h-5 text-white" />;
      default: return <Cloud className="w-5 h-5 text-gray-400" />;
    }
  };

  return (
    <div className="flex flex-1 items-stretch overflow-hidden h-[calc(100vh-64px)]">
      {/* Map Panel */}
      <div className="flex-1 w-full md:w-[65%] h-[calc(100vh-64px)] min-h-0 relative border-r border-brand-border flex flex-col bg-[#0b0c10]">
        <div className="absolute top-4 left-4 z-10 flex gap-2">
          <select 
            value={selectedCityId}
            onChange={handleCityChange}
            className="bg-brand-card border border-brand-border text-white text-sm rounded-lg focus:ring-brand-amber focus:border-brand-amber block w-48 p-2.5 outline-none shadow-lg cursor-pointer"
          >
            {cities.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <input 
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="bg-brand-card border border-brand-border text-white text-sm rounded-lg focus:ring-brand-amber focus:border-brand-amber block w-40 p-2.5 outline-none shadow-lg cursor-pointer [color-scheme:dark]"
          />
        </div>

        <div className="absolute top-4 right-4 z-10 flex flex-col gap-2">
          <button className="p-2 bg-brand-card border border-brand-border rounded-lg text-gray-400 hover:text-white shadow-lg">
            <ZoomIn className="w-5 h-5" />
          </button>
          <button className="p-2 bg-brand-card border border-brand-border rounded-lg text-gray-400 hover:text-white shadow-lg">
            <ZoomOut className="w-5 h-5" />
          </button>
        </div>

        <div className="absolute bottom-24 left-4 z-10 bg-brand-card/90 backdrop-blur border border-brand-border p-3 rounded-lg shadow-lg">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Traffic Legend</p>
          <div className="space-y-1 text-[10px] text-gray-300">
            <div className="flex items-center gap-2">
              <div className="w-4 h-3 rounded" style={{ backgroundColor: '#00C700' }} />
              <span>Free (≥40 km/h)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-3 rounded" style={{ backgroundColor: '#FFFF00' }} />
              <span>Moderate (25-40 km/h)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-3 rounded" style={{ backgroundColor: '#FF9900' }} />
              <span>Heavy (15-25 km/h)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-3 rounded" style={{ backgroundColor: '#FF0000' }} />
              <span>Congested ({'<'}15 km/h)</span>
            </div>
          </div>
        </div>
        
        {/* Map Area */}
        <div className="flex-1 w-full h-full min-h-0 relative">
          <MapboxMap 
            city={city}
            cityId={city.id}
            selectedSegmentId={selectedSegmentId} 
            onSegmentClick={setSelectedSegmentId}
            timeHour={timeHour}
            selectedDate={selectedDate}
            onSummaryLoaded={setTrafficSummary}
          />
        </div>

        {/* Time Slider */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-[80%] max-w-md bg-brand-card/90 backdrop-blur border border-brand-border p-4 rounded-xl shadow-2xl flex flex-col gap-2">
          
          {/* Weather Widget */}
          {weather && (
            <div className="absolute -top-14 right-0 bg-brand-card/90 backdrop-blur border border-brand-border p-2 px-4 rounded-lg shadow-lg flex items-center gap-3 text-sm text-gray-200">
              {getWeatherIcon(weather.condition)}
              <div className="flex flex-col">
                <span className="font-bold">{weather.temperature}°C</span>
                <span className="text-[10px] text-gray-400">{weather.condition} {weather.precipitation > 0 ? `(${weather.precipitation}mm)` : ''}</span>
              </div>
            </div>
          )}

          <div className="flex justify-between items-center text-sm">
            <span className="text-gray-300">Viewing traffic at:</span>
            <span className="font-bold text-white bg-gray-800 px-2 py-1 rounded">{formatTime(timeHour)}</span>
          </div>
          <input 
            type="range" 
            className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-brand-amber" 
            min="0" 
            max="23" 
            value={timeHour}
            onChange={(e) => setTimeHour(Number(e.target.value))}
          />
        </div>
      </div>

      {/* Analytics Sidebar */}
      <div className="hidden md:block w-[35%] h-[calc(100vh-64px)] min-h-0 overflow-y-auto bg-brand-bg p-6 scroll-smooth">
        {selectedSegment ? (
          <SegmentDetail 
            segment={selectedSegment} 
            onBack={() => setSelectedSegmentId(null)}
            onCompare={() => setShowToast(true)}
          />
        ) : (
          <CityOverview 
            city={city} 
            summary={trafficSummary}
            onSegmentClick={setSelectedSegmentId} 
          />
        )}
      </div>

      <Toast 
        isVisible={showToast} 
        message="Comparison feature coming soon!" 
        onClose={() => setShowToast(false)} 
      />
    </div>
  );
};

export default Explore;
