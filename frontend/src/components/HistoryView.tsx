import React from "react";
import { HistoryItem } from "../lib/api";
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
      <h2>History</h2>
      <div id="hl">
        {items.length === 0 ? (
          <div className="empty">Finished downloads will show up here.</div>
        ) : (
          items.map((item) => (
            <div key={`${item.id}-${item.completedAt}`} className="card dl">
              <div
                className="t"
                style={{ alignItems: "center", flexWrap: "wrap" }}
              >
                <span>{item.title}</span>
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    flexWrap: "wrap",
                  }}
                >
                  <span className="meta" style={{ margin: 0 }}>
                    {item.label}
                  </span>
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
            </div>
          ))
        )}
      </div>
    </>
  );
}
