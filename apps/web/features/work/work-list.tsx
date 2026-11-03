"use client";

import type { ConversationOut, TaskOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useNow, useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, type ReactNode } from "react";

import { AlertTriangle, ArrowRight, Check, Loader2, MessageSquare, ShieldAlert, Trash2, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { useChatTitle } from "@/features/chat/chat-title";
import { listTasks, taskKeys } from "@/lib/api/agents";
import { chatKeys, deleteChat, listChats } from "@/lib/api/chat";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn, notAfter } from "@/lib/utils";

import { groupWork, type WaitReason, type WorkItem } from "./work-list-model";

/** How many tasks and chats wait for the owner (the phone's «Работа» button shows it). */
export function useWaitingCount(): number {
  return useWork().waiting.length;
}

function useWork() {
  const tasks = useQuery({ queryKey: taskKeys.list("all", ""), queryFn: ({ signal }) => listTasks("all", "", signal) });
  const chats = useQuery({ queryKey: chatKeys.list, queryFn: ({ signal }) => listChats(signal) });
  const live = useRealtimeStore((s) => s.tasks);
  const approvals = useRealtimeStore((s) => s.approvals);
  const now = useNow({ updateInterval: 60_000 });
  const groups = useMemo(() => {
    const listed = tasks.data?.items ?? [];
    const known = new Set(listed.map((t) => t.id));
    // Live statuses; and parts the store knows, so their approvals count for their task.
    const merged = [...listed.map((t) => live[t.id] ?? t), ...Object.values(live).filter((t) => t.parent_task_id && !known.has(t.id))];
    return groupWork(merged, chats.data?.items ?? [], Object.values(approvals), now.getTime());
  }, [tasks.data, chats.data, live, approvals, now]);
  return { ...groups, tasks, chats };
}

/**
 * The owner's work, like Claude's sidebar: «Ждут вас» (an approval, a question in the answer,
 * or it broke), «В работе», then «Недавние» — chats and finished tasks together, newest first.
 */
export function WorkList({ onNavigate, className }: { onNavigate?: () => void; className?: string }) {
  const t = useTranslations("work");
  const tc = useTranslations("common");
  const toMessage = useErrorMessage();
  const { waiting, active, recent, tasks, chats } = useWork();
  const loading = tasks.isPending || chats.isPending;
  const failed = (tasks.isError && !tasks.data) || (chats.isError && !chats.data);

  return (
    <div className={cn("flex flex-col gap-4", className)} data-testid="work-list">
      {failed && (
        <div role="alert" className="flex flex-col items-start gap-2 px-3 text-sm">
          <p>{toMessage(tasks.error ?? chats.error).message}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void tasks.refetch();
              void chats.refetch();
            }}
          >
            {tc("retry")}
          </Button>
        </div>
      )}
      {waiting.length > 0 && (
        <Group title={t("waiting")} count={waiting.length} testId="work-waiting" accent>
          {waiting.map((item) => (
            <Row key={key(item)} item={item} onNavigate={onNavigate} />
          ))}
        </Group>
      )}
      {active.length > 0 && (
        <Group title={t("active")} count={active.length} testId="work-active">
          {active.map((item) => (
            <Row key={key(item)} item={item} onNavigate={onNavigate} />
          ))}
        </Group>
      )}
      <Group title={t("recent")} testId="work-recent">
        {loading && <p className="px-3 py-1.5 text-sm text-muted-foreground">{tc("loading")}</p>}
        {!loading && !failed && recent.length === 0 && waiting.length === 0 && active.length === 0 && (
          <p className="px-3 py-1.5 text-sm text-muted-foreground">{t("empty")}</p>
        )}
        {recent.map((item) => (
          <Row key={key(item)} item={item} onNavigate={onNavigate} />
        ))}
        <Link
          href="/tasks"
          onClick={onNavigate}
          className="mt-1 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          {t("allTasks")} <ArrowRight className="size-3" aria-hidden />
        </Link>
      </Group>
    </div>
  );
}

const key = (item: WorkItem) => (item.kind === "task" ? `t:${item.task.id}` : `c:${item.chat.id}`);

function Group({
  title,
  count,
  accent,
  testId,
  children,
}: {
  title: string;
  count?: number;
  accent?: boolean;
  testId: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col" data-testid={testId} aria-label={title}>
      <h2
        className={cn(
          "flex items-center gap-2 px-3 pb-1 text-xs font-medium tracking-wide uppercase",
          accent ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground",
        )}
      >
        {title}
        {count !== undefined && <span className="tabular-nums">{count}</span>}
      </h2>
      <ul className="flex flex-col gap-0.5">{children}</ul>
    </section>
  );
}

