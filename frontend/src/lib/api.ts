export function getApiBase(): string {
  if (typeof window !== "undefined") {
    const params = new URLSearchParams(window.location.search);
    const apiPort = params.get("api_port");
    if (apiPort) return `http://127.0.0.1:${apiPort}`;
  }
  const base = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
  return base.replace(/\/api\/?$/, "").replace(/\/+$/, "");
}

export type DownloadFormat = "mp4" | "mp3" | "m4a" | "opus";

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
}

export interface AppSettings {
  autoDetectClipboard: boolean;
  minimizeToTray: boolean;
  notifyWhenFinished: boolean;
  maxConcurrent: 1 | 2 | 3 | 5;
  saveFolder: string;
  theme: "light" | "dark";
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
}

declare global {
  interface Window {
    electronAPI?: {
      getSettings: () => Promise<AppSettings>;
      updateSettings: (patch: Partial<AppSettings>) => Promise<AppSettings>;
      pickFolder: () => Promise<AppSettings>;
      openFolder: (targetPath?: string) => Promise<{ opened: string }>;
      notify: (title: string, body?: string) => Promise<boolean>;
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

export async function startDownload(
  url: string,
  format: DownloadFormat,
  quality: string,
  title?: string
): Promise<{ job_id: string }> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify({ url, format, quality, title }),
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
  title?: string
): Promise<{ job_ids: string[]; count: number }> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}/api/queue/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify({ url, format, quality, title }),
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

export function getQueueStreamUrl(): string {
  return `${getApiBase()}/api/queue/stream`;
}

const DEFAULT_FALLBACK_SETTINGS: AppSettings = {
  autoDetectClipboard: true,
  minimizeToTray: true,
  notifyWhenFinished: true,
  maxConcurrent: 3,
  saveFolder: "Downloads\\Universal Downloader",
  theme: "dark",
};

export async function getAppSettings(): Promise<AppSettings> {
  if (typeof window !== "undefined" && window.electronAPI) {
    return window.electronAPI.getSettings();
  }
  try {
    const res = await fetch(`${getApiBase()}/api/settings`);
    if (res.ok) {
      const data = await res.json();
      return {
        ...DEFAULT_FALLBACK_SETTINGS,
        maxConcurrent: data.max_concurrent || 3,
        saveFolder: data.save_folder || DEFAULT_FALLBACK_SETTINGS.saveFolder,
      };
    }
  } catch {}
  return DEFAULT_FALLBACK_SETTINGS;
}

export async function updateAppSettings(patch: Partial<AppSettings>): Promise<AppSettings> {
  if (typeof window !== "undefined" && window.electronAPI) {
    return window.electronAPI.updateSettings(patch);
  }
  if (patch.maxConcurrent) {
    const authHeaders = await getAuthHeaders();
    await fetch(`${getApiBase()}/api/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({ max_concurrent: patch.maxConcurrent }),
    }).catch(() => {});
  }
  return { ...DEFAULT_FALLBACK_SETTINGS, ...patch };
}

export async function pickSaveFolder(): Promise<AppSettings> {
  if (typeof window !== "undefined" && window.electronAPI) {
    return window.electronAPI.pickFolder();
  }
  return getAppSettings();
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
