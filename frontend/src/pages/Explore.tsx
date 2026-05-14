import React, { useState, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  CalendarDays,
  ZoomIn,
  ZoomOut,
  CloudRain,
  Sun,
  Cloud,
  CloudLightning,
  Snowflake,
  Clock3,
} from "lucide-react";
import { cities, segments } from "../data/mockData";
import MapboxMap, { type TrafficSummary } from "../components/MapboxMap";
import CityOverview from "../components/CityOverview";
import SegmentDetail from "../components/SegmentDetail";
import Toast from "../components/Toast";
import { apiUrl } from "../lib/api";

const DAY_PRESETS = [
  { label: "Today", offsetDays: 0 },
  { label: "Yesterday", offsetDays: -1 },
  { label: "2 days ago", offsetDays: -2 },
] as const;

const TIME_PRESETS = [
  { label: "Morning peak", hour: 8 },
  { label: "Midday", hour: 13 },
  { label: "Evening peak", hour: 18 },
  { label: "Night", hour: 22 },
] as const;

const formatDateInputValue = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const Explore: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const defaultCityId = cities[0]?.id || "pune";
  const cityParam = searchParams.get("city") || defaultCityId;
  const dateParam =
    searchParams.get("date") || new Date().toISOString().split("T")[0];
  const timeParam = Number(searchParams.get("hour"));
  const initialTimeHour =
    Number.isInteger(timeParam) && timeParam >= 0 && timeParam <= 23
      ? timeParam
      : 8;
  const normalizedInitialCityId = cities.some((c) => c.id === cityParam)
    ? cityParam
    : defaultCityId;

  const [selectedCityId, setSelectedCityId] = useState(normalizedInitialCityId);
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(
    null,
  );
  const [timeHour, setTimeHour] = useState<number>(initialTimeHour);
  const [selectedDate, setSelectedDate] = useState<string>(dateParam);
  const [showToast, setShowToast] = useState(false);

  const [weather, setWeather] = useState<{
    condition: string;
    temperature: number;
    precipitation: number;
  } | null>(null);
  const [trafficSummary, setTrafficSummary] = useState<TrafficSummary | null>(
    null,
  );

  // Clear selected segment when city changes
  React.useEffect(() => {
    setSelectedSegmentId(null);
  }, [selectedCityId]);

  const handleCityChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newCity = e.target.value;
    setSelectedCityId(newCity);
    setSelectedSegmentId(null);
  };

  React.useEffect(() => {
    setSearchParams(
      {
        city: selectedCityId,
        date: selectedDate,
        hour: String(timeHour),
      },
      { replace: true },
    );
  }, [selectedCityId, selectedDate, timeHour, setSearchParams]);

  const city = useMemo(
    () => cities.find((c) => c.id === selectedCityId) || cities[0],
    [selectedCityId],
  );
  const selectedSegment = useMemo(
    () => segments.find((s) => s.id === selectedSegmentId),
    [selectedSegmentId],
  );

  const formatTime = (hour: number) => {
    const ampm = hour >= 12 ? "PM" : "AM";
    const h = hour % 12 || 12;
    return `${h.toString().padStart(2, "0")}:00 ${ampm}`;
  };

  const selectedDateLabel = useMemo(() => {
    const parsed = new Date(`${selectedDate}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return selectedDate;
    return parsed.toLocaleDateString("en-IN", {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }, [selectedDate]);

  const applyDayPreset = (offsetDays: number) => {
    const date = new Date();
    date.setHours(0, 0, 0, 0);
    date.setDate(date.getDate() + offsetDays);
    setSelectedDate(formatDateInputValue(date));
  };

  React.useEffect(() => {
    const fetchWeather = async () => {
      try {
        const [year, month, day] = selectedDate.split("-").map(Number);
        const targetTime = new Date(year, month - 1, day, timeHour, 0, 0);
        const dateStr = targetTime.toISOString().split(".")[0];

        const res = await fetch(
          apiUrl(`/api/weather/${dateStr}?city=${selectedCityId}`),
        );
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
      case "Rain":
        return <CloudRain className="w-5 h-5 text-blue-400" />;
      case "Clear":
        return <Sun className="w-5 h-5 text-yellow-400" />;
      case "Cloudy":
        return <Cloud className="w-5 h-5 text-gray-400" />;
      case "Fog":
        return <Cloud className="w-5 h-5 text-gray-300" />;
      case "Thunderstorm":
        return <CloudLightning className="w-5 h-5 text-purple-400" />;
      case "Snow":
        return <Snowflake className="w-5 h-5 text-white" />;
      default:
        return <Cloud className="w-5 h-5 text-gray-400" />;
    }
  };

  return (
    <div className="flex flex-1 items-stretch overflow-hidden h-[calc(100vh-64px)]">
      {/* Map Panel */}
      <div className="flex-1 w-full md:w-[65%] h-[calc(100vh-64px)] min-h-0 relative border-r border-gray-300 flex flex-col bg-[#f1ede0]">
        <div className="absolute top-4 left-4 right-16 z-10 max-w-[min(30rem,calc(100%-5rem))]">
          <div className="rounded-2xl border border-[#d8d1c1] bg-white/96 p-3 shadow-[0_18px_50px_rgba(31,24,11,0.16)] backdrop-blur">
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-2 sm:flex-row">
                <label className="flex-1">
                  <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.22em] text-[#7a6c54]">
                    City
                  </span>
                  <select
                    value={selectedCityId}
                    onChange={handleCityChange}
                    className="block w-full rounded-xl border border-[#e8e0cf] bg-[#fcfaf4] px-3 py-2.5 text-sm font-medium text-gray-800 outline-none transition focus:border-brand-amber"
                  >
                    {cities.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="sm:w-[12.5rem]">
                  <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.22em] text-[#7a6c54]">
                    Date
                  </span>
                  <div className="flex items-center gap-2 rounded-xl border border-[#e8e0cf] bg-[#fcfaf4] px-3 py-2.5">
                    <CalendarDays className="h-4 w-4 text-[#9b875d]" />
                    <input
                      type="date"
                      value={selectedDate}
                      max={formatDateInputValue(new Date())}
                      onChange={(e) => setSelectedDate(e.target.value)}
                      className="w-full bg-transparent text-sm font-medium text-gray-800 outline-none [color-scheme:light]"
                    />
                  </div>
                </label>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {DAY_PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => applyDayPreset(preset.offsetDays)}
                    className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                      selectedDate ===
                      formatDateInputValue(
                        new Date(
                          new Date().setDate(new Date().getDate() + preset.offsetDays),
                        ),
                      )
                        ? "border-[#b98a2d] bg-[#1f1a10] text-[#f5d48b]"
                        : "border-[#e8e0cf] bg-[#fcfaf4] text-[#6f5f42] hover:border-[#d6c5a7]"
                    }`}
                  >
                    {preset.label}
                  </button>
                ))}
                <span className="ml-auto rounded-full bg-[#f3ecdf] px-3 py-1.5 text-xs font-medium text-[#6f5f42]">
                  {selectedDateLabel}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="absolute top-4 right-4 z-10 flex flex-col gap-2">
          <button className="p-2 bg-white border border-gray-200 rounded-lg text-gray-500 hover:text-gray-800 shadow-md">
            <ZoomIn className="w-5 h-5" />
          </button>
          <button className="p-2 bg-white border border-gray-200 rounded-lg text-gray-500 hover:text-gray-800 shadow-md">
            <ZoomOut className="w-5 h-5" />
          </button>
        </div>

        <div className="absolute bottom-24 left-4 z-10 bg-white/95 backdrop-blur border border-gray-200 p-3 rounded-lg shadow-lg">
          <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">
            Congestion Legend
          </p>
          <div className="space-y-1 text-[10px] text-gray-700">
            <div className="flex items-center gap-2">
              <div
                className="w-4 h-3 rounded"
                style={{ backgroundColor: "#00C700" }}
              />
              <span>Free</span>
            </div>
            <div className="flex items-center gap-2">
              <div
                className="w-4 h-3 rounded border border-gray-300"
                style={{ backgroundColor: "#FFFF00" }}
              />
              <span>Moderate</span>
            </div>
            <div className="flex items-center gap-2">
              <div
                className="w-4 h-3 rounded"
                style={{ backgroundColor: "#FF9900" }}
              />
              <span>Heavy</span>
            </div>
            <div className="flex items-center gap-2">
              <div
                className="w-4 h-3 rounded"
                style={{ backgroundColor: "#FF0000" }}
              />
              <span>Severe</span>
            </div>
            <div className="flex items-center gap-2">
              <div
                className="w-4 h-3 rounded"
                style={{ backgroundColor: "#a0a0b0" }}
              />
              <span>Unknown</span>
            </div>
          </div>
        </div>

        {/* Map Area */}
        <div className="flex-1 w-full h-full min-h-0 relative">
          <MapboxMap
            city={city}
            cityId={city.id}
            knownCities={cities}
            onViewportCityChange={setSelectedCityId}
            selectedSegmentId={selectedSegmentId}
            onSegmentClick={setSelectedSegmentId}
            timeHour={timeHour}
            selectedDate={selectedDate}
            onSummaryLoaded={setTrafficSummary}
          />
        </div>

        {/* Time Slider */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-[86%] max-w-xl bg-white/95 backdrop-blur border border-gray-200 p-4 rounded-2xl shadow-2xl flex flex-col gap-3">
          {/* Weather Widget */}
          {weather && (
            <div className="absolute -top-14 right-0 bg-white/95 backdrop-blur border border-gray-200 p-2 px-4 rounded-lg shadow-lg flex items-center gap-3 text-sm text-gray-700">
              {getWeatherIcon(weather.condition)}
              <div className="flex flex-col">
                <span className="font-bold text-gray-800">
                  {weather.temperature}°C
                </span>
                <span className="text-[10px] text-gray-500">
                  {weather.condition}{" "}
                  {weather.precipitation > 0
                    ? `(${weather.precipitation}mm)`
                    : ""}
                </span>
              </div>
            </div>
          )}

          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2 text-gray-600">
              <Clock3 className="h-4 w-4 text-[#9b875d]" />
              <span>Viewing traffic at</span>
            </div>
            <span className="rounded-full bg-[#f4ede1] px-3 py-1 text-sm font-bold text-gray-800">
              {formatTime(timeHour)}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {TIME_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => setTimeHour(preset.hour)}
                className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                  timeHour === preset.hour
                    ? "border-[#b98a2d] bg-[#1f1a10] text-[#f5d48b]"
                    : "border-gray-200 bg-[#faf7f0] text-gray-600 hover:border-[#d6c5a7]"
                }`}
              >
                {preset.label}
              </button>
            ))}
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
