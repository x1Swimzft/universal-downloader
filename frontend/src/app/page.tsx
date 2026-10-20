"use client";

import { useState, useRef, useEffect } from "react";
import Image from "next/image";
import {
  fetchInfo,
  startDownload,
  pollProgress,
  getFileUrl,
  addBatchToQueue,
  getQueueStreamUrl,
  MediaInfo,
  JobStatus,
  QueueItem,
} from "@/lib/api";

type Format = "mp3" | "mp4";
type Stage = "idle" | "loading-info" | "ready" | "downloading" | "done" | "error";

const MP3_QUALITIES = ["320", "192", "128"] as const;
const MP4_QUALITIES = ["2160", "1440", "1080", "720", "480", "360"] as const;

export default function Home() {
  const [mode, setMode] = useState<"single" | "batch">("single");

  // Single URL state
  const [url, setUrl] = useState("");
  const [format, setFormat] = useState<Format>("mp4");
  const [quality, setQuality] = useState("1080");
  const [info, setInfo] = useState<MediaInfo | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  // Batch / Queue state
  const [batchUrls, setBatchUrls] = useState("");
  const [batchFormat, setBatchFormat] = useState<Format>("mp4");
  const [batchQuality, setBatchQuality] = useState("1080");
  const [isSubmittingBatch, setIsSubmittingBatch] = useState(false);
  const [batchError, setBatchError] = useState("");
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);

  // SSE stream for queue updates
  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(getQueueStreamUrl());
      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (Array.isArray(data)) {
            setQueueItems(data);
          }
        } catch (err) {
          console.error("SSE parse error", err);
        }
      };
      es.onerror = () => {
        // EventSource will automatically reconnect
      };
    } catch (err) {
      console.error("Failed to connect to SSE", err);
    }

    return () => {
      if (es) {
        es.close();
      }
    };
  }, []);

  // Listen for clipboard detection from Electron
  useEffect(() => {
    function handleClipboard(e: Event) {
      const customEvent = e as CustomEvent<string>;
      const detectedUrl = customEvent.detail;
      if (!detectedUrl) return;

      if (mode === "single") {
        setUrl(detectedUrl);
      } else {
        setBatchUrls((prev) => {
          const lines = prev.split("\n").map((l) => l.trim()).filter(Boolean);
          if (!lines.includes(detectedUrl)) {
            return prev.trim() ? `${prev.trim()}\n${detectedUrl}` : detectedUrl;
          }
          return prev;
        });
      }
    }

    window.addEventListener("clipboard-url-detected", handleClipboard);
    return () => window.removeEventListener("clipboard-url-detected", handleClipboard);
  }, [mode]);

  function handleFormatChange(f: Format) {
    setFormat(f);
    setQuality(f === "mp3" ? "320" : "1080");
  }

  function handleBatchFormatChange(f: Format) {
    setBatchFormat(f);
    setBatchQuality(f === "mp3" ? "320" : "1080");
  }

  async function handleFetchInfo() {
    if (!url.trim()) return;
    setStage("loading-info");
    setInfo(null);
    setErrorMsg("");
    try {
      const data = await fetchInfo(url.trim());
      setInfo(data);
      setStage("ready");
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Unknown error");
      setStage("error");
    }
  }

  async function handleDownload() {
    if (!url || !info) return;
    setStage("downloading");
    setProgress(0);
    setErrorMsg("");
    try {
      const { job_id } = await startDownload(url.trim(), format, quality, info.title);
      setJobId(job_id);
      pollRef.current = setInterval(async () => {
        const status: JobStatus = await pollProgress(job_id);
        setProgress(status.progress);
        if (status.status === "done") {
          clearInterval(pollRef.current!);
          setProgress(100);
          setStage("done");
        } else if (status.status === "error") {
          clearInterval(pollRef.current!);
          setErrorMsg(status.error || "Download failed");
          setStage("error");
        }
      }, 1500);
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Unknown error");
      setStage("error");
    }
  }

  function handleReset() {
    if (pollRef.current) clearInterval(pollRef.current);
    setUrl("");
    setInfo(null);
    setStage("idle");
    setProgress(0);
    setJobId(null);
    setErrorMsg("");
    setFormat("mp4");
    setQuality("720");
  }

  async function handleAddBatch() {
    const urls = batchUrls
      .split("\n")
      .map((u) => u.trim())
      .filter((u) => u.length > 0);
    if (urls.length === 0) return;

    setIsSubmittingBatch(true);
    setBatchError("");
    try {
      await addBatchToQueue(urls, batchFormat, batchQuality);
      setBatchUrls("");
    } catch (e: unknown) {
      setBatchError(e instanceof Error ? e.message : "Failed to add to queue");
    } finally {
      setIsSubmittingBatch(false);
    }
  }

  const singleQualities = format === "mp3" ? MP3_QUALITIES : MP4_QUALITIES;
  const batchQualities = batchFormat === "mp3" ? MP3_QUALITIES : MP4_QUALITIES;

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-start py-16 px-4">
      {/* Header */}
      <div className="mb-8 text-center">
        <h1 className="text-4xl font-bold tracking-tight mb-2">
          Universal <span className="text-violet-400">Downloader</span>
        </h1>
        <p className="text-gray-400 text-sm">
          YouTube · TikTok · Instagram · Twitter/X · Facebook · SoundCloud
        </p>
      </div>

      {/* Main Card */}
      <div className="w-full max-w-2xl bg-gray-900 rounded-2xl shadow-2xl p-8 space-y-6">
        {/* Mode Tabs */}
        <div className="flex border-b border-gray-800 pb-3 gap-6 text-sm font-semibold">
          <button
            onClick={() => setMode("single")}
            className={`transition pb-1 border-b-2 ${
              mode === "single"
                ? "border-violet-500 text-violet-400"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            Single Download
          </button>
          <button
            onClick={() => setMode("batch")}
            className={`transition pb-1 border-b-2 ${
              mode === "batch"
                ? "border-violet-500 text-violet-400"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            Batch / Queue
          </button>
        </div>

        {/* SINGLE MODE */}
        {mode === "single" && (
          <div className="space-y-6">
            {/* URL Input */}
            <div className="flex gap-2">
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleFetchInfo()}
                placeholder="Paste video / audio URL here…"
                disabled={stage === "loading-info" || stage === "downloading"}
                className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-sm outline-none focus:border-violet-500 transition disabled:opacity-50"
              />
              <button
                onClick={handleFetchInfo}
                disabled={!url.trim() || stage === "loading-info" || stage === "downloading"}
                className="bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded-xl px-5 py-3 text-sm font-semibold transition"
              >
                {stage === "loading-info" ? "Loading…" : "Fetch"}
              </button>
            </div>

            {/* Media Info Preview */}
            {info && (stage === "ready" || stage === "downloading" || stage === "done") && (
              <div className="flex gap-4 items-start bg-gray-800 rounded-xl p-4">
                {info.thumbnail && (
                  <div className="relative w-28 h-16 flex-shrink-0 rounded-lg overflow-hidden">
                    <Image
                      src={info.thumbnail}
                      alt="thumbnail"
                      fill
                      className="object-cover"
                      unoptimized
                    />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-sm leading-snug line-clamp-2">{info.title}</p>
                  <p className="text-xs text-gray-400 mt-1">
                    {info.uploader && <span>{info.uploader}</span>}
                    {info.duration && (
                      <span className="ml-2">
                        {Math.floor(info.duration / 60)}:{String(info.duration % 60).padStart(2, "0")}
                      </span>
                    )}
                    {info.platform && (
                      <span className="ml-2 capitalize text-violet-400">{info.platform}</span>
                    )}
                  </p>
                </div>
              </div>
            )}

            {/* Format + Quality */}
            {(stage === "ready" || stage === "downloading" || stage === "done") && (
              <div className="space-y-4">
                {/* Format Toggle */}
                <div className="flex rounded-xl overflow-hidden border border-gray-700">
                  {(["mp4", "mp3"] as Format[]).map((f) => (
                    <button
                      key={f}
                      onClick={() => handleFormatChange(f)}
                      disabled={stage === "downloading"}
                      className={`flex-1 py-2.5 text-sm font-semibold transition ${
                        format === f
                          ? "bg-violet-600 text-white"
                          : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                      } disabled:opacity-50`}
                    >
                      {f.toUpperCase()}
                    </button>
                  ))}
                </div>

                {/* Quality */}
                <div className="flex gap-2 flex-wrap">
                  {singleQualities.map((q) => (
                    <button
                      key={q}
                      onClick={() => setQuality(q)}
                      disabled={stage === "downloading"}
                      className={`px-4 py-2 rounded-lg text-sm font-medium border transition ${
                        quality === q
                          ? "border-violet-500 bg-violet-900/40 text-violet-300"
                          : "border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-500"
                      } disabled:opacity-50`}
                    >
                      {format === "mp3" ? `${q} kbps` : `${q}p`}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Progress Bar */}
            {stage === "downloading" && (
              <div className="space-y-2">
                <div className="flex justify-between text-xs text-gray-400">
                  <span>Processing…</span>
                  <span>{progress.toFixed(0)}%</span>
                </div>
                <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-violet-500 transition-all duration-500 rounded-full"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}

            {/* Error */}
            {stage === "error" && (
              <div className="bg-red-900/30 border border-red-700 text-red-300 text-sm rounded-xl px-4 py-3">
                ⚠ {errorMsg}
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3">
              {stage === "ready" && (
                <button
                  onClick={handleDownload}
                  className="flex-1 bg-violet-600 hover:bg-violet-500 rounded-xl py-3 text-sm font-semibold transition"
                >
                  Download {format.toUpperCase()}
                </button>
              )}

              {stage === "done" && jobId && (
                <a
                  href={getFileUrl(jobId)}
                  download={info?.title ? `${info.title}.${format}` : undefined}
                  className="flex-1 text-center bg-green-600 hover:bg-green-500 rounded-xl py-3 text-sm font-semibold transition"
                >
                  ✓ Save File
                </a>
              )}

              {(stage === "ready" || stage === "done" || stage === "error") && (
                <button
                  onClick={handleReset}
                  className="px-5 py-3 bg-gray-800 hover:bg-gray-700 rounded-xl text-sm text-gray-400 transition"
                >
                  Reset
                </button>
              )}
            </div>
          </div>
        )}

        {/* BATCH MODE */}
        {mode === "batch" && (
          <div className="space-y-5">
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-2">
                Enter video or audio URLs (one per line):
              </label>
              <textarea
                rows={5}
                value={batchUrls}
                onChange={(e) => setBatchUrls(e.target.value)}
                placeholder="https://www.youtube.com/watch?v=...&#10;https://www.tiktok.com/@user/video/...&#10;https://www.instagram.com/reel/..."
                disabled={isSubmittingBatch}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-sm outline-none focus:border-violet-500 transition disabled:opacity-50 resize-y font-mono"
              />
            </div>

            {/* Batch Format Toggle */}
            <div className="space-y-3">
              <div className="flex rounded-xl overflow-hidden border border-gray-700">
                {(["mp4", "mp3"] as Format[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => handleBatchFormatChange(f)}
                    disabled={isSubmittingBatch}
                    className={`flex-1 py-2.5 text-sm font-semibold transition ${
                      batchFormat === f
                        ? "bg-violet-600 text-white"
                        : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                    } disabled:opacity-50`}
                  >
                    {f.toUpperCase()}
                  </button>
                ))}
              </div>

              {/* Batch Quality */}
              <div className="flex gap-2 flex-wrap">
                {batchQualities.map((q) => (
                  <button
                    key={q}
                    onClick={() => setBatchQuality(q)}
                    disabled={isSubmittingBatch}
                    className={`px-4 py-2 rounded-lg text-sm font-medium border transition ${
                      batchQuality === q
                        ? "border-violet-500 bg-violet-900/40 text-violet-300"
                        : "border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-500"
                    } disabled:opacity-50`}
                  >
                    {batchFormat === "mp3" ? `${q} kbps` : `${q}p`}
                  </button>
                ))}
              </div>
            </div>

            {/* Batch Error */}
            {batchError && (
              <div className="bg-red-900/30 border border-red-700 text-red-300 text-sm rounded-xl px-4 py-3">
                ⚠ {batchError}
              </div>
            )}

            <button
              onClick={handleAddBatch}
              disabled={!batchUrls.trim() || isSubmittingBatch}
              className="w-full bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded-xl py-3 text-sm font-semibold transition"
            >
              {isSubmittingBatch ? "Adding to Queue…" : "Add to Download Queue"}
            </button>
          </div>
        )}
      </div>

      {/* QUEUE CARDS SECTION */}
      {queueItems.length > 0 && (
        <div className="w-full max-w-2xl mt-8 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <span>Download Queue</span>
              <span className="text-xs bg-violet-950 text-violet-300 border border-violet-800 px-2 py-0.5 rounded-full font-mono">
                {queueItems.length}
              </span>
            </h2>
          </div>

          <div className="space-y-3">
            {queueItems.map((item) => {
              const isCompleted = item.status === "completed" || item.status === "done";
              return (
                <div
                  key={item.id}
                  className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col gap-3 shadow-lg"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p
                        className="text-sm font-medium text-white truncate"
                        title={item.title || item.url}
                      >
                        {item.title || item.url}
                      </p>
                      <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                        <span className="text-xs uppercase bg-gray-800 text-gray-300 px-2 py-0.5 rounded font-mono">
                          {item.format} · {item.format === "mp3" ? `${item.quality}kbps` : `${item.quality}p`}
                        </span>
                        <span
                          className={`text-xs px-2 py-0.5 rounded font-medium ${
                            isCompleted
                              ? "bg-green-950 text-green-400 border border-green-800"
                              : item.status === "downloading"
                              ? "bg-violet-950 text-violet-300 border border-violet-800 animate-pulse"
                              : item.status === "error"
                              ? "bg-red-950 text-red-400 border border-red-800"
                              : "bg-gray-800 text-gray-400 border border-gray-700"
                          }`}
                        >
                          {isCompleted
                            ? "✓ Completed"
                            : item.status === "downloading"
                            ? "Downloading…"
                            : item.status === "error"
                            ? "Failed"
                            : "Queued"}
                        </span>
                      </div>
                    </div>

                    {/* Save File Button */}
                    {isCompleted && (
                      <a
                        href={getFileUrl(item.id)}
                        download
                        className="bg-green-600 hover:bg-green-500 text-white text-xs px-4 py-2 rounded-lg font-semibold transition shrink-0 self-center"
                      >
                        ✓ Save File
                      </a>
                    )}
                  </div>

                  {/* Progress bar */}
                  {item.status === "downloading" && (
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs text-gray-400 font-mono">
                        <span>Downloading…</span>
                        <span>{item.progress.toFixed(0)}%</span>
                      </div>
                      <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-violet-500 transition-all duration-300 rounded-full"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Error display */}
                  {item.status === "error" && item.error && (
                    <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg p-2 font-mono">
                      {item.error}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <p className="mt-8 text-xs text-gray-600">
        Powered by yt-dlp + ffmpeg — for personal use only
      </p>
    </main>
  );
}
