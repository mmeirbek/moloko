"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocale } from "next-intl";
import type { DragEvent } from "react";

import { agentKeys, createAgentFromTemplate, restoreAgent } from "@/lib/api/agents";

/** What can be dropped into the office: a template (a new agent) or an agent removed earlier. */
export type OfficeDrop = { kind: "template"; key: string } | { kind: "archived"; id: string };

/** The drag-and-drop data type; anything else dragged over the map is ignored. */
export const DROP_TYPE = "application/x-moloko-agent";

export function startDrag(e: DragEvent, item: OfficeDrop) {
  e.dataTransfer.setData(DROP_TYPE, JSON.stringify(item));
  e.dataTransfer.effectAllowed = "copy";
}

export function canDrop(e: DragEvent): boolean {
  return e.dataTransfer.types.includes(DROP_TYPE);
}

export function readDrop(e: DragEvent): OfficeDrop | null {
  try {
    const item = JSON.parse(e.dataTransfer.getData(DROP_TYPE)) as OfficeDrop;
    if (item.kind === "template" && typeof item.key === "string") return item;
    if (item.kind === "archived" && typeof item.id === "string") return item;
  } catch {
    // not ours
  }
  return null;
}

/**
 * Puts an agent into the office — a new one from a template, or one removed earlier. The server
 * decides; the office shows the agent when the event arrives (it walks in and rests in the lounge).
 */
export function useAddToOffice(onAdded?: (agentId: string) => void) {
  const locale = useLocale();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (item: OfficeDrop) =>
      item.kind === "template" ? createAgentFromTemplate({ template: item.key, locale }) : restoreAgent(item.id),
    onSuccess: (agent) => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all });
      onAdded?.(agent.id);
    },
  });
}
