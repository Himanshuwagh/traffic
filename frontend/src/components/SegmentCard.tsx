import React from 'react';
import CFIScoreBadge from './CFIScoreBadge';

interface SegmentCardProps {
  rank?: number;
  name: string;
  city?: string;
  cfi: number;
  statLabel: string;
  statValue: string;
  onClick: () => void;
  isActive?: boolean;
}

const SegmentCard: React.FC<SegmentCardProps> = ({ 
  rank, 
  name, 
  city,
  cfi, 
  statLabel, 
  statValue, 
  onClick,
  isActive = false
}) => {
  return (
    <div 
      onClick={onClick}
      className={`card p-3 flex items-center gap-4 cursor-pointer transition-colors ${
        isActive ? 'border-brand-amber bg-brand-card/80' : 'hover:border-brand-amber hover:bg-brand-card/50'
      }`}
    >
      {rank !== undefined && (
        <span className="text-brand-amber font-bold w-4 text-center">{rank}</span>
      )}
      
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate text-white">{name}</p>
        <p className="text-xs text-gray-400">
          {city && <span className="mr-2">{city} &bull;</span>}
          {statLabel}: {statValue}
        </p>
      </div>
      
      <CFIScoreBadge score={cfi} size="sm" />
    </div>
  );
};

export default SegmentCard;
