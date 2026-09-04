const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw new Error(`FloodOps API request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

export const floodApi = {
  getFloodMap: <T = unknown>(query = "") => apiRequest<T>(`/flood/map${query}`),
  getRiskAlerts: <T = unknown>() => apiRequest<T>("/flood/risk"),
  getSaferRoutes: <T = unknown>() => apiRequest<T>("/route/safer"),
};
