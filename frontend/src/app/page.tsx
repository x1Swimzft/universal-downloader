"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  fetchInfo,
  previewUrls,
  enqueueDownload,
  cancelQueueItem,
  pauseQueueItem,
  resumeQueueItem,
  retryQueueItem,
  clearFinishedQueue,
  deleteHistoryItem,
  clearHistory,
  getQueueStreamUrl,
  getAppSettings,
  updateAppSettings,
  ApiRequestError,
  pickSaveFolder,
  pickCookiesFile,
  openSaveFolder,
  triggerDesktopNotification,
  MediaInfo,
  PreviewEntry,
  QueueItem,
  DownloadFormat,
  AppSettings,
  HistoryItem,
} from "@/lib/api";
import { SvgSprite, Icon } from "@/components/Icons";
import { Sidebar, SidebarView } from "@/components/Sidebar";
import { UrlBar } from "@/components/UrlBar";
import {
  PreviewCard,
  DownloadChoices,
  DownloadMode,
} from "@/components/PreviewCard";
import { DownloadCard } from "@/components/DownloadCard";
import { HistoryView } from "@/components/HistoryView";
import { SettingsView } from "@/components/SettingsView";
import { Switch } from "@/components/Switch";
import {
  AppearanceSettings,
  APPEARANCE_STORAGE_KEY,
  DEFAULT_APPEARANCE,
  applyAppearance,
  readAppearance,
} from "@/lib/appearance";

const HISTORY_STORAGE_KEY = "ud_history_v1";

const PLATFORM_PATTERNS: Array<[string, RegExp]> = [
  ["YouTube", /youtu/i],
  ["Spotify", /spotify/i],
  ["Apple Music", /music\.apple\.com|apple music/i],
  ["TikTok", /tiktok/i],
  ["Instagram", /instagram/i],
  ["X", /twitter\.com|\bx\.com/i],
  ["Facebook", /facebook|fb\./i],
  ["Twitch", /twitch/i],
  ["Kick", /kick\.com/i],
  ["Bilibili", /bilibili/i],
  ["Reddit", /reddit/i],
  ["Pinterest", /pinterest|pin\.it/i],
  ["Vimeo", /vimeo/i],
  ["SoundCloud", /soundcloud/i],
  ["Bandcamp", /bandcamp/i],
];

function detectPlatformName(url: string): string {
  const found = PLATFORM_PATTERNS.find(([, re]) => re.test(url));
  return found ? found[0] : "";
}

function isMusicPlatform(value?: string): boolean {
  return /spotify|apple/i.test(value || "");
}

function parseUrls(value: string): string[] {
  const urls: string[] = [];
  for (const part of value.split(/[\s,]+/)) {
    const candidate = part.trim();
    if (/^https?:\/\//i.test(candidate) && !urls.includes(candidate)) {
      urls.push(candidate);
    }
  }
  return urls;
}

const AUTH_FETCH_ERROR_RE =
  /login|log in|cookie|403|forbidden|rate.?limit|too many requests|could not copy/i;

// Backend auth/cookie errors still arrive as raw extractor text from older builds.
function friendlyFetchError(message: string): string {
  if (!AUTH_FETCH_ERROR_RE.test(message)) return message;
  if (/could not copy|cookie.{0,40}(lock|in use)/i.test(message)) {
    return "The browser's cookie database is locked. Close Chrome or Edge, then retry, or choose a cookies.txt file in Settings.";
  }
  if (/rate.?limit|too many requests/i.test(message)) {
    return "The site is rate-limiting anonymous requests. Wait a minute, or enable Browser Cookies in Settings.";
  }
  return "This link needs a signed-in browser session. Open Settings, choose a browser with your login (or a cookies.txt file), then retry.";
}

function PreviewSkeleton() {
  return (
    <div className="sk" role="status" aria-label="Loading preview">
      <div className="sk-thumb" />
      <div className="sk-body">
        <div className="sk-line w80" />
        <div className="sk-line w40" />
        <div className="sk-line w60" />
      </div>
    </div>
  );
}

