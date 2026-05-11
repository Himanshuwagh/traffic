import React from 'react';

interface CFIScoreBadgeProps {
  score: number;
  size?: 'sm' | 'md' | 'lg';
}

const getCFIColor = (score: number) => {
  if (score >= 80) return 'bg-[#EF4444]'; // Red
  if (score >= 60) return 'bg-[#F97316]'; // Orange
  if (score >= 40) return 'bg-[#F59E0B]'; // Amber
  if (score >= 20) return 'bg-[#84CC16]'; // Lime
  return 'bg-[#10B981]'; // Green
};

const CFIScoreBadge: React.FC<CFIScoreBadgeProps> = ({ score, size = 'md' }) => {
  const sizeClasses = {
    sm: 'w-6 h-6 text-xs',
    md: 'w-8 h-8 text-sm',
    lg: 'w-12 h-12 text-lg',
  };

  return (
    <div 
      className={`${sizeClasses[size]} ${getCFIColor(score)} rounded-full flex items-center justify-center font-bold text-white shadow-sm shrink-0`}
    >
      {score}
    </div>
  );
};

export default CFIScoreBadge;
