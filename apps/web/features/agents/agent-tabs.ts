export const TABS = ["profile", "memory", "tasks", "messages"] as const;
export type Tab = (typeof TABS)[number];

/** `?tab=messages` opens a tab directly (links from Search). Pure: tested. */
export function asTab(value: string | undefined): Tab {
  return (TABS as readonly string[]).includes(value ?? "") ? (value as Tab) : "profile";
}
