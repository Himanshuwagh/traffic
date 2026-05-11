export interface City {
  id: string;
  name: string;
  avgCFI: number;
  peakHour: string;
  worstDay: string;
  totalSegments: number;
  topCorridor: string;
  center: [number, number];
  zoom: number;
}

export interface Segment {
  id: string;
  name: string;
  city: string;
  type: 'highway' | 'arterial' | 'junction' | 'local';
  cfi: number;
  avgSpeed: number;
  peakDelay: number;
  peakHour: string;
  accidentCount: number;
  weekdaySpeedProfile: number[];
  weekendSpeedProfile: number[];
  trend: number;
  coordinates: [number, number][];
}

export const cities: City[] = [
  { id: 'bengaluru', name: 'Bengaluru', avgCFI: 63.4, peakHour: '8:45 AM', worstDay: 'Monday', totalSegments: 2450, topCorridor: 'Outer Ring Road (ORR)', center: [77.63, 12.95], zoom: 11.5 },
  { id: 'pune', name: 'Pune', avgCFI: 58.2, peakHour: '9:15 AM', worstDay: 'Tuesday', totalSegments: 1820, topCorridor: 'Pune-Mumbai Highway', center: [73.8567, 18.5204], zoom: 12 },
  { id: 'mumbai', name: 'Mumbai', avgCFI: 68.9, peakHour: '9:00 AM', worstDay: 'Wednesday', totalSegments: 3100, topCorridor: 'Western Express Highway', center: [72.8777, 19.0760], zoom: 11 },
  { id: 'delhi', name: 'Delhi', avgCFI: 65.1, peakHour: '8:30 AM', worstDay: 'Monday', totalSegments: 3800, topCorridor: 'Ring Road', center: [77.1025, 28.7041], zoom: 10.5 },
  { id: 'hyderabad', name: 'Hyderabad', avgCFI: 55.4, peakHour: '9:30 AM', worstDay: 'Thursday', totalSegments: 1650, topCorridor: 'Inner Ring Road', center: [78.4867, 17.3850], zoom: 11.5 },
  { id: 'chennai', name: 'Chennai', avgCFI: 59.8, peakHour: '8:45 AM', worstDay: 'Friday', totalSegments: 1980, topCorridor: 'Anna Salai', center: [80.2707, 13.0827], zoom: 11.5 }
];

