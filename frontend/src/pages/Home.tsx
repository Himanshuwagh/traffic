import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Map as MapIcon, BarChart2 } from 'lucide-react';

const Home: React.FC = () => {
  const navigate = useNavigate();

  const handleCitySelect = (cityId: string) => {
    navigate(`/explore?city=${cityId}`);
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    navigate('/explore?city=bengaluru');
  };

  const cities = ['Bengaluru', 'Pune', 'Mumbai', 'Delhi', 'Hyderabad', 'Chennai'];

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-4 py-12 relative overflow-hidden">
      {/* Background decoration */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-brand-amber/5 rounded-full blur-3xl pointer-events-none" />

      <div className="text-center z-10 max-w-3xl mb-12">
        <h1 className="text-5xl md:text-6xl font-bold tracking-tight mb-6">
          India's road congestion, <span className="text-brand-amber">decoded.</span>
        </h1>
        <p className="text-xl text-gray-400 max-w-2xl mx-auto">
          Explore historical traffic patterns for any road in Bengaluru, Pune, Mumbai, Delhi and more.
        </p>
      </div>

      <div className="w-full max-w-2xl z-10 mb-8">
        <form onSubmit={handleSearch} className="relative">
          <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
            <Search className="h-5 w-5 text-gray-400" />
          </div>
          <input
            type="text"
            className="block w-full pl-12 pr-4 py-4 bg-brand-card border border-brand-border rounded-full text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-amber focus:border-transparent transition-all shadow-lg text-lg"
            placeholder="Search a city, road, or area..."
          />
        </form>
        
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          {cities.map(city => (
            <button
              key={city}
              onClick={() => handleCitySelect(city.toLowerCase())}
              className="px-4 py-2 bg-brand-card/50 border border-brand-border rounded-full text-sm font-medium hover:border-brand-amber hover:text-brand-amber transition-colors"
            >
              {city}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full max-w-5xl z-10 mt-12">
        {[
          { label: 'Road segments analysed', value: '12,847' },
          { label: 'Cities covered', value: '6' },
          { label: 'Data points processed', value: '2.4M' },
        ].map((stat, i) => (
          <div key={i} className="card p-6 text-center">
            <p className="text-3xl font-bold text-white mb-2">{stat.value}</p>
            <p className="text-sm text-gray-400 uppercase tracking-wider">{stat.label}</p>
          </div>
        ))}
      </div>

      <div className="w-full max-w-5xl z-10 mt-24">
        <h2 className="text-2xl font-semibold text-center mb-12">How it works</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-12">
          <div className="text-center">
            <div className="w-16 h-16 mx-auto bg-brand-card border border-brand-border rounded-2xl flex items-center justify-center mb-6">
              <Search className="h-8 w-8 text-brand-amber" />
            </div>
            <h3 className="text-lg font-medium mb-2">1. Search</h3>
            <p className="text-gray-400 text-sm leading-relaxed">Search any city or specific road segment you want to analyze.</p>
          </div>
          <div className="text-center">
            <div className="w-16 h-16 mx-auto bg-brand-card border border-brand-border rounded-2xl flex items-center justify-center mb-6">
              <MapIcon className="h-8 w-8 text-brand-emerald" />
            </div>
            <h3 className="text-lg font-medium mb-2">2. View Heatmap</h3>
            <p className="text-gray-400 text-sm leading-relaxed">See historical congestion frequency scores visually on the map.</p>
          </div>
          <div className="text-center">
            <div className="w-16 h-16 mx-auto bg-brand-card border border-brand-border rounded-2xl flex items-center justify-center mb-6">
              <BarChart2 className="h-8 w-8 text-cfi-orange" />
            </div>
            <h3 className="text-lg font-medium mb-2">3. Drill Down</h3>
            <p className="text-gray-400 text-sm leading-relaxed">Drill into segment-level hourly patterns and peak delay analytics.</p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Home;
