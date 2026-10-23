import React from "react";
import { Icon } from "./Icons";

const PLATFORMS = [
  "YouTube",
  "TikTok",
  "Instagram",
  "X",
  "Facebook",
  "SoundCloud",
] as const;

export interface UrlBarProps {
  url: string;
  onChange: (val: string) => void;
  onFetch: (overrideUrl?: string) => void;
  onPaste: () => void;
  loading: boolean;
  detectedPlatform: string;
  error: string;
}

export function UrlBar({
  url,
  onChange,
  onFetch,
  onPaste,
  loading,
  detectedPlatform,
  error,
}: UrlBarProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onFetch();
    }
  };

  return (
    <>
      <div className="bar">
        <label className="in" htmlFor="url">
          <Icon name="dl" />
          <span hidden>Video or audio URL</span>
          <input
            id="url"
            placeholder="Paste a video or audio link…"
            autoComplete="off"
            value={url}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
          />
        </label>
        <button
          type="button"
          className="btn"
          id="paste"
          aria-label="Paste from clipboard"
          onClick={onPaste}
          disabled={loading}
        >
          <Icon name="c" />
          Paste
        </button>
        <button
          type="button"
          className="btn p"
          id="fetch"
          onClick={() => onFetch()}
          disabled={loading}
        >
          {loading ? "Fetching…" : "Fetch"}
        </button>
      </div>

      <div className="chips" id="plats" aria-label="Supported sites">
        {PLATFORMS.map((platform) => {
          const isOn =
            detectedPlatform.trim().toLowerCase() === platform.toLowerCase() ||
            (platform === "X" &&
              detectedPlatform.trim().toLowerCase() === "twitter");
          return (
            <span key={platform} className={`chip ${isOn ? "on" : ""}`}>
              {platform}
            </span>
          );
        })}
      </div>

      <div className="err" id="err" role="alert">
        {error}
      </div>
    </>
  );
}
