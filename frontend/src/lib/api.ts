export function getApiBase(): string {
  if (typeof window !== "undefined") {
    const params = new URLSearchParams(window.location.search);
    const apiPort = params.get("api_port");
    if (apiPort) return `http://127.0.0.1:${apiPort}`;
  }
  const base = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
  return base.replace(/\/api\/?$/, "").replace(/\/+$/, "");
}

export type DownloadFormat = "mp4" | "mp3" | "m4a" | "opus" | "images";
export type CookieBrowser = "none" | "chrome" | "edge" | "brave" | "firefox";

export interface DownloadOptions {
  startTime?: string;
  endTime?: string;
  preset?: string;
  socialBypass?: boolean;
}

export interface ExtractorStatus {
  active_version: string;
  user_version?: string | null;
  source: "bundled" | "user";
  location: string;
  restart_required: boolean;
  updated?: boolean;
  latest_version?: string;
  message?: string;
}

export interface FormatOption {
  format_id: string;
  ext: string;
  resolution?: string;
  filesize?: number;
  note?: string;
}

export interface MediaInfo {
  title: string;
  thumbnail?: string;
  duration?: number;
  uploader?: string;
  platform?: string;
  formats: FormatOption[];
  images?: string[];
  media_type?: "video" | "image" | "carousel";
}

export interface JobStatus {
  job_id: string;
  status: "pending" | "processing" | "done" | "error";
  progress: number;
  filename?: string;
  error?: string;
}

export interface QueueItem {
  id: string;
  url: string;
  format: DownloadFormat;
  quality: string;
  title?: string;
  platform?: string;
  status: "queued" | "downloading" | "completed" | "done" | "error";
  progress: number;
  speed?: number;
  filename?: string;
  error?: string;
  start_time?: string;
  end_time?: string;
  preset?: string;
  social_bypass?: boolean;
}

export interface AppSettings {
  autoDetectClipboard: boolean;
  minimizeToTray: boolean;
  notifyWhenFinished: boolean;
  maxConcurrent: 1 | 2 | 3 | 5;
  saveFolder: string;
  theme: "light" | "dark";
  cookiesFromBrowser: CookieBrowser;
  cookiesFile: string;
  socialBypass: boolean;
  quickFetchHotkeyEnabled: boolean;
}

export interface HistoryItem {
  id: string;
  url: string;
  title: string;
  format: DownloadFormat;
  quality: string;
  label: string;
  platform?: string;
  filename?: string;
  completedAt: number;
  start_time?: string;
  end_time?: string;
  preset?: string;
  social_bypass?: boolean;
}

declare global {
  interface Window {
    electronAPI?: {
      getSettings: () => Promise<AppSettings>;
      updateSettings: (patch: Partial<AppSettings>) => Promise<AppSettings>;
      pickFolder: () => Promise<AppSettings>;
      pickCookiesFile: () => Promise<AppSettings>;
      openFolder: (targetPath?: string) => Promise<{ opened: string }>;
      notify: (title: string, body?: string) => Promise<boolean>;
      startDrag: (filePath: string) => Promise<boolean>;
      onSettingsUpdated: (cb: (updated: AppSettings) => void) => () => void;
      getAppToken: () => Promise<string>;
    };
  }
}

let appTokenCache: string | null = null;

export async function getAppToken(): Promise<string> {
  if (appTokenCache) return appTokenCache;
  if (typeof window !== "undefined") {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("token");
    if (fromQuery) {
      appTokenCache = fromQuery;
      return appTokenCache;
    }
    if (window.electronAPI?.getAppToken) {
      try {
        const fromIpc = await window.electronAPI.getAppToken();
        if (fromIpc) {
          appTokenCache = fromIpc;
          return appTokenCache;
        }
      } catch {}
    }
  }
  return "";
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const token = await getAppToken();
  return token ? { "X-App-Token": token } : {};
}

export async function fetchInfo(url: string): Promise<MediaInfo> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/info`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to fetch info");
  }
  return res.json();
}

function downloadPayload(
  url: string,
  format: DownloadFormat,
  quality: string,
  title?: string,
  options?: DownloadOptions
) {
  return {
    url,
    format,
    quality,
    title,
    start_time: options?.startTime || null,
    end_time: options?.endTime || null,
    preset: options?.preset || null,
    social_bypass: Boolean(options?.socialBypass),
  };
}

export async function startDownload(
  url: string,
  format: DownloadFormat,
  quality: string,
  title?: string,
  options?: DownloadOptions
): Promise<{ job_id: string }> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify(downloadPayload(url, format, quality, title, options)),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to start download");
  }
  return res.json();
}

export async function pollProgress(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${getApiBase()}/api/progress/${jobId}`);
  if (!res.ok) throw new Error("Failed to fetch progress");
  return res.json();
}

