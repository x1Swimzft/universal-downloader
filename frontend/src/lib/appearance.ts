export type ThemeMode = "dark" | "light" | "system";
export type AccentColor = "crimson" | "violet" | "cyan" | "emerald" | "amber";
export type Density = "comfortable" | "compact";
export type UiScale = "100" | "115" | "125";

export interface AppearanceSettings {
  theme: ThemeMode;
  accent: AccentColor;
  density: Density;
  reduceEffects: boolean;
  scale: UiScale;
}

export const APPEARANCE_STORAGE_KEY = "ud_appearance_v1";

export const DEFAULT_APPEARANCE: AppearanceSettings = {
  theme: "dark",
  accent: "crimson",
  density: "comfortable",
  reduceEffects: false,
  scale: "115",
};

const THEMES: ThemeMode[] = ["dark", "light", "system"];
const ACCENTS: AccentColor[] = ["crimson", "violet", "cyan", "emerald", "amber"];
const DENSITIES: Density[] = ["comfortable", "compact"];
const SCALES: UiScale[] = ["100", "115", "125"];

export function readAppearance(): AppearanceSettings {
  if (typeof window === "undefined") return DEFAULT_APPEARANCE;
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(APPEARANCE_STORAGE_KEY) || "{}"
    ) as Partial<AppearanceSettings>;
    return {
      theme: THEMES.includes(parsed.theme as ThemeMode)
        ? (parsed.theme as ThemeMode)
        : DEFAULT_APPEARANCE.theme,
      accent: ACCENTS.includes(parsed.accent as AccentColor)
        ? (parsed.accent as AccentColor)
        : DEFAULT_APPEARANCE.accent,
      density: DENSITIES.includes(parsed.density as Density)
        ? (parsed.density as Density)
        : DEFAULT_APPEARANCE.density,
      reduceEffects: parsed.reduceEffects === true,
      scale: SCALES.includes(parsed.scale as UiScale)
        ? (parsed.scale as UiScale)
        : DEFAULT_APPEARANCE.scale,
    };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function resolveTheme(theme: ThemeMode): "dark" | "light" {
  if (theme !== "system") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function applyAppearance(appearance: AppearanceSettings) {
  const root = document.documentElement;
  const theme = resolveTheme(appearance.theme);
  root.dataset.theme = theme;
  root.dataset.accent = appearance.accent;
  root.dataset.density = appearance.density;
  root.dataset.reduceEffects = String(appearance.reduceEffects);
  root.dataset.scale = appearance.scale;
  root.style.colorScheme = theme;
}
