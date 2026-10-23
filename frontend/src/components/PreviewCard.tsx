import React from "react";
import Image from "next/image";
import { Icon } from "./Icons";
import { MediaInfo } from "../lib/api";

export interface PreviewCardProps {
  info: MediaInfo;
  mode: "Video" | "Audio";
  onModeChange: (m: "Video" | "Audio") => void;
  selectedOption: string;
  onSelectOption: (q: string) => void;
  saveFolder: string;
  onDownload: () => void;
  downloading?: boolean;
}

const VIDEO_OPTIONS = ["2160p", "1440p", "1080p", "720p", "480p"] as const;
const AUDIO_OPTIONS = ["MP3 320k", "M4A", "OPUS"] as const;

function formatDuration(sec?: number): string {
  if (sec == null || isNaN(sec) || sec <= 0) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatFilesize(bytes?: number): string {
  if (bytes == null || isNaN(bytes) || bytes <= 0) return "";
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

export function PreviewCard({
  info,
  mode,
  onModeChange,
  selectedOption,
  onSelectOption,
  saveFolder,
  onDownload,
  downloading,
}: PreviewCardProps) {
  const parts: string[] = [];
  const dur = formatDuration(info.duration);
  if (dur) parts.push(dur);

  if (info.uploader) {
    parts.push(info.uploader);
  }

  const matchedFormat = info.formats?.find(
    (f) =>
      (f.resolution && f.resolution.includes(selectedOption)) ||
      (f.note && f.note.includes(selectedOption))
  );

  if (matchedFormat?.resolution) {
    parts.push(matchedFormat.resolution);
  }

  const size =
    matchedFormat?.filesize ||
    info.formats?.find((f) => f.filesize && f.filesize > 0)?.filesize;

  if (size) {
    parts.push(`about ${formatFilesize(size)}`);
  } else if (!info.uploader && info.platform) {
    parts.push(info.platform);
  }

  const metaText = parts.join(" · ");
  const currentOptions = mode === "Video" ? VIDEO_OPTIONS : AUDIO_OPTIONS;

  return (
    <div className="res show" id="res">
      <div className="thumb" style={{ position: "relative", overflow: "hidden" }}>
        {info.thumbnail ? (
          <Image
            src={info.thumbnail}
            alt={info.title || "Thumbnail"}
            fill
            unoptimized
            style={{
              objectFit: "cover",
              borderRadius: "12px",
            }}
          />
        ) : (
          <Icon name="p" style={{ width: 36, height: 36, fill: "#fff" }} />
        )}
      </div>

      <div className="info">
        <h3 id="rt">{info.title}</h3>
        {metaText && (
          <div className="meta" id="rm">
            {metaText}
          </div>
        )}
        <div className="seg" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "Video"}
            className={mode === "Video" ? "on" : ""}
            onClick={() => onModeChange("Video")}
          >
            Video
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "Audio"}
            className={mode === "Audio" ? "on" : ""}
            onClick={() => onModeChange("Audio")}
          >
            Audio
          </button>
        </div>
        <div className="chips" id="qs" style={{ marginTop: 0 }}>
          {currentOptions.map((opt) => (
            <button
              key={opt}
              type="button"
              className={`chip ${opt === selectedOption ? "on" : ""}`}
              onClick={() => onSelectOption(opt)}
            >
              {opt}
            </button>
          ))}
        </div>
      </div>

      <div className="foot" style={{ width: "100%" }}>
        <Icon name="f" />
        <span>Save to {saveFolder}</span>
        <button
          type="button"
          className="btn p"
          id="go"
          onClick={onDownload}
          disabled={downloading}
        >
          <Icon name="dl" />
          {downloading ? "Starting…" : "Download"}
        </button>
      </div>
    </div>
  );
}
