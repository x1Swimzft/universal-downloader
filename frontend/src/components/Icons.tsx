import React from "react";

export type IconName =
  | "dl"
  | "q"
  | "h"
  | "s"
  | "k"
  | "c"
  | "m"
  | "p"
  | "x"
  | "f"
  | "r";

export function SvgSprite() {
  return (
    <svg
      width="0"
      height="0"
      style={{ position: "absolute" }}
      aria-hidden="true"
    >
      <defs>
        <symbol id="dl" viewBox="0 0 24 24">
          <path d="M12 3v12m0 0-4-4m4 4 4-4M4 21h16" />
        </symbol>
        <symbol id="q" viewBox="0 0 24 24">
          <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
        </symbol>
        <symbol id="h" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </symbol>
        <symbol id="s" viewBox="0 0 24 24">
          <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" />
          <circle cx="16" cy="6" r="2" />
          <circle cx="10" cy="12" r="2" />
          <circle cx="18" cy="18" r="2" />
        </symbol>
        <symbol id="k" viewBox="0 0 24 24">
          <circle cx="8" cy="15" r="4" />
          <path d="m11 12 9-9m-3 3 3 3m-6-1 2 2" />
        </symbol>
        <symbol id="c" viewBox="0 0 24 24">
          <rect x="6" y="4" width="12" height="17" rx="2" />
          <path d="M9 4h6v3H9z" />
        </symbol>
        <symbol id="m" viewBox="0 0 24 24">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </symbol>
        <symbol id="p" viewBox="0 0 24 24">
          <path d="M8 5v14l11-7z" />
        </symbol>
        <symbol id="x" viewBox="0 0 24 24">
          <path d="M6 6l12 12M18 6 6 18" />
        </symbol>
        <symbol id="f" viewBox="0 0 24 24">
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </symbol>
        <symbol id="r" viewBox="0 0 24 24">
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <path d="M3 3v5h5" />
        </symbol>
      </defs>
    </svg>
  );
}

export function Icon({
  name,
  className,
  style,
}: {
  name: IconName;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <svg className={className || "i"} style={style} aria-hidden="true">
      <use href={`#${name}`} />
    </svg>
  );
}
