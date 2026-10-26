import React, { useRef } from "react";
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
  const inputRef = useRef<HTMLInputElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onFetch();
    }
  };

  const handleInputPaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData.getData("text");
    // Single-line pastes keep native input behaviour; lists are flattened in place.
    if (!/[\r\n\t]/.test(text)) return;
    e.preventDefault();
    const input = e.currentTarget;
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? start;
    const collapsed = text.replace(/[\r\n\t]+/g, " ").trim();
    onChange(
      input.value.slice(0, start) + collapsed + input.value.slice(end)
    );
    const caret = start + collapsed.length;
    requestAnimationFrame(() => {
      inputRef.current?.setSelectionRange(caret, caret);
    });
  };

  return (
    <>
      <div className="bar">
        <label className="in" htmlFor="url">
          <Icon name="dl" />
          <span hidden>Video or audio URL</span>
          <input
            ref={inputRef}
            id="url"
            placeholder="Paste one or more links…"
            autoComplete="off"
            value={url}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handleInputPaste}
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
        {error && (
          <div className="err-box">
            <Icon name="x" />
            <span>{error}</span>
            <button
              type="button"
              className="btn sm"
              onClick={() => onFetch()}
              disabled={loading}
            >
              Retry
            </button>
          </div>
        )}
      </div>
    </>
  );
}
