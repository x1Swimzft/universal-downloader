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

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
