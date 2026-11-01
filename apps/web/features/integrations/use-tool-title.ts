"use client";

import type { ToolOut } from "@moloko/shared-types";
import { useTranslations } from "next-intl";

/** Built-in tools get a localized name; MCP tools keep the server's name. */
export function useToolTitle(): (tool: Pick<ToolOut, "name" | "title" | "source">) => string {
  const t = useTranslations("tools.names");
  return (tool) => (tool.source === "builtin" && t.has(tool.name as "fs_read") ? t(tool.name as "fs_read") : tool.title);
}
