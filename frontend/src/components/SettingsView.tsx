import React, { useEffect, useState } from "react";
import {
  AppSettings,
  AUDIO_FILENAME_TEMPLATES,
  AudioFilenameTemplate,
  checkForAppUpdate,
  CookieBrowser,
  ExtractorStatus,
  getExtractorStatus,
  UpdateCheckResult,
  updateExtractor,
} from "../lib/api";
import { SettingRow } from "./SettingRow";
import { Switch } from "./Switch";
import {
  AccentColor,
  AppearanceSettings,
  Density,
  ThemeMode,
  UiScale,
} from "../lib/appearance";

export interface SettingsViewProps {
  settings: AppSettings;
  appearance: AppearanceSettings;
  onUpdate: (patch: Partial<AppSettings>) => void;
  onUpdateAppearance: (patch: Partial<AppearanceSettings>) => void;
  onPickFolder: () => void;
  onPickCookiesFile: () => void;
}

interface SegmentOption {
  value: string;
  label: string;
}

const THEME_OPTIONS: SegmentOption[] = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "system", label: "System" },
];

const ACCENT_OPTIONS: Array<{ value: AccentColor; label: string }> = [
  { value: "crimson", label: "Crimson" },
  { value: "violet", label: "Violet" },
  { value: "cyan", label: "Cyan" },
  { value: "emerald", label: "Emerald" },
  { value: "amber", label: "Amber" },
];

const SCALE_OPTIONS: SegmentOption[] = [
  { value: "100", label: "100%" },
  { value: "115", label: "115%" },
  { value: "125", label: "125%" },
];

const CONCURRENCY_OPTIONS: SegmentOption[] = [1, 2, 3, 4, 5].map((value) => ({
  value: String(value),
  label: String(value),
}));

const AUDIO_TEMPLATE_OPTIONS: SegmentOption[] = AUDIO_FILENAME_TEMPLATES.map(
  (template) => ({ value: template, label: template })
);

