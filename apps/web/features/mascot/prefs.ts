/** Per-device mascot preferences (localStorage; nothing to sync with the server). */
export interface MascotPrefs {
  /** Seasonal outfits (New Year, Halloween, spring). */
  seasonal: boolean;
  /** "Moo!" sound for the easter egg. Off by default. */
  sound: boolean;
}

export const DEFAULT_MASCOT: MascotPrefs = { seasonal: true, sound: false };
const KEY = "moloko.mascot";
const CHANGED = "moloko:mascot-prefs";
let cached: MascotPrefs | null = null;

function load(): MascotPrefs {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? { ...DEFAULT_MASCOT, ...(JSON.parse(raw) as Partial<MascotPrefs>) } : DEFAULT_MASCOT;
  } catch {
    return DEFAULT_MASCOT;
  }
}

export function saveMascotPrefs(prefs: MascotPrefs): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    /* private mode: just not remembered */
  }
  cached = prefs;
  window.dispatchEvent(new Event(CHANGED));
}

export function subscribeMascot(onChange: () => void): () => void {
  const storage = () => {
    cached = null;
    onChange();
  };
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", storage);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", storage);
  };
}

export function mascotSnapshot(): MascotPrefs {
  cached ??= load();
  return cached;
}
