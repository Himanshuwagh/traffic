const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

export const API_BASE_URL = (rawApiBaseUrl && rawApiBaseUrl.length > 0)
  ? rawApiBaseUrl.replace(/\/+$/, '')
  : 'http://127.0.0.1:8000';

export const apiUrl = (path: string) => {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
};
