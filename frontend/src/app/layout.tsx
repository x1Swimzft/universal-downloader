import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Universal Downloader",
  description: "One place for every video and audio link - fast, private, and on your own PC.",
  icons: {
    icon: "/icon.svg",
    shortcut: "/icon.png",
  },
};

const appearanceInit = `(() => {
  try {
    const saved = JSON.parse(localStorage.getItem("ud_appearance_v1") || "{}");
    const mode = ["dark", "light", "system"].includes(saved.theme) ? saved.theme : "dark";
    const theme = mode === "system"
      ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      : mode;
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.dataset.accent = ["crimson", "violet", "cyan", "emerald", "amber"].includes(saved.accent) ? saved.accent : "crimson";
    root.dataset.density = saved.density === "compact" ? "compact" : "comfortable";
    root.dataset.reduceEffects = saved.reduceEffects === true ? "true" : "false";
    root.dataset.scale = ["100", "115", "125"].includes(saved.scale) ? saved.scale : "115";
    root.style.colorScheme = theme;
  } catch {}
})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: appearanceInit }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
