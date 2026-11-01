"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { UNTITLED_CHAT } from "@/features/chat/chat-title";
import { MilkBottle } from "@/features/mascot/milk-bottle";
import { agentKeys, listAgents, listTasks, taskKeys } from "@/lib/api/agents";
import { chatKeys, createChat, listChats, listPickerModels, modelKeys } from "@/lib/api/chat";
import { cn } from "@/lib/utils";

const HIDDEN_KEY = "moloko.gettingStarted.hidden"; // per device: the owner closed the checklist

function readHidden(): boolean {
  try {
    return localStorage.getItem(HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}
const subscribeStorage = (onChange: () => void) => {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
};

type StepKey = "model" | "chat" | "task" | "agent";

/**
 * "Where do I start?" — four first steps, each ticked from real server data (not from clicks),
 * with the action that does it. Disappears when all are done or when the owner hides it.
 */
export function GettingStarted({ className }: { className?: string }) {
  const t = useTranslations("start");
  const router = useRouter();
  const queryClient = useQueryClient();
  const storedHidden = useSyncExternalStore(subscribeStorage, readHidden, () => true);
  const [hiddenNow, setHiddenNow] = useState(false);

  const models = useQuery({ queryKey: modelKeys.picker, queryFn: ({ signal }) => listPickerModels(signal) });
  const chats = useQuery({ queryKey: chatKeys.list, queryFn: ({ signal }) => listChats(signal) });
  const tasks = useQuery({ queryKey: taskKeys.list("all", ""), queryFn: ({ signal }) => listTasks("all", "", signal) });
  const agents = useQuery({ queryKey: agentKeys.all, queryFn: ({ signal }) => listAgents(signal) });
  const newChat = useMutation({
    mutationFn: () => createChat(),
    onSuccess: (chat) => {
      void queryClient.invalidateQueries({ queryKey: chatKeys.list });
      router.push(`/chat/${chat.id}`);
    },
  });

  if (storedHidden || hiddenNow) return null;
  if (!models.data || !chats.data || !tasks.data || !agents.data) return null; // no flicker while loading

  const done: Record<StepKey, boolean> = {
    model: models.data.length > 0,
    chat: chats.data.items.some((c) => c.title !== UNTITLED_CHAT), // a chat gets its title from the first message
    task: tasks.data.items.length > 0,
    agent: agents.data.some((a) => a.agent_type === "autonomous"),
  };
  const steps: StepKey[] = ["model", "chat", "task", "agent"];
  const count = steps.filter((s) => done[s]).length;
  if (count === steps.length) return null;
  const next = steps.find((s) => !done[s]);

  function hide() {
    try {
      localStorage.setItem(HIDDEN_KEY, "1");
    } catch {
      // private mode: hidden for this visit only
    }
    setHiddenNow(true);
  }

  const action = (step: StepKey) => {
    const primary = step === next;
    const variant = primary ? "default" : "outline";
    if (step === "chat") {
      return (
        <Button size="sm" variant={variant} disabled={!done.model || newChat.isPending} onClick={() => newChat.mutate()}>
          {t("chat.action")}
        </Button>
      );
    }
    const href = { model: "/settings#ai", task: "/office/subagents", agent: "/office/agents" }[step];
    return (
      <Button size="sm" variant={variant} asChild>
        <Link href={href}>{t(`${step}.action`)}</Link>
      </Button>
    );
  };

  return (
    <section
      aria-labelledby="start-title"
      className={cn("flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-sm", className)}
      data-testid="getting-started"
    >
      <div className="flex items-start gap-3">
        <MilkBottle percent={(count / steps.length) * 100} size={26} />
        <div className="min-w-0 flex-1">
          <h2 id="start-title" className="font-pixel text-lg leading-tight">
            {t("title")}
          </h2>
          <p className="text-xs text-muted-foreground">{t("progress", { done: count, total: steps.length })}</p>
        </div>
        <Button variant="ghost" size="icon" onClick={hide} aria-label={t("hide")} title={t("hide")} className="-m-2">
          <X />
        </Button>
      </div>
      <ol className="flex flex-col gap-2">
        {steps.map((step, index) => (
          <li
            key={step}
            className={cn(
              "flex items-center gap-3 rounded-lg px-2 py-2",
              step === next && "bg-accent/60",
              done[step] && "opacity-70",
            )}
          >
            <span
              className={cn(
                "flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                done[step] && "border-grass bg-grass text-white",
              )}
              aria-hidden
            >
              {done[step] ? <Check className="size-4" /> : index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className={cn("text-sm font-medium", done[step] && "line-through decoration-muted-foreground/60")}>
                {t(`${step}.title`)}
                <span className="sr-only"> — {done[step] ? t("stepDone") : t("stepTodo")}</span>
              </p>
              {!done[step] && <p className="text-xs text-muted-foreground">{t(`${step}.hint`)}</p>}
            </div>
            {!done[step] && action(step)}
          </li>
        ))}
      </ol>
    </section>
  );
}
