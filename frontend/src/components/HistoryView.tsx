import React from "react";
import { HistoryItem, startDragFile } from "../lib/api";
import { Icon } from "./Icons";

export interface HistoryViewProps {
  items: HistoryItem[];
  onOpenFolder: (filepath?: string) => void;
  onRedownload: (item: HistoryItem) => void;
}

export function HistoryView({
  items,
  onOpenFolder,
  onRedownload,
}: HistoryViewProps) {
  return (
    <>
      <div className="page-head">
        <div className="cap">Library</div>
        <h2>History</h2>
      </div>
      {items.length === 0 ? (
        <div className="empty">Finished downloads will show up here.</div>
      ) : (
        <div className="group" id="hl">
          {items.map((item) => (
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
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
