import { Bot, Building2, ListChecks, MessageSquare, Plug, Settings, type LucideIcon } from "lucide-react";

type LabelKey = "chat" | "subagentOffice" | "agentOffice" | "tasks" | "integrations" | "settings";

export interface NavItem {
  href: string;
  labelKey: LabelKey;
  /** Shorter label for the phone tab bar, where space is tight. */
  shortLabelKey?: "subagentOfficeShort" | "agentOfficeShort";
  icon: LucideIcon;
}

// Spec section 19: Chat · Subagent Office · Agent Office · Tasks · Integrations · Settings
export const NAV_ITEMS: NavItem[] = [
  { href: "/chat", labelKey: "chat", icon: MessageSquare },
  {
    href: "/office/subagents",
    labelKey: "subagentOffice",
    shortLabelKey: "subagentOfficeShort",
    icon: Bot,
  },
  {
    href: "/office/agents",
    labelKey: "agentOffice",
    shortLabelKey: "agentOfficeShort",
    icon: Building2,
  },
  { href: "/tasks", labelKey: "tasks", icon: ListChecks },
  { href: "/integrations", labelKey: "integrations", icon: Plug },
  { href: "/settings", labelKey: "settings", icon: Settings },
];
