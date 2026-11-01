"use client";

import type { EventEnvelope, MessagePage } from "@moloko/shared-types";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { agentKeys, systemStateKey, taskKeys } from "@/lib/api/agents";
import { chatKeys } from "@/lib/api/chat";

import { RealtimeClient } from "./socket";
import { useRealtimeStore } from "./store";

const ClientContext = createContext<RealtimeClient | null>(null);

export function useRealtimeClient() {
  return useContext(ClientContext);
}

/** Keeps the WebSocket open while the app is shown and turns events into cache updates. */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [client] = useState(
    () =>
      new RealtimeClient({
        onUnauthenticated: () => {
          window.location.assign("/login"); // eslint-disable-line @next/next/no-location-assign-relative-destination
        },
      }),
  );

  useEffect(() => {
    // A busy run sends an event per step and a chat answer one per token: refetch each key at
    // most once per burst, and never abort a refetch that is already on its way.
    const due = new Map<string, QueryKey>();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const refresh = (queryKey: QueryKey) => {
      due.set(JSON.stringify(queryKey), queryKey);
      timer ??= setTimeout(() => {
        timer = null;
        const keys = [...due.values()];
        due.clear();
        for (const key of keys) void queryClient.invalidateQueries({ queryKey: key }, { cancelRefetch: false });
      }, 250);
    };

    const off = client.subscribe((event: EventEnvelope | { type: "snapshot" }) => {
      if (event.type === "snapshot") {
        // Caught up after a gap: refresh everything that may be stale.
        void queryClient.invalidateQueries();
        return;
      }
      const e = event as EventEnvelope;
      if (e.type.startsWith("task.") || e.type.startsWith("agent.task_") || e.type === "agent.message") {
        refresh(taskKeys.all);
        refresh(systemStateKey);
      }
      if (e.type.startsWith("agent.") && e.type !== "agent.message") {
        refresh(agentKeys.all);
      }
      if (e.type === "chat.message_completed") {
        const conversationId = String(e.payload.conversation_id ?? "");
        refresh(chatKeys.messages(conversationId));
        refresh(chatKeys.list);
      }
      if (e.type === "chat.message_delta") {
        // Another device started an answer we don't know yet: load it (we then re-attach).
        const conversationId = String(e.payload.conversation_id ?? "");
        const page = queryClient.getQueryData<MessagePage>(chatKeys.messages(conversationId));
        if (page && !page.items.some((m) => m.id === e.payload.message_id)) {
          refresh(chatKeys.messages(conversationId));
        }
      }
    });
    client.start();
    const wake = () => client.nudge();
    const onVisibility = () => document.visibilityState === "visible" && wake();
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      if (timer) clearTimeout(timer);
      off();
      client.stop();
      useRealtimeStore.getState().reset();
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [client, queryClient]);

  return <ClientContext.Provider value={client}>{children}</ClientContext.Provider>;
}

export function ConnectionDot({ className }: { className?: string }) {
  const status = useRealtimeStore((s) => s.status);
  const color = status === "online" ? "bg-grass" : status === "connecting" ? "bg-amber-400" : "bg-destructive";
  return <span aria-hidden="true" className={`inline-block size-2 rounded-full ${color} ${className ?? ""}`} />;
}
