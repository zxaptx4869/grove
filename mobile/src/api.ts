export type ApiError = Error & { status?: number };
export type Me = { user: { id: number; username: string }; workspace: { id: number; name: string } };
export type Project = { id: number; name: string; description: string | null; status: string };
export type MobileAuth = { user: { id: number; username: string }; token: string };

const baseUrl = process.env.EXPO_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
export const apiConfigured = Boolean(baseUrl);

export async function request<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  if (!baseUrl) throw new Error("未配置 EXPO_PUBLIC_API_BASE_URL，请在 .env 中填写后端地址。");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12_000);
  try {
    const response = await fetch(`${baseUrl}${path}`, { ...options, signal: controller.signal, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } });
    if (!response.ok) { const error: ApiError = new Error((await response.json().catch(() => null))?.detail ?? "请求失败"); error.status = response.status; throw error; }
    return response.json() as Promise<T>;
  } finally { clearTimeout(timer); }
}

export const mobileLogin = (username: string, password: string, register = false) => request<MobileAuth>(`/api/auth/mobile/${register ? "register" : "login"}`, { method: "POST", body: JSON.stringify({ username, password }) });
export const getMe = (token: string) => request<Me>("/api/me", {}, token);
export const getProjects = (token: string) => request<Project[]>("/api/projects", {}, token);
export const mobileLogout = (token: string) => request<{ ok: boolean }>("/api/auth/mobile/logout", { method: "POST" }, token);