function mapSelectionToFormatQuality(
  mode: DownloadMode,
  selectedOption: string
): { format: DownloadFormat; quality: string } {
  if (mode === "Images") {
    return { format: "images", quality: "" };
  }
  if (mode === "Audio") {
    if (selectedOption === "M4A") return { format: "m4a", quality: "0" };
    if (selectedOption === "OPUS") return { format: "opus", quality: "0" };
    return { format: "mp3", quality: "320" };
  }
  const q = selectedOption.replace(/p$/i, "") || "1080";
  return { format: "mp4", quality: q };
}

function formatHistoryLabel(item: QueueItem): string {
  if (item.format === "images") return "Photos";
  if (item.format === "m4a") return "M4A";
  if (item.format === "opus") return "OPUS";
  if (item.format === "mp3") return `MP3 ${item.quality.replace(/k$/i, "") || "320"}k`;
  return `${item.quality.replace(/p$/i, "") || "1080"}p`;
}

export default function Home() {
  const [activeView, setActiveView] = useState<SidebarView>("dl");
  const [url, setUrl] = useState("");
  const [detectedPlatform, setDetectedPlatform] = useState("");
  const [loadingInfo, setLoadingInfo] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [fetchErrorAction, setFetchErrorAction] = useState<"open_settings" | "">(
    ""
  );
  const [info, setInfo] = useState<MediaInfo | null>(null);
  const [mode, setMode] = useState<DownloadMode>("Video");
  const [selectedOption, setSelectedOption] = useState("1080p");
  const [startingDownload, setStartingDownload] = useState(false);

  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [appearance, setAppearance] =
    useState<AppearanceSettings>(DEFAULT_APPEARANCE);
  const [appearanceReady, setAppearanceReady] = useState(false);
  const [settings, setSettings] = useState<AppSettings>({
    autoDetectClipboard: true,
    minimizeToTray: true,
    notifyWhenFinished: true,
    maxConcurrent: 3,
    audioFilenameTemplate: "{artist} - {title}",
    saveFolder: "Downloads\\Universal Downloader",
    theme: "dark",
    cookiesFromBrowser: "none",
    cookiesFile: "",
    socialBypass: false,
    quickFetchHotkeyEnabled: true,
  });

  const completedIdsRef = useRef<Set<string>>(new Set());
  const settingsRef = useRef<AppSettings>(settings);
  settingsRef.current = settings;

  useEffect(() => {
    setAppearance(readAppearance());
    setAppearanceReady(true);
  }, []);

  useEffect(() => {
    if (!appearanceReady) return;
    applyAppearance(appearance);
    try {
      localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(appearance));
    } catch {}
    if (appearance.theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const syncSystemTheme = () => applyAppearance(appearance);
    media.addEventListener("change", syncSystemTheme);
    return () => media.removeEventListener("change", syncSystemTheme);
  }, [appearance, appearanceReady]);

  // Load history from localStorage, and settings from Electron IPC / backend
  useEffect(() => {
    try {
      const raw = localStorage.getItem(HISTORY_STORAGE_KEY);
      if (raw) {
        const parsed: HistoryItem[] = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          setHistoryItems(parsed);
          parsed.forEach((h) => completedIdsRef.current.add(h.id));
        }
      }
    } catch {}

    getAppSettings().then((loaded) => {
      setSettings(loaded);
    });

    if (typeof window !== "undefined" && window.electronAPI) {
      return window.electronAPI.onSettingsUpdated((updated) => {
        setSettings(updated);
      });
    }
  }, []);

  // Connect to SSE stream for Queue updates
  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(getQueueStreamUrl());
      es.onmessage = (event) => {
        try {
          const data: QueueItem[] = JSON.parse(event.data);
          if (!Array.isArray(data)) return;
          setQueueItems(data);

          const newlyFinished: HistoryItem[] = [];
          for (const item of data) {
            const isDone = item.status === "completed" || item.status === "done";
            if (isDone && !completedIdsRef.current.has(item.id)) {
              completedIdsRef.current.add(item.id);
              newlyFinished.push({
                id: item.id,
                url: item.url,
                title: item.title || item.url,
                format: item.format,
                quality: item.quality,
                label: formatHistoryLabel(item),
                platform: item.platform,
                filename: item.filename,
                completedAt: Date.now(),
                start_time: item.start_time,
                end_time: item.end_time,
                preset: item.preset,
                social_bypass: item.social_bypass,
              });
              if (settingsRef.current.notifyWhenFinished) {
                triggerDesktopNotification(
                  "Download finished",
                  item.title || item.url
                ).catch(() => {});
              }
            }
          }

          if (newlyFinished.length > 0) {
            setHistoryItems((prev) => {
              const updated = [...newlyFinished, ...prev].slice(0, 100);
              try {
                localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(updated));
              } catch {}
              return updated;
            });
          }
        } catch {}
      };
    } catch {}

    return () => {
      if (es) es.close();
    };
  }, []);

  const handleFetchInfo = useCallback(
    async (overrideUrl?: string) => {
      const urls = parseUrls(overrideUrl !== undefined ? overrideUrl : url);
      setInfo(null);
      if (urls.length === 0) {
        setErrorMsg(
          "That doesn't look like a link. Paste a full URL starting with https://"
        );
        setFetchErrorAction("");
        return;
      }
      setErrorMsg("");
      setFetchErrorAction("");
      const singlePlatform =
        urls.length === 1 ? detectPlatformName(urls[0]) : "";
      setDetectedPlatform(singlePlatform);
      setLoadingInfo(true);
      try {
        if (urls.length === 1) {
          const media = await fetchInfo(urls[0]);
          setInfo(media);
          if (!singlePlatform && media.platform) {
            setDetectedPlatform(media.platform);
          }
          const isImagePost =
            media.media_type === "image" || media.media_type === "carousel";
          const isPlaylist = Boolean(media.entries?.length);
          const hasVideo = media.formats?.some(
            (f) => f.resolution && f.resolution !== "audio"
          );
          const music =
            isMusicPlatform(media.platform) || isMusicPlatform(urls[0]);
          if (music) {
            setMode("Audio");
            setSelectedOption("MP3 320k");
          } else if (isImagePost) {
            setMode("Images");
            setSelectedOption("1080p");
          } else if (isPlaylist) {
            setMode("Video");
            setSelectedOption("1080p");
          } else if (!hasVideo || media.platform === "soundcloud") {
            setMode("Audio");
            setSelectedOption("MP3 320k");
          } else {
            setMode("Video");
            setSelectedOption("1080p");
          }
        } else {
          const preview = await previewUrls(urls);
          const musicBatch =
            preview.items.length > 0 &&
            preview.items.every((entry) => isMusicPlatform(entry.platform));
          setInfo({
            title: `${urls.length} links`,
            media_type: "playlist",
            platform: "Multiple",
            entries: preview.items,
            formats: [],
          });
          setMode(musicBatch ? "Audio" : "Video");
          setSelectedOption(musicBatch ? "MP3 320k" : "1080p");
          if (preview.failed?.length) {
            setErrorMsg(
              `Skipped ${preview.failed.length} link${
                preview.failed.length === 1 ? "" : "s"
              } that could not be inspected.`
            );
          }
        }
      } catch (e: unknown) {
        const message =
          e instanceof Error ? e.message : "Failed to fetch link info";
        const backendAction =
          e instanceof ApiRequestError ? e.action : undefined;
        const needsSettings =
          backendAction === "open_settings" || AUTH_FETCH_ERROR_RE.test(message);
        setErrorMsg(
          backendAction === "open_settings" ? message : friendlyFetchError(message)
        );
        setFetchErrorAction(needsSettings ? "open_settings" : "");
      } finally {
        setLoadingInfo(false);
      }
    },
    [url]
  );

  // Listen for clipboard URL detection from Electron
  useEffect(() => {
    function handleClipboard(e: Event) {
      if (!settingsRef.current.autoDetectClipboard) return;
      const customEvent = e as CustomEvent<string>;
      const detected = customEvent.detail;
      if (!detected) return;
      setUrl(detected);
      setDetectedPlatform(detectPlatformName(detected));
      setActiveView("dl");
      handleFetchInfo(detected);
    }

    window.addEventListener("clipboard-url-detected", handleClipboard);
    return () => window.removeEventListener("clipboard-url-detected", handleClipboard);
  }, [handleFetchInfo]);

  const handleUrlChange = (val: string) => {
    setUrl(val);
    setDetectedPlatform(detectPlatformName(val));
    if (errorMsg) setErrorMsg("");
    setFetchErrorAction("");
  };

  const handlePaste = async () => {
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (text) {
        setUrl(text);
        setDetectedPlatform(detectPlatformName(text));
        await handleFetchInfo(text);
      }
    } catch {
      setErrorMsg("Clipboard access was blocked. Paste with Ctrl+V instead.");
      setFetchErrorAction("");
    }
  };

  const handleModeChange = (nextMode: DownloadMode) => {
    setMode(nextMode);
    setSelectedOption(
      nextMode === "Video"
        ? "1080p"
        : nextMode === "Audio"
          ? "MP3 320k"
          : "1080p" // unused for Images, keeps a sane fallback value
    );
  };

  const handleStartDownload = async (choices?: DownloadChoices) => {
    if (!info || !url.trim()) return;
    setStartingDownload(true);
    setErrorMsg("");
    setFetchErrorAction("");
    try {
      const { format, quality } = mapSelectionToFormatQuality(
        mode,
        selectedOption
      );
      await enqueueDownload(url.trim(), format, quality, info.title, {
        ...choices,
        socialBypass: settings.socialBypass,
        ...(isMusicPlatform(info.platform) || isMusicPlatform(url)
          ? {
              artist: info.artist,
              album: info.album,
              trackNumber: info.track_number,
              searchQuery: info.search_query,
              thumbnail: info.thumbnail,
            }
          : {}),
      });
      setActiveView("q");
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Failed to start download");
    } finally {
      setStartingDownload(false);
    }
  };

  const handleEnqueueSelected = async (
    entries: PreviewEntry[],
    choices?: DownloadChoices
  ) => {
    if (!info || entries.length === 0) return;
    setStartingDownload(true);
    setErrorMsg("");
    setFetchErrorAction("");
    try {
      const { format, quality } = mapSelectionToFormatQuality(
        mode,
        selectedOption
      );
      const allEntries = info.entries || [];
      const isBatch = info.platform === "Multiple";
      for (let position = 0; position < entries.length; position += 1) {
        const entry = entries[position];
        const entryIsMusic =
          Boolean(entry.search_query) || isMusicPlatform(entry.platform);
        const playlistIndex = allEntries.findIndex(
          (candidate) => candidate.url === entry.url
        );
        const trackNumber = isBatch
          ? undefined
          : entry.track_number ??
            (playlistIndex >= 0 ? playlistIndex : position) + 1;
        await enqueueDownload(entry.url, format, quality, entry.title, {
          ...choices,
          socialBypass: settings.socialBypass,
          trackNumber,
          ...(entryIsMusic
            ? {
                artist: entry.artist,
                album: entry.album,
                searchQuery: entry.search_query,
                thumbnail: entry.thumbnail,
              }
            : {}),
          ...(isBatch
            ? {}
            : {
                playlistTitle: info.title,
                saveInSubfolder: choices?.saveInSubfolder ?? true,
              }),
        });
      }
      setActiveView("q");
    } catch (e: unknown) {
      setErrorMsg(
        e instanceof Error ? e.message : "Failed to enqueue selected links"
      );
    } finally {
      setStartingDownload(false);
    }
  };

  const handleCancelQueueItem = async (jobId: string) => {
    setQueueItems((prev) => prev.filter((i) => i.id !== jobId));
    try {
      await cancelQueueItem(jobId);
    } catch {}
  };

  const handlePauseQueueItem = async (jobId: string) => {
    setQueueItems((prev) =>
      prev.map((item) =>
        item.id === jobId
          ? { ...item, status: "paused" as const, speed: 0 }
          : item
      )
    );
    try {
      await pauseQueueItem(jobId);
    } catch {}
  };

  const handleResumeQueueItem = async (jobId: string) => {
    setQueueItems((prev) =>
      prev.map((item) =>
        item.id === jobId
          ? {
              ...item,
              status: "queued" as const,
              speed: 0,
              error: undefined,
              error_code: undefined,
            }
          : item
      )
    );
    try {
      await resumeQueueItem(jobId);
    } catch {}
  };

  const handleRetryQueueItem = async (jobId: string) => {
    setQueueItems((prev) =>
      prev.map((item) =>
        item.id === jobId
          ? {
              ...item,
              status: "queued" as const,
              progress: 0,
              speed: 0,
              filename: undefined,
              error: undefined,
              error_code: undefined,
              retry_count: 0,
            }
          : item
      )
    );
    try {
      await retryQueueItem(jobId);
    } catch {}
  };

  const handleClearFinished = async () => {
    setQueueItems((prev) =>
      prev.filter((item) => item.status !== "completed" && item.status !== "done")
    );
    try {
      await clearFinishedQueue();
    } catch {}
  };

  const handleOpenSettingsFromQueue = () => {
    setActiveView("s");
  };

  const handleOpenCookieSettings = () => {
    setActiveView("s");
    requestAnimationFrame(() => {
      const target = document.getElementById("cookies-source");
      if (!target) return;
      target.scrollIntoView({ block: "center", behavior: "smooth" });
      target.focus();
    });
  };

  const handleRedownload = async (item: HistoryItem) => {
    try {
      await enqueueDownload(item.url, item.format, item.quality, item.title, {
        startTime: item.start_time,
        endTime: item.end_time,
        preset: item.preset,
        socialBypass: item.social_bypass,
      });
      setActiveView("q");
    } catch {}
  };

  const handleDeleteHistoryItem = (item: HistoryItem) => {
    // Keep the id in completedIdsRef so a queue SSE broadcast cannot re-add it.
    setHistoryItems((prev) => {
      const updated = prev.filter((entry) => entry.id !== item.id);
      try {
        localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(updated));
      } catch {}
      return updated;
    });
    deleteHistoryItem(item.id).catch(() => {});
  };

  const handleClearHistory = () => {
    setHistoryItems([]);
    try {
      localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify([]));
    } catch {}
    clearHistory().catch(() => {});
  };

  const handleOpenFolder = async (filepath?: string) => {
    try {
      await openSaveFolder(filepath);
    } catch {}
  };

  const handleUpdateSettings = async (patch: Partial<AppSettings>) => {
    const next = { ...settings, ...patch };
    setSettings(next);
    const saved = await updateAppSettings(patch);
    setSettings(saved);
  };

  const handleUpdateAppearance = (patch: Partial<AppearanceSettings>) => {
    setAppearance((current) => ({ ...current, ...patch }));
  };

  const handlePickFolder = async () => {
    const updated = await pickSaveFolder();
    setSettings(updated);
  };

  const handlePickCookiesFile = async () => {
    const updated = await pickCookiesFile();
    setSettings(updated);
  };

  const handleToggleTheme = () => {
    const currentTheme =
      document.documentElement.dataset.theme === "light" ? "light" : "dark";
    setAppearance((current) => ({
      ...current,
      theme: currentTheme === "dark" ? "light" : "dark",
    }));
  };

  const activeQueueCount = queueItems.filter(
    (i) => i.status === "queued" || i.status === "downloading"
  ).length;
  const finishedQueueCount = queueItems.filter(
    (i) => i.status === "completed" || i.status === "done"
  ).length;

  return (
    <>
      <SvgSprite />
      <div className="app">
        <Sidebar
          activeView={activeView}
          onSelectView={setActiveView}
          activeQueueCount={activeQueueCount}
          onToggleTheme={handleToggleTheme}
          versionText="v0.7.1 · Pro"
        />

        <main>
          <div className="wrap">
            {/* Download View */}
            <section
              className={`v ${activeView === "dl" ? "show" : ""}`}
              id="v-dl"
            >
              <div className="page-head">
                <div className="cap">Download</div>
                <h1>
                  Paste a link. <span>Get the file.</span>
                </h1>
                <p className="sub">
                  One place for every video and audio link - fast, private, and on
                  your own PC.
                </p>
              </div>

              <div className="card">
                <UrlBar
                  url={url}
                  onChange={handleUrlChange}
                  onFetch={handleFetchInfo}
                  onPaste={handlePaste}
                  loading={loadingInfo}
                  detectedPlatform={detectedPlatform}
                  error={errorMsg}
                  showSettings={fetchErrorAction === "open_settings"}
                  onOpenSettings={handleOpenCookieSettings}
                />

                <div className="watch">
                  <div>
                    <span className="watch-label">Clipboard watch</span>
                    <span className="watch-status">
                      {settings.autoDetectClipboard
                        ? "On · copied links are detected"
                        : "Off · paste a link manually"}
                    </span>
                  </div>
                  <Switch
                    checked={settings.autoDetectClipboard}
                    onChange={(val) =>
                      handleUpdateSettings({ autoDetectClipboard: val })
                    }
                    ariaLabel="Auto-detect copied links"
                  />
                </div>

                {loadingInfo && !info && <PreviewSkeleton />}

                {info && (
                  <PreviewCard
                    info={info}
                    mode={mode}
                    onModeChange={handleModeChange}
                    selectedOption={selectedOption}
                    onSelectOption={setSelectedOption}
                    saveFolder={settings.saveFolder}
                    onDownload={handleStartDownload}
                    downloading={startingDownload}
                    onEnqueueSelected={handleEnqueueSelected}
                    enqueueing={startingDownload}
                  />
                )}
              </div>

              <div className="hint">
                <Icon name="c" />
                Tip: copy a link and it&apos;s detected automatically.
              </div>
            </section>

            {/* Queue View */}
            <section
              className={`v ${activeView === "q" ? "show" : ""}`}
              id="v-q"
            >
              <div className="page-head queue-head">
                <div>
                  <div className="cap">Queue</div>
                  <h2>Active downloads</h2>
                </div>
                <div className="queue-tools">
                  <span className="queue-count">
                    {activeQueueCount} / {settings.maxConcurrent} active
                  </span>
                  {finishedQueueCount > 0 && (
                    <button
                      type="button"
                      className="btn sm"
                      onClick={handleClearFinished}
                    >
                      Clear finished
                    </button>
                  )}
                </div>
              </div>
              {queueItems.length === 0 ? (
                <div className="empty">
                  Nothing downloading. Paste a link to start.
                </div>
              ) : (
                <div className="group" id="ql">
                  {queueItems.map((item) => (
                    <DownloadCard
                      key={item.id}
                      item={item}
                      onCancel={handleCancelQueueItem}
                      onPause={handlePauseQueueItem}
                      onResume={handleResumeQueueItem}
                      onRetry={handleRetryQueueItem}
                      onOpenSettings={handleOpenSettingsFromQueue}
                    />
                  ))}
                </div>
              )}
            </section>

            {/* History View */}
            <section
              className={`v ${activeView === "h" ? "show" : ""}`}
              id="v-h"
            >
              <HistoryView
                items={historyItems}
                onOpenFolder={handleOpenFolder}
                onRedownload={handleRedownload}
                onDelete={handleDeleteHistoryItem}
                onClearAll={handleClearHistory}
              />
            </section>

            {/* Settings View */}
            <section
              className={`v ${activeView === "s" ? "show" : ""}`}
              id="v-s"
            >
              <SettingsView
                settings={settings}
                appearance={appearance}
                onUpdate={handleUpdateSettings}
                onUpdateAppearance={handleUpdateAppearance}
                onPickFolder={handlePickFolder}
                onPickCookiesFile={handlePickCookiesFile}
              />
            </section>

          </div>
        </main>
      </div>
    </>
  );
}
