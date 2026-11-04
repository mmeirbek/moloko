import { Building2, CalendarDays, Plug, Settings, type IconComponent } from "@/components/icons";

type LabelKey =
  | "chat"
  | "agentOffice"
  | "tasks"
  | "schedules"
  | "approvals"
  | "search"
  | "integrations"
  | "settings";

export interface NavItem {
  href: string;
  /** `nav.<labelKey>` is the name, `nav.hints.<labelKey>` a one-line "what is this". */
  labelKey: LabelKey;
  /** Shorter label for the phone tab bar, where space is tight. */
  shortLabelKey?: "agentOfficeShort";
  icon: IconComponent;
}

const SCHEDULES: NavItem = { href: "/schedules", labelKey: "schedules", icon: CalendarDays };
const AGENT_OFFICE: NavItem = { href: "/office/agents", labelKey: "agentOffice", shortLabelKey: "agentOfficeShort", icon: Building2 };
const INTEGRATIONS: NavItem = { href: "/integrations", labelKey: "integrations", icon: Plug };
const SETTINGS: NavItem = { href: "/settings", labelKey: "settings", icon: Settings };

/** The phone's bottom bar has the office next to «Работа» and «Новое». */
export const OFFICE = AGENT_OFFICE;

// The owner's work — tasks and chats together, grouped «ждут вас · в работе · недавние» — is
// the sidebar's list (features/work); these are the other places, at its bottom (owner's
// decision 2026-11-03, like Claude's sidebar). Approvals are where they belong: in their task
// and in «Ждут вас»; search is next to «Новое».
export const SECTIONS: NavItem[] = [AGENT_OFFICE, SCHEDULES, INTEGRATIONS, SETTINGS];
