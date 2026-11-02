"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useFormatter, useNow, useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { ArrowLeft, ArrowRight, File as FileIcon } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/features/system/query-state";
import { agentKeys, listAgentMessages, type AgentMessageItem, type MessageDirection } from "@/lib/api/agents";
import { cn, notAfter } from "@/lib/utils";

const DIRECTIONS: MessageDirection[] = ["all", "in", "out"];

/** «Переписка»: what this agent asked, told and answered other agents directly, newest first. */
export function AgentMessages({ agentId }: { agentId: string }) {
  const t = useTranslations("agents.messages");
  const [direction, setDirection] = useState<MessageDirection>("all");
  const messages = useInfiniteQuery({
    queryKey: agentKeys.messages(agentId, direction),
    queryFn: ({ pageParam, signal }) => listAgentMessages(agentId, direction, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = messages.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="flex flex-col gap-4" aria-label={t("title")} data-testid="agent-messages">
      <div role="group" aria-label={t("filter")} className="flex flex-wrap items-center gap-2">
        {DIRECTIONS.map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={direction === d}
            onClick={() => setDirection(d)}
            className={cn(
              "min-h-9 px-3 text-sm",
              direction === d ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            {t(`directions.${d}`)}
          </button>
        ))}
      </div>
      {messages.isPending && <LoadingState />}
      {messages.isError && <ErrorState error={messages.error} onRetry={() => messages.refetch()} />}
      {messages.data && items.length === 0 && (
        <p className="border-2 border-dashed p-6 text-center text-sm text-muted-foreground">{t("empty")}</p>
      )}
      {items.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label={t("title")}>
          {items.map((m) => (
            <MessageRow key={m.id} message={m} />
          ))}
        </ul>
      )}
      {messages.hasNextPage && (
        <Button variant="outline" className="self-start" disabled={messages.isFetchingNextPage} onClick={() => messages.fetchNextPage()}>
          {t("more")}
        </Button>
      )}
    </section>
  );
}

function MessageRow({ message: m }: { message: AgentMessageItem }) {
  const t = useTranslations("agents.messages");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const [open, setOpen] = useState(false);
  const incoming = m.direction === "in";
  const otherId = incoming ? m.sender_agent_id : m.receiver_agent_id;
  const otherName = incoming ? m.sender_name : m.receiver_name;
  const refused = m.status === "refused";
  const text = m.text ?? m.summary;
  const long = text.length > m.summary.length || text.includes("\n");
  const taskId = m.consult_task_id ?? m.task_id;

  return (
    <li
      className={cn(
        "flex flex-col gap-2 bg-card p-3 text-sm pixel-frame",
        refused && "[--frame-color:var(--color-destructive)]",
        incoming && m.message_type === "note" && !m.read_at && "[--frame-color:var(--color-sky)]",
      )}
      data-message-type={m.message_type}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {incoming ? (
          <ArrowLeft className="size-3 shrink-0 text-muted-foreground" aria-hidden />
        ) : (
          <ArrowRight className="size-3 shrink-0 text-muted-foreground" aria-hidden />
        )}
        <span className="text-muted-foreground">{incoming ? t("from") : t("to")}</span>
        <Link href={`/office/agents/${otherId}`} className="truncate underline-offset-2 hover:underline">
          {otherName}
        </Link>
        <span className={cn("px-1.5 text-xs", typeClass(m.message_type))}>{t(`types.${m.message_type}`)}</span>
        {refused && <span className="text-xs text-destructive">{t("refused", { reason: refusalText(t, m.error) })}</span>}
        <span className="ml-auto text-xs text-muted-foreground" title={format.dateTime(new Date(m.created_at), { dateStyle: "medium", timeStyle: "short" })}>
          {format.relativeTime(notAfter(new Date(m.created_at), now), now)}
        </span>
      </div>
      {!refused && (
        <p className={cn("break-words whitespace-pre-wrap", !open && "line-clamp-3")}>{open ? text : m.summary || text}</p>
      )}
      {(m.files.length > 0 || taskId || (long && !refused)) && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          {m.files.map((f) => (
            <span key={f} className="inline-flex items-center gap-1">
              <FileIcon className="size-3" aria-hidden /> {f}
            </span>
          ))}
          {taskId && (
            <Link href={`/tasks/${taskId}`} className="text-sky underline-offset-2 hover:underline">
              {m.message_type === "note" ? t("openSenderTask") : t("openConsult")}
            </Link>
          )}
          {m.asker_task_id && m.asker_task_id !== taskId && (
            <Link href={`/tasks/${m.asker_task_id}`} className="text-sky underline-offset-2 hover:underline">
              {t("openAskerTask")}
            </Link>
          )}
          {long && !refused && (
            <button type="button" className="underline-offset-2 hover:underline" onClick={() => setOpen((v) => !v)}>
              {open ? t("collapse") : t("expand")}
            </button>
          )}
        </div>
      )}
    </li>
  );
}

function typeClass(type: AgentMessageItem["message_type"]): string {
  switch (type) {
    case "request":
      return "bg-sky/15 text-sky";
    case "task_result":
      return "bg-grass/15 text-grass";
    case "error":
      return "bg-destructive/15 text-destructive";
    default:
      return "bg-muted text-muted-foreground";
  }
}

const REFUSALS = [
  "self",
  "different_owner",
  "agent_unavailable",
  "orchestrator",
  "different_run",
  "not_a_colleague",
  "not_in_contacts",
  "receiver_refuses",
  "cycle",
  "too_many_hops",
  "too_many_asks",
  "deadlock",
] as const;

function refusalText(t: ReturnType<typeof useTranslations<"agents.messages">>, code: string | null): string {
  return code && (REFUSALS as readonly string[]).includes(code) ? t(`refusals.${code as (typeof REFUSALS)[number]}`) : t("refusals.other");
}
