import React from 'react';

const About: React.FC = () => {
  return (
    <div className="max-w-3xl mx-auto px-4 py-16">
      <h1 className="text-4xl font-bold mb-8">About TrafficLens</h1>
      
      <div className="space-y-8 text-gray-300 leading-relaxed">
        <section>
          <h2 className="text-2xl font-semibold text-white mb-4">What is TrafficLens?</h2>
          <p>
            TrafficLens is an India-focused urban traffic history intelligence platform. 
            We provide deep analytics into congestion patterns across major Indian cities, 
            helping urban planners, logistics companies, and commuters make data-driven decisions.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold text-white mb-4">How CFI is calculated</h2>
          <p>
            The Congestion Frequency Index (CFI) is a normalized score from 0 to 100. 
            We collect continuous speed data for road segments and compare it against the 
            free-flow speed (speed limit or night-time average). The frequency and severity 
            of delays determine the final CFI score.
          </p>
          <ul className="list-disc pl-6 mt-4 space-y-2">
            <li><strong className="text-white">80-100 (Red):</strong> Severe, daily congestion</li>
            <li><strong className="text-white">60-79 (Orange):</strong> Frequent heavy traffic</li>
            <li><strong className="text-white">40-59 (Amber):</strong> Moderate delays during peak hours</li>
            <li><strong className="text-white">20-39 (Lime):</strong> Occasional minor slow-downs</li>
            <li><strong className="text-white">0-19 (Green):</strong> Free-flowing traffic</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold text-white mb-4">Data Sources</h2>
          <ul className="list-disc pl-6 space-y-2">
            <li>Google Maps Roads API</li>
            <li>OpenStreetMap</li>
            <li>iRAD Accident Database</li>
            <li>IMD Weather Data</li>
            <li>MapmyIndia (Future integration)</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold text-white mb-4">Built for India</h2>
          <p>
            Indian traffic patterns are unique—featuring mixed vehicle types, informal junctions, 
            and seasonal impacts like monsoons. TrafficLens is built specifically to model these 
            anomalies and provide actionable insights for developing infrastructure.
          </p>
        </section>
      </div>
    </div>
  );
};

export default About;
