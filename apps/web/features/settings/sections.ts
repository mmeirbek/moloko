import { Bell, Bot, Brain, CalendarDays, FileText, Monitor, Settings2, type IconComponent } from "@/components/icons";

/*
 * Settings, like the iPhone's: a short list of sections, each on its own page (owner: the long
 * page with a jump bar on top was pointless and awkward to scroll). In the order a new owner
 * needs them — without an AI provider nothing works.
 */
export const SECTIONS = ["ai", "notifications", "agents", "appearance", "system"] as const;
export type SectionId = (typeof SECTIONS)[number];

export const SECTION_ICONS: Record<SectionId, IconComponent> = {
  ai: Brain,
  notifications: Bell,
  agents: Bot,
  appearance: Monitor,
  system: Settings2,
};

/** The other pages listed with the sections. */
export const EXTRA_PAGES = [
  { href: "/settings/costs", key: "costsLink", icon: CalendarDays },
  { href: "/settings/audit", key: "auditLink", icon: FileText },
] as const;

/** Old addresses (`/settings#ai`, `#memory`) → the section that has it now. */
export function sectionForHash(hash: string): SectionId | null {
  const id = hash.replace(/^#/, "");
  if (id === "memory") return "agents";
  return (SECTIONS as readonly string[]).includes(id) ? (id as SectionId) : null;
}

export function isSection(value: string): value is SectionId {
  return (SECTIONS as readonly string[]).includes(value);
}
