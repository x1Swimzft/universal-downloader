import React, { useEffect, useState } from "react";
import {
  AppSettings,
  CookieBrowser,
  ExtractorStatus,
  getExtractorStatus,
  updateExtractor,
} from "../lib/api";
import { SettingRow } from "./SettingRow";
import { Switch } from "./Switch";

export interface SettingsViewProps {
  settings: AppSettings;
  onUpdate: (patch: Partial<AppSettings>) => void;
  onPickFolder: () => void;
  onPickCookiesFile: () => void;
}

export function SettingsView({
  settings,
  onUpdate,
  onPickFolder,
  onPickCookiesFile,
}: SettingsViewProps) {
  const [extractor, setExtractor] = useState<ExtractorStatus | null>(null);
  const [updating, setUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState("");

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

        <SettingRow title="Simultaneous downloads">
          <select
            aria-label="Simultaneous downloads"
            value={settings.maxConcurrent}
            onChange={(e) =>
              onUpdate({
                maxConcurrent: Number(e.target.value) as 1 | 2 | 3 | 5,
              })
            }
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
            <option value={5}>5</option>
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