export const segments: Segment[] = [
  // Bengaluru
  {
    id: 'blr-1', name: 'Outer Ring Road (Marathahalli stretch)', city: 'Bengaluru', type: 'highway',
    cfi: 91, avgSpeed: 12, peakDelay: 24, peakHour: '8:45 AM', accidentCount: 12,
    weekdaySpeedProfile: [35, 40, 42, 43, 40, 30, 20, 10, 8, 14, 20, 22, 20, 22, 24, 20, 14, 10, 12, 18, 24, 30, 32, 35],
    weekendSpeedProfile: [38, 42, 45, 46, 45, 40, 35, 28, 24, 26, 28, 30, 28, 28, 30, 30, 26, 24, 26, 30, 32, 35, 38, 38],
    trend: 2.5, coordinates: [[77.698, 12.946], [77.695, 12.955], [77.690, 12.965]]
  },
  {
    id: 'blr-2', name: 'Silk Board Junction', city: 'Bengaluru', type: 'junction',
    cfi: 89, avgSpeed: 14, peakDelay: 31, peakHour: '9:00 AM', accidentCount: 7,
    weekdaySpeedProfile: [38, 42, 44, 45, 43, 35, 22, 14, 12, 18, 24, 26, 22, 24, 26, 24, 18, 12, 14, 22, 28, 32, 36, 38],
    weekendSpeedProfile: [40, 44, 46, 47, 46, 44, 38, 30, 26, 28, 30, 32, 30, 30, 32, 32, 28, 26, 28, 32, 36, 38, 40, 40],
    trend: 4.1, coordinates: [[77.622, 12.917], [77.625, 12.918], [77.627, 12.919]]
  },
  { id: 'blr-3', name: 'Hebbal Flyover approach', city: 'Bengaluru', type: 'arterial', cfi: 84, avgSpeed: 18, peakDelay: 19, peakHour: '8:30 AM', accidentCount: 5, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: -1.2, coordinates: [[77.589, 13.042], [77.592, 13.038]] },
  { id: 'blr-4', name: 'KR Puram Bridge', city: 'Bengaluru', type: 'highway', cfi: 82, avgSpeed: 16, peakDelay: 22, peakHour: '9:15 AM', accidentCount: 8, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 0.5, coordinates: [[77.675, 13.003], [77.685, 13.006]] },
  { id: 'blr-5', name: 'Tin Factory Junction', city: 'Bengaluru', type: 'junction', cfi: 79, avgSpeed: 19, peakDelay: 17, peakHour: '8:45 AM', accidentCount: 9, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 1.8, coordinates: [[77.669, 12.997], [77.671, 12.998]] },
  { id: 'blr-6', name: 'Agara Junction (ORR)', city: 'Bengaluru', type: 'junction', cfi: 76, avgSpeed: 21, peakDelay: 14, peakHour: '9:00 AM', accidentCount: 3, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: -0.4, coordinates: [[77.648, 12.923], [77.652, 12.924]] },
  { id: 'blr-7', name: 'Bannerghatta Road (JP Nagar stretch)', city: 'Bengaluru', type: 'arterial', cfi: 74, avgSpeed: 22, peakDelay: 16, peakHour: '6:30 PM', accidentCount: 4, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 1.1, coordinates: [[77.598, 12.912], [77.597, 12.901]] },
  { id: 'blr-8', name: 'Electronic City Flyover entry', city: 'Bengaluru', type: 'highway', cfi: 71, avgSpeed: 24, peakDelay: 12, peakHour: '8:30 AM', accidentCount: 2, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: -2.3, coordinates: [[77.632, 12.905], [77.636, 12.890]] },
  { id: 'blr-9', name: 'Whitefield Main Road', city: 'Bengaluru', type: 'arterial', cfi: 68, avgSpeed: 26, peakDelay: 11, peakHour: '9:30 AM', accidentCount: 6, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 0.8, coordinates: [[77.749, 12.969], [77.747, 12.980]] },
  { id: 'blr-10', name: 'MG Road', city: 'Bengaluru', type: 'arterial', cfi: 55, avgSpeed: 30, peakDelay: 9, peakHour: '7:00 PM', accidentCount: 1, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: -0.9, coordinates: [[77.601, 12.973], [77.611, 12.973]] },

  // Pune
  { id: 'pun-1', name: 'Pune-Mumbai Highway Wakad', city: 'Pune', type: 'highway', cfi: 78, avgSpeed: 28, peakDelay: 18, peakHour: '9:00 AM', accidentCount: 4, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 1.5, coordinates: [[73.765, 18.599], [73.755, 18.605]] },
  { id: 'pun-2', name: 'Katraj Chowk', city: 'Pune', type: 'junction', cfi: 85, avgSpeed: 16, peakDelay: 25, peakHour: '6:30 PM', accidentCount: 8, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 3.2, coordinates: [[73.856, 18.455], [73.858, 18.456]] },
  { id: 'pun-3', name: 'Swargate Bus Stand junction', city: 'Pune', type: 'junction', cfi: 80, avgSpeed: 18, peakDelay: 22, peakHour: '10:00 AM', accidentCount: 10, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 0.5, coordinates: [[73.858, 18.501], [73.859, 18.502]] },
  { id: 'pun-4', name: 'Hinjewadi Phase 1 entry', city: 'Pune', type: 'arterial', cfi: 77, avgSpeed: 20, peakDelay: 20, peakHour: '9:30 AM', accidentCount: 5, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: -1.0, coordinates: [[73.740, 18.591], [73.730, 18.590]] },
  { id: 'pun-5', name: 'FC Road', city: 'Pune', type: 'local', cfi: 62, avgSpeed: 25, peakDelay: 10, peakHour: '7:30 PM', accidentCount: 2, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 0.2, coordinates: [[73.840, 18.520], [73.838, 18.526]] },

  // Mumbai
  { id: 'mum-1', name: 'Eastern Express Highway Thane entry', city: 'Mumbai', type: 'highway', cfi: 88, avgSpeed: 15, peakDelay: 35, peakHour: '8:45 AM', accidentCount: 14, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 2.1, coordinates: [[72.973, 19.191], [72.965, 19.180]] },
  { id: 'mum-2', name: 'Western Express Highway Andheri', city: 'Mumbai', type: 'highway', cfi: 83, avgSpeed: 18, peakDelay: 28, peakHour: '9:15 AM', accidentCount: 11, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 1.8, coordinates: [[72.855, 19.117], [72.853, 19.105]] },
  { id: 'mum-3', name: 'Sion-Panvel Highway', city: 'Mumbai', type: 'highway', cfi: 76, avgSpeed: 24, peakDelay: 20, peakHour: '6:00 PM', accidentCount: 6, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: -0.5, coordinates: [[72.890, 19.040], [72.905, 19.045]] },
  { id: 'mum-4', name: 'Worli Flyover', city: 'Mumbai', type: 'arterial', cfi: 69, avgSpeed: 30, peakDelay: 12, peakHour: '9:30 AM', accidentCount: 3, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: -1.5, coordinates: [[72.815, 19.015], [72.818, 19.025]] },

  // Delhi
  { id: 'del-1', name: 'NH-48 Gurugram toll', city: 'Delhi', type: 'highway', cfi: 86, avgSpeed: 14, peakDelay: 40, peakHour: '9:00 AM', accidentCount: 15, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 3.5, coordinates: [[77.098, 28.502], [77.090, 28.490]] },
  { id: 'del-2', name: 'NH-24 Akshardham', city: 'Delhi', type: 'highway', cfi: 82, avgSpeed: 20, peakDelay: 25, peakHour: '9:30 AM', accidentCount: 9, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 0.8, coordinates: [[77.275, 28.612], [77.285, 28.618]] },
  { id: 'del-3', name: 'Ring Road Ashram', city: 'Delhi', type: 'arterial', cfi: 79, avgSpeed: 22, peakDelay: 22, peakHour: '6:30 PM', accidentCount: 7, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 1.2, coordinates: [[77.260, 28.570], [77.255, 28.565]] },
  
  // Hyderabad
  { id: 'hyd-1', name: 'Ameerpet Junction', city: 'Hyderabad', type: 'junction', cfi: 81, avgSpeed: 17, peakDelay: 26, peakHour: '9:30 AM', accidentCount: 8, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 2.0, coordinates: [[78.448, 17.436], [78.450, 17.435]] },
  { id: 'hyd-2', name: 'Hitec City Main Road', city: 'Hyderabad', type: 'arterial', cfi: 75, avgSpeed: 22, peakDelay: 18, peakHour: '9:00 AM', accidentCount: 4, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 0.5, coordinates: [[78.380, 17.445], [78.385, 17.442]] },
  { id: 'hyd-3', name: 'KPHB Colony', city: 'Hyderabad', type: 'local', cfi: 65, avgSpeed: 28, peakDelay: 12, peakHour: '7:00 PM', accidentCount: 2, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: -0.8, coordinates: [[78.395, 17.495], [78.390, 17.490]] },

  // Chennai
  { id: 'che-1', name: 'Kathipara Junction', city: 'Chennai', type: 'junction', cfi: 85, avgSpeed: 16, peakDelay: 30, peakHour: '8:45 AM', accidentCount: 12, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 2.8, coordinates: [[80.201, 13.008], [80.203, 13.007]] },
  { id: 'che-2', name: 'OMR Sholinganallur', city: 'Chennai', type: 'arterial', cfi: 78, avgSpeed: 24, peakDelay: 20, peakHour: '9:15 AM', accidentCount: 6, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: 1.1, coordinates: [[80.228, 12.900], [80.225, 12.890]] },
  { id: 'che-3', name: 'Mount Road (Anna Salai)', city: 'Chennai', type: 'arterial', cfi: 72, avgSpeed: 26, peakDelay: 15, peakHour: '6:30 PM', accidentCount: 5, weekdaySpeedProfile: [], weekendSpeedProfile: [], trend: -0.4, coordinates: [[80.260, 13.060], [80.265, 13.065]] },
];

// Fill in default speed profiles for segments that don't have them
segments.forEach(seg => {
  if (seg.weekdaySpeedProfile.length === 0) {
    const baseSpeed = seg.avgSpeed + 15;
    const dip1 = seg.avgSpeed - 5;
    const dip2 = seg.avgSpeed - 2;
    seg.weekdaySpeedProfile = Array.from({length: 24}, (_, i) => {
      if (i >= 7 && i <= 10) return dip1 + Math.random() * 4; // morning peak
      if (i >= 17 && i <= 20) return dip2 + Math.random() * 4; // evening peak
      return baseSpeed - Math.random() * 5;
    });
  }
  if (seg.weekendSpeedProfile.length === 0) {
    const baseSpeed = seg.avgSpeed + 20;
    seg.weekendSpeedProfile = Array.from({length: 24}, () => {
      return baseSpeed - Math.random() * 8; // generally faster on weekends
    });
  }
});