function Row({ item, onNavigate }: { item: WorkItem; onNavigate?: () => void }) {
  return item.kind === "task" ? (
    <TaskRow task={item.task} reason={item.reason} onNavigate={onNavigate} />
  ) : (
    <ChatRow chat={item.chat} onNavigate={onNavigate} />
  );
}

function TaskIcon({ status, reason }: { status: string; reason?: WaitReason }) {
  if (reason === "approval") return <ShieldAlert className="size-4 shrink-0 text-amber-600 dark:text-amber-300" aria-hidden />;
  if (reason === "question") return <MessageSquare className="size-4 shrink-0 text-amber-600 dark:text-amber-300" aria-hidden />;
  if (status === "failed") return <AlertTriangle className="size-4 shrink-0 text-destructive" aria-hidden />;
  if (status === "cancelled") return <X className="size-4 shrink-0 text-muted-foreground" aria-hidden />;
  if (status === "completed") return <Check className="size-4 shrink-0 text-grass" aria-hidden />;
  return <Loader2 className={cn("size-4 shrink-0 text-sky", status === "running" && "animate-spin")} aria-hidden />;
}

function TaskRow({ task, reason, onNavigate }: { task: TaskOut; reason?: WaitReason; onNavigate?: () => void }) {
  const t = useTranslations("work");
  const tStatus = useTranslations("status");
  const pathname = usePathname();
  const agent = useRealtimeStore((s) => (task.agent_id ? s.agents[task.agent_id] : undefined));
  const href = `/tasks/${task.id}`;
  const current = pathname === href;
  const statusKey = task.status as Parameters<typeof tStatus>[0];
  const state = reason ? t(`reason.${reason}`) : tStatus.has(statusKey) ? tStatus(statusKey) : task.status;
  const meta = agent ? `${agent.name} · ${state}` : state;
  return (
    <li>
      <Link
        href={href}
        onClick={onNavigate}
        aria-current={current ? "page" : undefined}
        title={`${task.title} — ${meta}`}
        data-testid="work-task"
        className={cn(
          "flex items-start gap-2 px-3 py-1.5",
          current ? "bg-primary text-primary-foreground" : "hover:bg-accent",
        )}
      >
        <span className="mt-0.5">
          <TaskIcon status={task.status} reason={reason} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm">{task.title}</span>
          <span className={cn("truncate text-xs", current ? "text-primary-foreground/80" : "text-muted-foreground")}>{meta}</span>
        </span>
      </Link>
    </li>
  );
}

function ChatRow({ chat, onNavigate }: { chat: ConversationOut; onNavigate?: () => void }) {
  const t = useTranslations("chat");
  const tc = useTranslations("common");
  const confirm = useConfirm();
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const chatTitle = useChatTitle();
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: deleteChat,
    onSuccess: (_, id) => {
      void queryClient.invalidateQueries({ queryKey: chatKeys.list });
      if (pathname === `/chat/${id}`) router.push("/chat/new");
    },
  });
  const href = `/chat/${chat.id}`;
  const current = pathname === href;
  const title = chatTitle(chat.title);
  const when = format.relativeTime(notAfter(new Date(chat.last_message_at), now), now);
  return (
    <li className={cn("group flex items-center", current ? "bg-primary text-primary-foreground" : "hover:bg-accent")}>
      <Link
        href={href}
        onClick={onNavigate}
        aria-current={current ? "page" : undefined}
        title={`${title} · ${when}`}
        data-testid="work-chat"
        className="flex min-w-0 flex-1 items-center gap-2 px-3 py-1.5"
      >
        <MessageSquare className={cn("size-4 shrink-0", current ? "" : "text-muted-foreground")} aria-hidden />
        <span className="truncate text-sm">{title}</span>
      </Link>
      <button
        type="button"
        aria-label={t("deleteChat", { title })}
        // Hidden until hover only where there is hover: touch screens always see it.
        className="flex size-8 shrink-0 items-center justify-center text-muted-foreground hover:text-destructive focus:opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100"
        disabled={remove.isPending}
        onClick={async () => {
          if (await confirm({ title: t("confirmDelete"), confirmLabel: tc("delete"), destructive: true })) remove.mutate(chat.id);
        }}
      >
        <Trash2 className="size-4" />
      </button>
    </li>
  );
}
