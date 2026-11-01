import {
  Bot,
  Building2,
  ListChecks,
  MessageSquare,
  Plug,
  Search,
  Settings,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

type LabelKey =
  | "chat"
  | "subagentOffice"
  | "agentOffice"
  | "tasks"
  | "approvals"
  | "search"
  | "integrations"
  | "settings";

export interface NavItem {
  href: string;
  /** `nav.<labelKey>` is the name, `nav.hints.<labelKey>` a one-line "what is this". */
  labelKey: LabelKey;
  /** Shorter label for the phone tab bar, where space is tight. */
  shortLabelKey?: "subagentOfficeShort" | "agentOfficeShort";
  icon: LucideIcon;
}

const CHAT: NavItem = { href: "/chat", labelKey: "chat", icon: MessageSquare };
const TASKS: NavItem = { href: "/tasks", labelKey: "tasks", icon: ListChecks };
const APPROVALS: NavItem = { href: "/approvals", labelKey: "approvals", icon: ShieldCheck };
const SEARCH: NavItem = { href: "/search", labelKey: "search", icon: Search };
const AGENT_OFFICE: NavItem = { href: "/office/agents", labelKey: "agentOffice", shortLabelKey: "agentOfficeShort", icon: Building2 };
const SUBAGENT_OFFICE: NavItem = {
  href: "/office/subagents",
  labelKey: "subagentOffice",
  shortLabelKey: "subagentOfficeShort",
  icon: Bot,
};
const INTEGRATIONS: NavItem = { href: "/integrations", labelKey: "integrations", icon: Plug };
const SETTINGS: NavItem = { href: "/settings", labelKey: "settings", icon: Settings };

// Spec section 19 sections (Chat · Subagent Office · Agent Office · Tasks · Integrations · Settings),
// plus Approvals and Search, grouped so the sidebar reads as "do work · watch the office · set up".
export const NAV_GROUPS: { key: "work" | "office" | "system"; items: NavItem[] }[] = [
  { key: "work", items: [CHAT, TASKS, APPROVALS, SEARCH] },
  { key: "office", items: [AGENT_OFFICE, SUBAGENT_OFFICE] },
  { key: "system", items: [INTEGRATIONS, SETTINGS] },
];

/** Phone tab bar: the most used sections (the cow "new task" button sits between them). */
export const PHONE_TABS: [NavItem, NavItem, NavItem] = [CHAT, AGENT_OFFICE, TASKS];
/** Phone "More" sheet: everything else, with its one-line explanation. */
export const PHONE_MORE: NavItem[] = [SUBAGENT_OFFICE, APPROVALS, SEARCH, INTEGRATIONS, SETTINGS];
