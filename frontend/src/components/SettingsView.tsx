import React from "react";
import { AppSettings } from "../lib/api";
import { SettingRow } from "./SettingRow";
import { Switch } from "./Switch";

export interface SettingsViewProps {
  settings: AppSettings;
  onUpdate: (patch: Partial<AppSettings>) => void;
  onPickFolder: () => void;
}

export function SettingsView({
  settings,
  onUpdate,
  onPickFolder,
}: SettingsViewProps) {
  return (
    <>
      <h2>Settings</h2>
      <div className="card">
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
      </div>
    </>
  );
}
