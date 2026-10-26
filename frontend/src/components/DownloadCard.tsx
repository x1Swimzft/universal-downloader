import React from "react";
import { QueueItem } from "../lib/api";

export interface DownloadCardProps {
  item: QueueItem;
  onCancel: (id: string) => void;
}

export function DownloadCard({ item, onCancel }: DownloadCardProps) {
  const isDone = item.status === "completed" || item.status === "done";
  const isActive = item.status === "queued" || item.status === "downloading";
  const qualityLabel = (() => {
    if (item.format === "m4a") return "M4A";
    if (item.format === "opus") return "OPUS";
    if (item.format === "mp3") {
      return item.quality
        ? `MP3 ${item.quality.replace(/k$/i, "")}k`
        : "MP3 320k";
    }
    if (!item.quality) return "";
    return `${item.quality.replace(/p$/i, "")}p`;
  })();
  const progressPercent = Math.min(100, Math.max(0, item.progress));
  const label = item.title || item.url;

  const statusText = isDone
    ? "Saved"
    : item.status === "error"
      ? item.error || "Failed"
      : item.status === "queued"
        ? "Queued"
        : `${qualityLabel ? `${qualityLabel} · ` : ""}${(item.speed || 0).toFixed(1)} MB/s`;

  return (
    <div className={`qrow ${isDone ? "done" : ""} ${isActive ? "active" : ""}`}>
      <div className="qline">
        <span className="chip">{item.platform || "Web"}</span>
        <span className="qtitle" title={label}>
          {label}
        </span>
        <span className="qpct">
          {isDone ? "100%" : item.status === "error" ? "—" : `${Math.round(item.progress)}%`}
        </span>
        <button
          type="button"
          className="chip"
          onClick={() => onCancel(item.id)}
          aria-label={isDone ? `Clear ${label} from queue` : `Remove ${label} from queue`}
        >
          {isDone ? "Done" : "Remove"}
        </button>
      </div>

      <div className="qline">
        <div
          className="pg"
          role="progressbar"
          aria-label={`${label} progress`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progressPercent)}
        >
          <i style={{ transform: `scaleX(${progressPercent / 100})` }} />
        </div>
        <span className={`qmeta ${item.status === "error" ? "bad" : ""}`} title={statusText}>
          {statusText}
        </span>
      </div>
    </div>
  );
}
