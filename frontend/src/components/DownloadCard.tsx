import React from "react";
import { QueueItem } from "../lib/api";

export interface DownloadCardProps {
  item: QueueItem;
  onCancel: (id: string) => void;
}

export function DownloadCard({ item, onCancel }: DownloadCardProps) {
  const isDone = item.status === "completed" || item.status === "done";
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

  return (
    <div className={`card dl ${isDone ? "done" : ""}`}>
      <div className="t">
        <span>{item.title || item.url}</span>
        <button
          type="button"
          className="chip"
          onClick={() => onCancel(item.id)}
          aria-label="Remove"
        >
          {isDone ? "Done" : "Cancel"}
        </button>
      </div>

      <div className="pg">
        <i style={{ width: `${progressPercent}%` }} />
      </div>

      <div className="s">
        <span>
          {qualityLabel ? `${qualityLabel} · ` : ""}
          {item.platform || "Web"}
        </span>
        <span>
          {isDone
            ? "Saved"
            : item.status === "error"
            ? item.error || "Failed"
            : `${Math.round(item.progress)}% · ${(item.speed || 0).toFixed(1)} MB/s`}
        </span>
      </div>
    </div>
  );
}
