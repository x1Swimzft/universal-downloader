import React from "react";
import { Icon } from "./Icons";

export type SidebarView = "dl" | "q" | "h" | "s";

export interface SidebarProps {
  activeView: SidebarView;
  onSelectView: (v: SidebarView) => void;
  activeQueueCount: number;
  onToggleTheme: () => void;
  versionText?: string;
}

export function Sidebar({
  activeView,
  onSelectView,
  activeQueueCount,
  onToggleTheme,
  versionText = "v0.5.0 · Pro",
}: SidebarProps) {
  return (
    <aside className="side">
      <div className="brand">
        <span className="brand-tile">
          <Icon name="dl" />
        </span>
        <div className="brand-name">
          Universal<em>Downloader</em>
        </div>
      </div>

      <button
        type="button"
        className="nav"
        data-v="dl"
        aria-current={activeView === "dl" ? "page" : undefined}
        onClick={() => onSelectView("dl")}
      >
        <Icon name="dl" />
        Download
      </button>

      <button
        type="button"
        className="nav"
        data-v="q"
        aria-current={activeView === "q" ? "page" : undefined}
        onClick={() => onSelectView("q")}
      >
        <Icon name="q" />
        Queue
        {activeQueueCount > 0 && <b id="qb">{activeQueueCount}</b>}
      </button>

      <button
        type="button"
        className="nav"
        data-v="h"
        aria-current={activeView === "h" ? "page" : undefined}
        onClick={() => onSelectView("h")}
      >
        <Icon name="h" />
        History
      </button>

      <button
        type="button"
        className="nav"
        data-v="s"
        aria-current={activeView === "s" ? "page" : undefined}
        onClick={() => onSelectView("s")}
      >
        <Icon name="s" />
        Settings
      </button>

      <div className="sp" />

      <button
        type="button"
        className="nav"
        id="th"
        onClick={onToggleTheme}
        aria-label="Toggle theme"
      >
        <Icon name="m" />
        Theme
      </button>

      <div className="side-foot">
        <span className="status">
          <i className="dot" aria-hidden="true" />
          FFmpeg ready
        </span>
        <div className="ver" id="ver">
          {versionText}
        </div>
      </div>
    </aside>
  );
}
