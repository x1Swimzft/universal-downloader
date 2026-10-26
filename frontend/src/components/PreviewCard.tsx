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

interface SegmentOption {
  value: string;
  label: string;
}

const MODE_OPTIONS: SegmentOption[] = [
  { value: "Video", label: "Video" },
  { value: "Audio", label: "Audio" },
];

const VIDEO_OPTIONS: SegmentOption[] = [
  { value: "2160p", label: "4K" },
  { value: "1440p", label: "1440p" },
  { value: "1080p", label: "1080p" },
  { value: "720p", label: "720p" },
  { value: "480p", label: "480p" },
];

const AUDIO_OPTIONS: SegmentOption[] = [
  { value: "MP3 320k", label: "MP3 320k" },
  { value: "M4A", label: "M4A" },
  { value: "OPUS", label: "OPUS" },
];

function Segmented({
  label,
  options,
  value,
  onChange,
  className,
}: {
  label: string;
  options: SegmentOption[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  const index = Math.max(
    0,
    options.findIndex((option) => option.value === value)
  );
  const style = {
    "--seg-count": options.length,
    "--seg-index": index,
  } as React.CSSProperties;

  return (
    <div
      className={`segmented ${className || ""}`}
      role="group"
      aria-label={label}
      style={style}
    >
      <span className="seg-thumb" aria-hidden="true" />
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          className="seg-opt"
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

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
      <div className="thumb">
        {info.thumbnail ? (
          <Image
            src={info.thumbnail}
            alt={info.title || "Thumbnail"}
            fill
            unoptimized
            style={{ objectFit: "cover" }}
          />
        ) : (
          <Icon name="p" />
        )}
        {dur && <span className="thumb-dur">{dur}</span>}
      </div>

      <div className="info">
        <h3 id="rt">{info.title}</h3>
        {(metaText || info.platform) && (
          <div className="meta" id="rm">
            {info.platform && <span className="chip">{info.platform}</span>}
            {metaText && <span>{metaText}</span>}
          </div>
        )}
        <Segmented
          label="Media type"
          className="mode"
          options={MODE_OPTIONS}
          value={mode}
          onChange={(value) => onModeChange(value as "Video" | "Audio")}
        />
        <Segmented
          label="Quality"
          className="quality"
          options={currentOptions}
          value={selectedOption}
          onChange={onSelectOption}
        />
      </div>

      <div className="foot">
        <Icon name="f" />
        <span className="save">Save to {saveFolder}</span>
        <button
          type="button"
          className={`btn p ${downloading ? "" : "ready"}`}
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
