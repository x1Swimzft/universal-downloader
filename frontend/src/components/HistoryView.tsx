import React, { useEffect, useMemo, useRef, useState } from "react";
import { HistoryItem, startDragFile } from "../lib/api";
import { Icon } from "./Icons";

export interface HistoryViewProps {
  items: HistoryItem[];
  onOpenFolder: (filepath?: string) => void;
  onRedownload: (item: HistoryItem) => void;
  onDelete: (item: HistoryItem) => void;
  onClearAll: () => void;
}

type MediaFilter = "all" | "video" | "audio" | "photos";

const MEDIA_FILTERS: Array<{ value: MediaFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "video", label: "Video" },
  { value: "audio", label: "Audio" },
  { value: "photos", label: "Photos" },
];

const PLATFORM_FILTERS = [
  "all",
  "YouTube",
  "TikTok",
  "Instagram",
  "X",
  "Facebook",
  "SoundCloud",
];

function matchesMedia(item: HistoryItem, filter: MediaFilter): boolean {
  const format = (item.format || "").toLowerCase();
  if (filter === "video") return format === "mp4";
  if (filter === "audio") return ["mp3", "m4a", "opus"].includes(format);
  if (filter === "photos") return format === "images";
  return true;
}

function matchesPlatform(item: HistoryItem, filter: string): boolean {
  if (filter === "all") return true;
  const platform = (item.platform || "").toLowerCase();
  const wanted = filter.toLowerCase();
  return platform === wanted || (wanted === "x" && platform === "twitter");
}

export function HistoryView({
  items,
  onOpenFolder,
  onRedownload,
  onDelete,
  onClearAll,
}: HistoryViewProps) {
  const [query, setQuery] = useState("");
  const [media, setMedia] = useState<MediaFilter>("all");
  const [platform, setPlatform] = useState("all");
  const [confirmClear, setConfirmClear] = useState(false);
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (confirmTimer.current) clearTimeout(confirmTimer.current);
    };
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => {
      const matchesSearch =
        !needle ||
        [item.title, item.url, item.platform]
          .filter(Boolean)
          .join("\n")
          .toLowerCase()
          .includes(needle);
      return (
        matchesSearch &&
        matchesMedia(item, media) &&
        matchesPlatform(item, platform)
      );
    });
  }, [items, query, media, platform]);

  const resetFilters = () => {
    setQuery("");
    setMedia("all");
    setPlatform("all");
  };

  const handleClearClick = () => {
    if (confirmClear) {
      if (confirmTimer.current) clearTimeout(confirmTimer.current);
      confirmTimer.current = null;
      setConfirmClear(false);
      onClearAll();
      return;
    }
    setConfirmClear(true);
    confirmTimer.current = setTimeout(() => {
      confirmTimer.current = null;
      setConfirmClear(false);
    }, 3000);
  };

  return (
    <>
      <div className="page-head">
        <div className="cap">Library</div>
        <h2>History</h2>
      </div>
      {items.length === 0 ? (
        <div className="empty">Finished downloads will show up here.</div>
      ) : (
        <>
          <div className="hist-toolbar">
            <input
              className="hist-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search history…"
              aria-label="Search history"
            />
            <div
              className="hist-filters"
              role="group"
              aria-label="Filter by media type"
            >
              {MEDIA_FILTERS.map((filter) => (
                <button
                  key={filter.value}
                  type="button"
                  className={`chip ${media === filter.value ? "on" : ""}`}
                  aria-pressed={media === filter.value}
                  onClick={() => setMedia(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
            <div
              className="hist-filters"
              role="group"
              aria-label="Filter by platform"
            >
              {PLATFORM_FILTERS.map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`chip ${platform === value ? "on" : ""}`}
                  aria-pressed={platform === value}
                  onClick={() => setPlatform(value)}
                >
                  {value === "all" ? "All platforms" : value}
                </button>
              ))}
            </div>
            <button
              type="button"
              className={`chip ${confirmClear ? "on" : ""}`}
              onClick={handleClearClick}
              aria-label={
                confirmClear ? "Confirm clear all history" : "Clear all history"
              }
            >
              <Icon name="x" />
              {confirmClear ? "Confirm clear?" : "Clear history"}
            </button>
          </div>
          {filtered.length === 0 ? (
            <div className="empty hist-empty">
              <span>No downloads match your search and filters.</span>
              <button type="button" className="chip" onClick={resetFilters}>
                Reset filters
              </button>
            </div>
          ) : (
            <div className="group" id="hl">
              {filtered.map((item) => (
                <div
                  key={`${item.id}-${item.completedAt}`}
                  className="hrow"
                  draggable={Boolean(item.filename)}
                  onDragStart={(event) => {
                    if (!item.filename) return;
                    event.preventDefault();
                    startDragFile(item.filename).catch(() => {});
                  }}
                  title={
                    item.filename
                      ? "Drag into OBS, DaVinci Resolve, or CapCut"
                      : undefined
                  }
                >
                  <div className="hmain">
                    <span className="htitle" title={item.title}>
                      {item.title}
                    </span>
                    <span className="hmeta">
                      {item.label}
                      {item.platform ? ` · ${item.platform}` : ""}
                    </span>
                  </div>
                  <div className="hactions">
                    <button
                      type="button"
                      className="chip"
                      onClick={() => onOpenFolder(item.filename)}
                      aria-label={`Open folder for ${item.title}`}
                    >
                      <Icon name="f" />
                      Open folder
                    </button>
                    <button
                      type="button"
                      className="chip"
                      onClick={() => onRedownload(item)}
                      aria-label={`Download ${item.title} again`}
                    >
                      <Icon name="r" />
                      Download again
                    </button>
                    <button
                      type="button"
                      className="chip"
                      onClick={() => onDelete(item)}
                      aria-label={`Delete ${item.title} from history`}
                    >
                      <Icon name="x" />
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
