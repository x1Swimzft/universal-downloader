export function getApiBase(): string {
  if (typeof window !== "undefined") {
    const params = new URLSearchParams(window.location.search);
    const apiPort = params.get("api_port");
    if (apiPort) return `http://127.0.0.1:${apiPort}`;
  }
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  return base.replace(/\/api\/?$/, "").replace(/\/+$/, "");
}

export interface MediaInfo {
  title: string;
  thumbnail?: string;
  duration?: number;
  uploader?: string;
  platform?: string;
  formats: FormatOption[];
}

export interface FormatOption {
  format_id: string;
  ext: string;
  resolution?: string;
  filesize?: number;
  note?: string;
}

export interface JobStatus {
  job_id: string;
  status: "pending" | "processing" | "done" | "error";
  progress: number;
  filename?: string;
  error?: string;
}

export async function fetchInfo(url: string): Promise<MediaInfo> {
  const res = await fetch(`${getApiBase()}/api/info`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to fetch info");
  }
  return res.json();
}

export async function startDownload(
  url: string,
  format: "mp3" | "mp4",
  quality: string,
  title?: string
): Promise<{ job_id: string }> {
  const res = await fetch(`${getApiBase()}/api/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, format, quality, title }),
  });
  if (!res.ok) {
    const err = await res.json();
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
  return `${getApiBase()}/api/file/${jobId}`;
}

export interface QueueItem {
  id: string;
  url: string;
  format: "mp3" | "mp4";
  quality: string;
  title?: string;
  status: "queued" | "downloading" | "completed" | "done" | "error";
  progress: number;
  filename?: string;
  error?: string;
}

export async function addBatchToQueue(
  urls: string[],
  format: "mp3" | "mp4",
  quality: string
): Promise<{ job_ids: string[]; count: number }> {
  const res = await fetch(`${getApiBase()}/api/queue/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls, format, quality }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to add to queue");
  }
  return res.json();
}

export function getQueueStreamUrl(): string {
  return `${getApiBase()}/api/queue/stream`;
}