export function getFileUrl(jobId: string): string {
  const token = appTokenCache || "";
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${getApiBase()}/api/file/${jobId}${query}`;
}

export function getStreamUrl(url: string, quality: string = "720"): string {
  const token = appTokenCache || "";
  const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
  return `${getApiBase()}/api/stream?url=${encodeURIComponent(url)}&quality=${encodeURIComponent(quality)}${tokenParam}`;
}

export async function enqueueDownload(
  url: string,
  format: DownloadFormat,
  quality: string,
  title?: string,
  options?: DownloadOptions
): Promise<{ job_ids: string[]; count: number }> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/queue/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify(downloadPayload(url, format, quality, title, options)),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to add to queue");
  }
  return res.json();
}

export async function addBatchToQueue(
  urls: string[],
  format: DownloadFormat,
  quality: string
): Promise<{ job_ids: string[]; count: number }> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/queue/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify({ urls, format, quality }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to add to queue");
  }
  return res.json();
}

export async function cancelQueueItem(jobId: string): Promise<void> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/queue/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
    headers: authHeaders,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to cancel download");
  }
}

export async function fetchHistory(): Promise<HistoryItem[]> {
  try {
    const res = await fetch(`${getApiBase()}/api/history`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.items) ? data.items : [];
  } catch {
    return [];
  }
}

export async function deleteHistoryItem(id: string): Promise<void> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/history/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to delete history item");
  }
}

export async function clearHistory(): Promise<number> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/history`, {
    method: "DELETE",
    headers: authHeaders,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to clear history");
  }
  const data = await res.json().catch(() => ({}));
  return typeof data.cleared === "number" ? data.cleared : 0;
}

export function getQueueStreamUrl(): string {
  return `${getApiBase()}/api/queue/stream`;
}

export const DEFAULT_FALLBACK_SETTINGS: AppSettings = {
  autoDetectClipboard: true,
  minimizeToTray: true,
  notifyWhenFinished: true,
  maxConcurrent: 3,
  saveFolder: "Downloads\\Universal Downloader",
  theme: "dark",
  cookiesFromBrowser: "none",
  cookiesFile: "",
  socialBypass: false,
  quickFetchHotkeyEnabled: true,
};

export async function getAppSettings(): Promise<AppSettings> {
  if (typeof window !== "undefined" && window.electronAPI) {
    return {
      ...DEFAULT_FALLBACK_SETTINGS,
      ...(await window.electronAPI.getSettings()),
    };
  }
  try {
    const res = await fetch(`${getApiBase()}/api/settings`);
    if (res.ok) {
      const data = await res.json();
      return {
        ...DEFAULT_FALLBACK_SETTINGS,
        maxConcurrent: data.max_concurrent || 3,
        saveFolder: data.save_folder || DEFAULT_FALLBACK_SETTINGS.saveFolder,
        cookiesFromBrowser: data.cookies_from_browser || "none",
        cookiesFile: data.cookies_file || "",
      };
    }
  } catch {}
  return DEFAULT_FALLBACK_SETTINGS;
}

export async function updateAppSettings(patch: Partial<AppSettings>): Promise<AppSettings> {
  if (typeof window !== "undefined" && window.electronAPI) {
    return {
      ...DEFAULT_FALLBACK_SETTINGS,
      ...(await window.electronAPI.updateSettings(patch)),
    };
  }
  const authHeaders = await getAuthHeaders();
  await fetch(`${getApiBase()}/api/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify({
      max_concurrent: patch.maxConcurrent,
      cookies_from_browser: patch.cookiesFromBrowser,
      cookies_file: patch.cookiesFile,
    }),
  }).catch(() => {});
  return { ...DEFAULT_FALLBACK_SETTINGS, ...patch };
}

export async function pickSaveFolder(): Promise<AppSettings> {
  if (typeof window !== "undefined" && window.electronAPI) {
    return {
      ...DEFAULT_FALLBACK_SETTINGS,
      ...(await window.electronAPI.pickFolder()),
    };
  }
  return getAppSettings();
}

export async function pickCookiesFile(): Promise<AppSettings> {
  if (typeof window !== "undefined" && window.electronAPI) {
    return {
      ...DEFAULT_FALLBACK_SETTINGS,
      ...(await window.electronAPI.pickCookiesFile()),
    };
  }
  return getAppSettings();
}

export async function getExtractorStatus(): Promise<ExtractorStatus> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/system/extractor`, {
    headers: authHeaders,
  });
  if (!res.ok) throw new Error("Failed to read extractor status");
  return res.json();
}

export async function updateExtractor(): Promise<ExtractorStatus> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/system/update-extractor`, {
    method: "POST",
    headers: authHeaders,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Extractor update failed");
  }
  return res.json();
}

export async function startDragFile(filePath: string): Promise<boolean> {
  if (typeof window !== "undefined" && window.electronAPI?.startDrag) {
    return window.electronAPI.startDrag(filePath);
  }
  return false;
}

export async function openSaveFolder(targetPath?: string): Promise<void> {
  if (typeof window !== "undefined" && window.electronAPI) {
    await window.electronAPI.openFolder(targetPath);
    return;
  }
  const authHeaders = await getAuthHeaders();
  await fetch(`${getApiBase()}/api/open-folder`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify({ path: targetPath || null }),
  });
}

export async function triggerDesktopNotification(title: string, body?: string): Promise<void> {
  if (typeof window !== "undefined" && window.electronAPI) {
    await window.electronAPI.notify(title, body);
    return;
  }
  if (typeof window !== "undefined" && "Notification" in window) {
    if (Notification.permission === "granted") {
      new Notification(title, { body });
    } else if (Notification.permission !== "denied") {
      const perm = await Notification.requestPermission();
      if (perm === "granted") new Notification(title, { body });
    }
  }
}