function Segmented({
  label,
  options,
  value,
  onChange,
  wide,
}: {
  label: string;
  options: SegmentOption[];
  value: string;
  onChange: (value: string) => void;
  wide?: boolean;
}) {
  const index = Math.max(
    0,
    options.findIndex((option) => option.value === value)
  );
  const style = {
    "--seg-count": options.length,
    "--seg-index": index,
    maxWidth: wide ? 270 : 200,
  } as React.CSSProperties;

  return (
    <div
      className="segmented appearance"
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

export function SettingsView({
  settings,
  appearance,
  onUpdate,
  onUpdateAppearance,
  onPickFolder,
  onPickCookiesFile,
}: SettingsViewProps) {
  const [extractor, setExtractor] = useState<ExtractorStatus | null>(null);
  const [updating, setUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState("");
  const [appUpdate, setAppUpdate] = useState<UpdateCheckResult | null>(null);
  const [checkingAppUpdate, setCheckingAppUpdate] = useState(false);

  useEffect(() => {
    let active = true;
    getExtractorStatus()
      .then((status) => {
        if (active) setExtractor(status);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const handleUpdateExtractor = async () => {
    setUpdating(true);
    setUpdateMessage("");
    try {
      const status = await updateExtractor();
      setExtractor(status);
      setUpdateMessage(
        status.message ||
          (status.updated
            ? "Updated. Restart the app to apply it."
            : "yt-dlp is already up to date.")
      );
    } catch (error: unknown) {
      setUpdateMessage(
        error instanceof Error ? error.message : "Extractor update failed"
      );
    } finally {
      setUpdating(false);
    }
  };

  const handleCheckForAppUpdate = async () => {
    setCheckingAppUpdate(true);
    try {
      setAppUpdate(await checkForAppUpdate());
    } catch {
      setAppUpdate({
        status: "error",
        message: "Could not check for updates. Try again later.",
      });
    } finally {
      setCheckingAppUpdate(false);
    }
  };

  const extractorSubtitle = extractor
    ? `yt-dlp ${extractor.active_version}${
        extractor.source === "user" ? " (installed)" : ""
      }${
        extractor.restart_required && extractor.user_version
          ? ` · ${extractor.user_version} ready after restart`
          : ""
      }`
    : "Checking installed version…";

  return (
    <>
      <div className="page-head">
        <div className="cap">Preferences</div>
        <h2>Settings</h2>
      </div>
      <div className="group appearance-group" aria-label="Appearance">
        <SettingRow
          title="Theme"
          subtitle="Dark, light, or follow Windows"
        >
          <Segmented
            label="Theme"
            options={THEME_OPTIONS}
            value={appearance.theme}
            onChange={(theme) =>
              onUpdateAppearance({ theme: theme as ThemeMode })
            }
            wide
          />
        </SettingRow>

        <SettingRow
          title="Accent color"
          subtitle="Buttons, navigation, focus rings, and progress"
        >
          <div className="swatches" role="group" aria-label="Accent color">
            {ACCENT_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className="swatch"
                data-accent={option.value}
                aria-label={`${option.label} accent`}
                aria-pressed={appearance.accent === option.value}
                title={option.label}
                onClick={() => onUpdateAppearance({ accent: option.value })}
              >
                <span className="swatch-dot" aria-hidden="true" />
              </button>
            ))}
          </div>
        </SettingRow>

        <SettingRow
          title="UI scale"
          subtitle="115% recommended for 1080p+"
        >
          <Segmented
            label="UI scale"
            options={SCALE_OPTIONS}
            value={appearance.scale}
            onChange={(scale) =>
              onUpdateAppearance({ scale: scale as UiScale })
            }
          />
        </SettingRow>

        <SettingRow
          title="Compact history & queue rows"
          subtitle="Fit more finished and active downloads on screen"
        >
          <Switch
            checked={appearance.density === "compact"}
            onChange={(compact) =>
              onUpdateAppearance({
                density: (compact ? "compact" : "comfortable") as Density,
              })
            }
            ariaLabel="Compact history and queue rows"
          />
        </SettingRow>

        <SettingRow
          title="Reduce glass blur & motion"
          subtitle="Lower GPU use while streaming or gaming"
        >
          <Switch
            checked={appearance.reduceEffects}
            onChange={(reduceEffects) =>
              onUpdateAppearance({ reduceEffects })
            }
            ariaLabel="Reduce glass blur and motion"
          />
        </SettingRow>
      </div>
      <div className="group" aria-label="App updates">
        <SettingRow
          title="App updates"
          subtitle="Universal Downloader v0.6.0"
        >
          <button
            type="button"
            className="btn sm"
            onClick={handleCheckForAppUpdate}
            disabled={checkingAppUpdate}
          >
            {checkingAppUpdate ? "Checking…" : "Check for updates"}
          </button>
        </SettingRow>
        <div className="settings-note" aria-live="polite">
          {appUpdate?.message || ""}
        </div>
      </div>
      <div className="group">
        <SettingRow
          title="Auto-detect copied links"
          subtitle="Watch the clipboard and offer to fetch"
        >
          <Switch
            checked={settings.autoDetectClipboard}
            onChange={(val) => onUpdate({ autoDetectClipboard: val })}
            ariaLabel="Auto-detect copied links"
          />
        </SettingRow>

        <SettingRow
          title="Minimize to tray on close"
          subtitle="Keep downloads running in the background"
        >
          <Switch
            checked={settings.minimizeToTray}
            onChange={(val) => onUpdate({ minimizeToTray: val })}
            ariaLabel="Minimize to tray"
          />
        </SettingRow>

        <SettingRow
          title="Notify when finished"
          subtitle="Windows notification for each completed file"
        >
          <Switch
            checked={settings.notifyWhenFinished}
            onChange={(val) => onUpdate({ notifyWhenFinished: val })}
            ariaLabel="Notify when finished"
          />
        </SettingRow>

        <SettingRow
          title="Browser cookies"
          subtitle="Use a signed-in browser for private or age-gated posts"
        >
          <select
            aria-label="Browser cookies"
            value={settings.cookiesFromBrowser}
            onChange={(event) =>
              onUpdate({
                cookiesFromBrowser: event.target.value as CookieBrowser,
              })
            }
          >
            <option value="none">Off</option>
            <option value="chrome">Chrome</option>
            <option value="edge">Edge</option>
            <option value="brave">Brave</option>
            <option value="firefox">Firefox</option>
          </select>
        </SettingRow>

        <SettingRow
          title="Cookies file"
          subtitle={settings.cookiesFile || "Optional Netscape cookies.txt"}
        >
          <span className="row-actions">
            {settings.cookiesFile && (
              <button
                type="button"
                className="btn sm"
                onClick={() => onUpdate({ cookiesFile: "" })}
              >
                Clear
              </button>
            )}
            <button type="button" className="btn sm" onClick={onPickCookiesFile}>
              Choose
            </button>
          </span>
        </SettingRow>

        <SettingRow
          title="Social media bypass"
          subtitle="H.264 CFR 30 fps and clean metadata for TikTok / Reels"
        >
          <Switch
            checked={settings.socialBypass}
            onChange={(val) => onUpdate({ socialBypass: val })}
            ariaLabel="Social media bypass"
          />
        </SettingRow>

        <SettingRow
          title="Global quick-fetch hotkey"
          subtitle="Ctrl+Shift+D downloads the copied link in the background"
        >
          <Switch
            checked={settings.quickFetchHotkeyEnabled}
            onChange={(val) => onUpdate({ quickFetchHotkeyEnabled: val })}
            ariaLabel="Global quick-fetch hotkey"
          />
        </SettingRow>

        <SettingRow title="Max concurrent downloads">
          <Segmented
            label="Max concurrent downloads"
            options={CONCURRENCY_OPTIONS}
            value={String(settings.maxConcurrent)}
            onChange={(value) =>
              onUpdate({
                maxConcurrent: Number(value) as 1 | 2 | 3 | 4 | 5,
              })
            }
          />
        </SettingRow>

        <SettingRow
          title="Audio filename template"
          subtitle={settings.audioFilenameTemplate}
        >
          <select
            aria-label="Audio filename template"
            value={settings.audioFilenameTemplate}
            onChange={(event) =>
              onUpdate({
                audioFilenameTemplate:
                  event.target.value as AudioFilenameTemplate,
              })
            }
          >
            {AUDIO_TEMPLATE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </SettingRow>

        <SettingRow title="Save folder" subtitle={settings.saveFolder}>
          <button type="button" className="btn sm" onClick={onPickFolder}>
            Change
          </button>
        </SettingRow>

        <SettingRow title="Extractor engine" subtitle={extractorSubtitle}>
          <button
            type="button"
            className="btn sm"
            onClick={handleUpdateExtractor}
            disabled={updating}
          >
            {updating ? "Updating…" : "Update"}
          </button>
        </SettingRow>
      </div>
      {updateMessage && (
        <div className="settings-note" role="status">
          {updateMessage}
        </div>
      )}
    </>
  );
}
