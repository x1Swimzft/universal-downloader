import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        sf: "var(--sf)",
        sf2: "var(--sf2)",
        bd: "var(--bd)",
        tx: "var(--tx)",
        mu: "var(--mu)",
        ac: "var(--ac)",
        ac2: "var(--ac2)",
        on: "var(--on)",
        ok: "var(--ok)",
        er: "var(--er)",
        glow: "var(--glow)",
        background: "var(--bg)",
        foreground: "var(--tx)",
      },
    },
  },
  plugins: [],
};
export default config;
