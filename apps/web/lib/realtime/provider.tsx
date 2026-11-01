"use client";

import type { EventEnvelope, MessagePage } from "@moloko/shared-types";
import { useQueryClient } from "@tanstack/react-query";
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
    const off = client.subscribe((event: EventEnvelope | { type: "snapshot" }) => {
      if (event.type === "snapshot") {
        // Caught up after a gap: refresh everything that may be stale.
        void queryClient.invalidateQueries();
        return;
      }
      const e = event as EventEnvelope;
      if (e.type.startsWith("task.") || e.type.startsWith("agent.task_") || e.type === "agent.message") {
        void queryClient.invalidateQueries({ queryKey: taskKeys.all });
        void queryClient.invalidateQueries({ queryKey: systemStateKey });
      }
      if (e.type.startsWith("agent.") && e.type !== "agent.message") {
        void queryClient.invalidateQueries({ queryKey: agentKeys.all });
      }
      if (e.type === "chat.message_completed") {
        const conversationId = String(e.payload.conversation_id ?? "");
        void queryClient.invalidateQueries({ queryKey: chatKeys.messages(conversationId) });
        void queryClient.invalidateQueries({ queryKey: chatKeys.list });
      }
      if (e.type === "chat.message_delta") {
        // Another device started an answer we don't know yet: load it (we then re-attach).
        const conversationId = String(e.payload.conversation_id ?? "");
        const page = queryClient.getQueryData<MessagePage>(chatKeys.messages(conversationId));
        if (page && !page.items.some((m) => m.id === e.payload.message_id)) {
          void queryClient.invalidateQueries({ queryKey: chatKeys.messages(conversationId) });
        }
      }
    });
    client.start();
    const wake = () => client.nudge();
    const onVisibility = () => document.visibilityState === "visible" && wake();
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
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
