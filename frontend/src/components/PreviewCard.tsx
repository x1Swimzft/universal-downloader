import React, { useEffect, useState } from "react";
import Image from "next/image";
import { Icon } from "./Icons";
import { Switch } from "./Switch";
import { MediaInfo, PreviewEntry } from "../lib/api";

export type DownloadMode = "Images" | "Video" | "Audio";

export interface DownloadChoices {
  startTime?: string;
  endTime?: string;
  preset?: string;
  saveInSubfolder?: boolean;
}

export interface PreviewCardProps {
  info: MediaInfo;
  mode: DownloadMode;
  onModeChange: (m: DownloadMode) => void;
  selectedOption: string;
  onSelectOption: (q: string) => void;
  saveFolder: string;
  onDownload: (choices?: DownloadChoices) => void;
  downloading?: boolean;
  onEnqueueSelected?: (entries: PreviewEntry[], choices?: DownloadChoices) => void;
  enqueueing?: boolean;
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

const PRESET_OPTIONS: SegmentOption[] = [
  { value: "", label: "Off" },
  { value: "edit_ready", label: "Edit" },
  { value: "audio_norm", label: "Normalize" },
  { value: "audio_lossless", label: "Lossless" },
];

const AUDIO_PRESET_OPTIONS: SegmentOption[] = [
  { value: "", label: "Off" },
  { value: "audio_norm", label: "Normalize" },
  { value: "audio_lossless", label: "Lossless" },
];

const MUSIC_MODE_OPTIONS: SegmentOption[] = [
  { value: "Audio", label: "Audio" },
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
  onEnqueueSelected,
  enqueueing,
}: PreviewCardProps) {
  const [preset, setPreset] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [saveInSubfolder, setSaveInSubfolder] = useState(true);
  const entries = info.entries || [];
  const entryUrls = entries.map((entry) => entry.url).join("\n");
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set());

  useEffect(() => {
    setSelectedUrls(new Set(entryUrls ? entryUrls.split("\n") : []));
  }, [entryUrls]);

  const isPlaylist = entries.length > 0;
  const selectedEntries = entries.filter((entry) => selectedUrls.has(entry.url));

  const toggleEntry = (entryUrl: string) => {
    setSelectedUrls((current) => {
      const next = new Set(current);
      if (next.has(entryUrl)) next.delete(entryUrl);
      else next.add(entryUrl);
      return next;
    });
  };

  const images = info.images || [];
  const isImagePost =
    info.media_type === "image" ||
    info.media_type === "carousel" ||
    (images.length > 0 && (info.formats?.length || 0) === 0);
  const hasBackgroundAudio = Boolean(
    info.formats?.some(
      (f) =>
        f.resolution === "audio" ||
        (f.note || "").toLowerCase().startsWith("audio")
    )
  );
  const isMusic = /spotify|apple/i.test(info.platform || "");
  // Music links never offer Video. Photo posts never offer Video.
  const effectiveMode: DownloadMode = isImagePost
    ? mode === "Video" || !hasBackgroundAudio
      ? "Images"
      : mode
    : isMusic
      ? "Audio"
      : mode === "Images"
        ? "Video"
        : mode;

  useEffect(() => {
    if (mode !== effectiveMode) onModeChange(effectiveMode);
  }, [effectiveMode, mode, onModeChange]);

  useEffect(() => {
    setPreset("");
  }, [effectiveMode]);

  useEffect(() => {
    setPreset("");
    setStartTime("");
    setEndTime("");
    setSaveInSubfolder(true);
  }, [info.title, info.thumbnail]);

  const parts: string[] = [];
  const dur = formatDuration(info.duration);
  const showSlideMeta = isImagePost && effectiveMode === "Images";
  if (dur && !showSlideMeta) parts.push(dur);

  if (isPlaylist) {
    parts.push(`${entries.length} item${entries.length === 1 ? "" : "s"}`);
  }

  if (info.uploader) {
    parts.push(info.uploader);
  }

  if (isImagePost) {
    if (showSlideMeta) {
      const count = images.length || 1;
      parts.push(
        count > 1
          ? `${count} slides`
          : `${count} photo${count === 1 ? "" : "s"}`
      );
    }
  } else {
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
  }

  const metaText = parts.join(" · ");
  const currentOptions =
    effectiveMode === "Video" ? VIDEO_OPTIONS : AUDIO_OPTIONS;
  const imageModeOptions: SegmentOption[] = [
    {
      value: "Images",
      label:
        images.length > 1 ? `Photos · ${images.length} slides` : "Photo",
    },
    ...(hasBackgroundAudio ? [{ value: "Audio", label: "Audio" }] : []),
  ];
  const modeOptions = isMusic ? MUSIC_MODE_OPTIONS : MODE_OPTIONS;
  const presetOptions =
    effectiveMode === "Audio" ? AUDIO_PRESET_OPTIONS : PRESET_OPTIONS;
  const thumb = info.thumbnail || images[0];
  const downloadLabel = isImagePost
    ? effectiveMode === "Images"
      ? images.length > 1
        ? "Download photos"
        : "Download photo"
      : "Download audio"
    : isMusic
      ? "Download audio"
      : "Download";

  return (
    <div className="res show" id="res">
      <div className="thumb">
        {thumb ? (
          <Image
            src={thumb}
            alt={info.title || "Thumbnail"}
            fill
            unoptimized
            style={{ objectFit: "cover" }}
          />
        ) : (
          <Icon name="p" />
        )}
        {dur && !showSlideMeta && <span className="thumb-dur">{dur}</span>}
      </div>

      <div className="info">
        <h3 id="rt">{info.title}</h3>
        {(metaText || info.platform) && (
          <div className="meta" id="rm">
            {info.platform && <span className="chip">{info.platform}</span>}
            {metaText && <span>{metaText}</span>}
          </div>
        )}

        {isImagePost ? (
          <>
            <Segmented
              label="Media type"
              className="mode"
              options={imageModeOptions}
              value={effectiveMode}
              onChange={(value) => onModeChange(value as DownloadMode)}
            />
            {effectiveMode === "Images" ? (
              <>
                <div className="photos" aria-label={`${images.length} photos`}>
                  {images.slice(0, 4).map((src, index) => (
                    <span className="photo" key={`${src}-${index}`}>
                      <Image
                        src={src}
                        alt={`Photo ${index + 1}`}
                        fill
                        unoptimized
                        style={{ objectFit: "cover" }}
                      />
                    </span>
                  ))}
                  {images.length > 4 && (
                    <span className="photo-more">+{images.length - 4}</span>
                  )}
                </div>
                <span className="photo-note">
                  {images.length > 1
                    ? "Carousel saved as a ZIP of full-size photos."
                    : "Full-size photo saved without re-encoding."}
                </span>
              </>
            ) : (
              <>
                <Segmented
                  label="Quality"
                  className="quality"
                  options={AUDIO_OPTIONS}
                  value={selectedOption}
                  onChange={onSelectOption}
                />
                <Segmented
                  label="Edit preset"
                  className="preset"
                  options={AUDIO_PRESET_OPTIONS}
                  value={preset}
                  onChange={setPreset}
                />
              </>
            )}
          </>
        ) : (
          <>
            <Segmented
              label="Media type"
              className="mode"
              options={modeOptions}
              value={effectiveMode}
              onChange={(value) => onModeChange(value as DownloadMode)}
            />
            <Segmented
              label="Quality"
              className="quality"
              options={currentOptions}
              value={selectedOption}
              onChange={onSelectOption}
            />
            <Segmented
              label="Edit preset"
              className="preset"
              options={presetOptions}
              value={preset}
              onChange={setPreset}
            />
            {!isPlaylist && (
              <div className="clip-row">
                <label className="time-field">
                  <span>Start</span>
                  <input
                    className="time-input"
                    type="text"
                    inputMode="numeric"
                    placeholder="MM:SS"
                    aria-label="Clip start time"
                    value={startTime}
                    onChange={(event) => setStartTime(event.target.value)}
                  />
                </label>
                <label className="time-field">
                  <span>End</span>
                  <input
                    className="time-input"
                    type="text"
                    inputMode="numeric"
                    placeholder="MM:SS"
                    aria-label="Clip end time"
                    value={endTime}
                    onChange={(event) => setEndTime(event.target.value)}
                  />
                </label>
                <span className="clip-hint">Optional · MM:SS or HH:MM:SS</span>
              </div>
            )}
            {isPlaylist && (
              <>
                <div className="plist" role="group" aria-label="Playlist entries">
                  {entries.map((entry) => {
                    const meta = [
                      formatDuration(entry.duration),
                      entry.artist,
                      entry.album,
                      entry.platform,
                    ]
                      .filter(Boolean)
                      .join(" · ");
                    return (
                      <label className="pitem" key={entry.url}>
                        <input
                          type="checkbox"
                          aria-label={entry.title || "Untitled"}
                          checked={selectedUrls.has(entry.url)}
                          onChange={() => toggleEntry(entry.url)}
                        />
                        <span className="ptitle">{entry.title || "Untitled"}</span>
                        {meta && <span className="pmeta">{meta}</span>}
                      </label>
                    );
                  })}
                </div>
                {info.platform !== "Multiple" && (
                  <div className="plist-subfolder">
                    <span>Save playlist in subfolder</span>
                    <Switch
                      checked={saveInSubfolder}
                      onChange={setSaveInSubfolder}
                      ariaLabel="Save playlist in subfolder"
                    />
                  </div>
                )}
                <div className="plist-actions">
                  <button
                    type="button"
                    className="btn sm"
                    onClick={() =>
                      setSelectedUrls(new Set(entries.map((entry) => entry.url)))
                    }
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    className="btn sm"
                    onClick={() => setSelectedUrls(new Set())}
                  >
                    Select none
                  </button>
                  <span className="plist-count" aria-live="polite">
                    Selected {selectedEntries.length}/{entries.length}
                  </span>
                  <button
                    type="button"
                    className="btn p"
                    onClick={() =>
                      onEnqueueSelected?.(selectedEntries, {
                        preset: preset || undefined,
                        saveInSubfolder,
                      })
                    }
                    disabled={selectedEntries.length === 0 || enqueueing}
                    aria-busy={enqueueing || undefined}
                  >
                    <Icon name="dl" />
                    {enqueueing
                      ? "Starting…"
                      : `Download Selected (${selectedEntries.length})`}
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </div>

      <div className="foot">
        <Icon name="f" />
        <span className="save">Save to {saveFolder}</span>
        {!isPlaylist && (
          <button
            type="button"
            className={`btn p ${downloading ? "" : "ready"}`}
            id="go"
            onClick={() =>
              onDownload(
                isImagePost
                  ? effectiveMode === "Images"
                    ? undefined
                    : { preset: preset || undefined }
                  : {
                      startTime: startTime.trim() || undefined,
                      endTime: endTime.trim() || undefined,
                      preset: preset || undefined,
                    }
              )
            }
            disabled={downloading}
          >
            <Icon name="dl" />
            {downloading ? "Starting…" : downloadLabel}
          </button>
        )}
      </div>
    </div>
  );
}
