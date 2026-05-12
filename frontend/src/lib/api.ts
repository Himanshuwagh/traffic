const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

if (!rawApiBaseUrl) {
  console.warn("VITE_API_BASE_URL is not set. Defaulting to http://127.0.0.1:8000. This will fail on deployed sites.");
}

export const API_BASE_URL = (rawApiBaseUrl && rawApiBaseUrl.length > 0)
  ? rawApiBaseUrl.replace(/\/+$/, '')
  : 'http://127.0.0.1:8000';

export const apiUrl = (path: string) => {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const url = `${API_BASE_URL}${normalizedPath}`;
  return url;
};
