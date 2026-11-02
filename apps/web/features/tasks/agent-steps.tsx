"use client";

import type { EventOut, ToolCallOut } from "@moloko/shared-types";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";

import { Brain, Check, ChevronDown, ChevronRight, ListChecks, Loader2, MessageSquare, ShieldAlert, X } from "@/components/icons";
import { MarkdownBody } from "@/features/chat/markdown";
import { shortText } from "@/lib/notifications/text";
import { taskToolCalls, toolingKeys } from "@/lib/api/tooling";
import { cn } from "@/lib/utils";

/**
 * What the agent did, step by step — like Claude Code: every step is one short line (what it
 * thought, which tool it used and on what), a click opens everything (the full text, the exact
 * arguments, the whole output). While the task runs, the last line says what it is doing now.
 */

type Item =
  | { kind: "thought"; id: string; step: number; text: string }
  | { kind: "tool"; id: string; step: number; call: ToolCallOut }
  | { kind: "owner"; id: string; text: string }
  | { kind: "plan"; id: string; mode: string; summary: string; parts: { title: string; agent: string }[] };

/** The Orchestrator's planning reply is JSON — shown as its plan instead of raw text. */
const PLAN_JSON = /^\s*(```(json)?\s*)?\{[\s\S]*"mode"\s*:/;

const RUNNING = new Set(["running", "pending"]);
const FAILED = new Set(["failed", "denied", "rejected", "expired", "unknown"]);

/** `tasks.agentSteps.tools.<key>` and its params: what a tool call does, in a few words. */
export function stepLabel(tool: string, args: Record<string, unknown>): { key: string; params: Record<string, string> } {
  const s = (k: string, max = 70) => shortText(String(args[k] ?? ""), max);
  const file = (k: string) => shortText(String(args[k] ?? "").split("/").pop() ?? "", 60) || "?";
  const host = (k: string) => {
    try {
      return new URL(String(args[k] ?? "")).hostname;
    } catch {
      return s(k, 50);
    }
  };
  switch (tool) {
    case "fs_read":
    case "fs_delete":
      return { key: tool, params: { file: file("path") } };
    case "fs_write":
      return { key: args.mode === "append" ? "fs_append" : "fs_write", params: { file: file("path") } };
    case "fs_list":
      return { key: tool, params: { path: s("path", 60) || "." } };
    case "fs_move":
      return { key: tool, params: { file: file("source"), to: s("destination", 60) } };
    case "terminal_run":
      return { key: tool, params: { command: shortText(String(args.command ?? "").split("\n")[0] ?? "", 80) } };
    case "github_read_file":
    case "github_write_file":
      return { key: tool, params: { file: file("path"), repo: s("repo", 50) } };
    case "github_list_dir":
      return { key: tool, params: { path: s("path", 50) || "/", repo: s("repo", 50) } };
    case "github_create_branch":
      return { key: tool, params: { branch: s("branch", 40), repo: s("repo", 50) } };
    case "github_list_issues":
    case "github_list_commits":
    case "github_create_pull_request":
      return { key: tool, params: { repo: s("repo", 50) } };
    case "github_get_issue":
      return { key: tool, params: { number: s("number", 10), repo: s("repo", 50) } };
    case "web_search":
    case "knowledge_search":
    case "work_search":
      return { key: tool, params: { query: s("query") } };
    case "web_fetch":
    case "browser_screenshot":
      return { key: tool, params: { host: host("url") } };
    case "memory_save":
      return { key: tool, params: { title: s("title") } };
    case "agent_ask":
    case "agent_tell":
      return { key: tool, params: { agent: s("agent", 40) } };
    case "github_list_repos":
    case "agents_list":
    case "work_read":
      return { key: tool, params: {} };
    default:
      return { key: "other", params: { tool: tool.replaceAll("_", " ") } };
  }
}

function firstLine(text: string | null | undefined, max = 110): string {
  const line = (text ?? "").split("\n").find((l) => l.trim()) ?? "";
  return shortText(line, max);
}

/** What came out, in one line: for a command its first output line («exit code 0» only when
 *  it printed nothing), otherwise the first line of the result. */
export function outputPreview(tool: string, result: string | null | undefined): string {
  if (tool !== "terminal_run" || !result) return firstLine(result);
  const lines = result.split("\n");
  const status = lines[0] ?? "";
  const out = lines.slice(1).find((l) => l.trim() && !/^--- (stdout|stderr) ---$/.test(l.trim()));
  return out ? firstLine(out) : firstLine(status);
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

function StepRow({
  icon,
  title,
  preview,
  open,
  onToggle,
  tone,
  children,
  testId,
}: {
  icon: React.ReactNode;
  title: string;
  preview?: string;
  open: boolean;
  onToggle: () => void;
  tone?: string;
  children?: React.ReactNode;
  testId?: string;
}) {
  const expandable = Boolean(children);
  return (
    <li className="flex flex-col" data-testid={testId}>
      <button
        type="button"
        onClick={expandable ? onToggle : undefined}
        aria-expanded={expandable ? open : undefined}
        className={cn(
          "flex min-h-9 w-full items-start gap-2 px-2 py-1.5 text-left text-sm",
          expandable && "hover:bg-accent/60",
        )}
      >
        <span className={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center", tone)} aria-hidden>
          {icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block break-words">{title}</span>
          {preview && !open && <span className="block truncate text-xs text-muted-foreground">⎿ {preview}</span>}
        </span>
        {expandable && (
          <span className="mt-0.5 shrink-0 text-muted-foreground" aria-hidden>
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </span>
        )}
      </button>
      {open && children && <div className="ml-8 flex flex-col gap-2 pr-2 pb-2 text-sm">{children}</div>}
    </li>
  );
}

export function AgentSteps({
  taskId,
  status,
  events,
  result,
}: {
  taskId: string;
  status: string;
  events: EventOut[] | undefined;
  /** The final answer is shown below on its own: not repeated as a step. */
  result?: string | null;
}) {
  const t = useTranslations("tasks.agentSteps");
  const tStatus = useTranslations("tools.calls.status");
  const calls = useQuery({
    queryKey: [...toolingKeys.taskCalls(taskId), status],
    queryFn: ({ signal }) => taskToolCalls(taskId, signal),
  });
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [allOpen, setAllOpen] = useState(false);
  const running = status === "running" || status === "queued";

  const items = useMemo<Item[]>(() => {
    const out: Item[] = [];
    const byStep = new Map<number, ToolCallOut[]>();
    for (const c of calls.data ?? []) byStep.set(c.step, [...(byStep.get(c.step) ?? []), c]);
    const placed = new Set<string>();
    for (const e of events ?? []) {
      const p = e.payload as Record<string, unknown>;
      if (e.type === "agent.message" && p.kind === "plan") {
        const parts = Array.isArray(p.subtasks) ? (p.subtasks as { title?: string; agent?: string }[]) : [];
        out.push({
          kind: "plan",
          id: e.id,
          mode: String(p.mode ?? ""),
          summary: String(p.summary ?? ""),
          parts: parts.map((s) => ({ title: String(s.title ?? ""), agent: String(s.agent ?? "") })),
        });
      } else if (e.type === "agent.message" && p.kind === undefined && typeof p.step === "number") {
        const text = String(p.text ?? "").trim();
        const isAnswer = Boolean(result && text === result.trim());
        if (text && !isAnswer && !PLAN_JSON.test(text)) out.push({ kind: "thought", id: e.id, step: p.step, text });
        for (const c of byStep.get(p.step) ?? []) {
          out.push({ kind: "tool", id: c.id, step: c.step, call: c });
          placed.add(c.id);
        }
      } else if (e.type === "task.owner_message") {
        out.push({ kind: "owner", id: e.id, text: String(p.text ?? "") });
      }
    }
    // calls whose step event is not loaded yet (e.g. the history is still on its way)
    for (const c of calls.data ?? []) if (!placed.has(c.id)) out.push({ kind: "tool", id: c.id, step: c.step, call: c });
    return out;
  }, [calls.data, events, result]);

  const busyTool = items.find((i) => i.kind === "tool" && RUNNING.has(i.call.status));
  const now = useNow(running);
  const isOpen = (id: string) => allOpen || Boolean(open[id]);
  const toggle = (id: string) => setOpen((o) => ({ ...o, [id]: !isOpen(id) }));

  if (items.length === 0 && !running) return null;
  return (
    <section aria-labelledby="agent-steps-title" className="bg-card pixel-frame" data-testid="agent-steps">
      <div className="flex items-center justify-between gap-2 border-b-2 px-3 py-2">
        <h2 id="agent-steps-title" className="font-medium">
          {t("title")}
          {items.length > 0 && <span className="ml-2 text-sm font-normal text-muted-foreground">{items.length}</span>}
        </h2>
        {items.length > 0 && (
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={() => {
              setAllOpen((v) => !v);
              setOpen({});
            }}
          >
            {allOpen ? t("collapseAll") : t("expandAll")}
          </button>
        )}
      </div>
      <ol className="flex flex-col py-1">
        {items.map((item) => {
          if (item.kind === "owner")
            return (
              <StepRow
                key={item.id}
                icon={<MessageSquare className="size-3.5" />}
                tone="text-sky"
                title={t("owner", { text: firstLine(item.text, 90) })}
                open={false}
                onToggle={() => undefined}
              />
            );
          if (item.kind === "plan")
            return (
              <StepRow
                key={item.id}
                icon={<ListChecks className="size-3.5" />}
                tone="text-sky"
                title={
                  item.mode === "direct"
                    ? t("planDirect")
                    : t("plan", { count: item.parts.length, summary: shortText(item.summary, 80) })
                }
                open={isOpen(item.id)}
                onToggle={() => toggle(item.id)}
                testId="step-plan"
              >
                {item.parts.length > 0 ? (
                  <ul className="flex flex-col gap-0.5">
                    {item.parts.map((part, i) => (
                      <li key={i}>
                        {part.title}
                        {part.agent && <span className="text-muted-foreground"> → {part.agent}</span>}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </StepRow>
            );
          if (item.kind === "thought")
            return (
              <StepRow
                key={item.id}
                icon={<Brain className="size-3.5" />}
                tone="text-muted-foreground"
                title={firstLine(item.text)}
                open={isOpen(item.id)}
                onToggle={() => toggle(item.id)}
                testId="step-thought"
              >
                {item.text.length > 110 || item.text.includes("\n") ? <MarkdownBody text={item.text} /> : null}
              </StepRow>
            );
          const c = item.call;
          const label = stepLabel(c.tool_name, c.args);
          const live = RUNNING.has(c.status);
          const failed = FAILED.has(c.status) || c.is_error;
          const waiting = c.status === "awaiting_approval" || c.status === "awaiting_agent";
          const seconds = live && c.started_at ? Math.max(0, Math.round((now - Date.parse(c.started_at)) / 1000)) : null;
          const icon = live ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : waiting ? (
            <ShieldAlert className="size-3.5" />
          ) : failed ? (
            <X className="size-3.5" />
          ) : (
            <Check className="size-3.5" />
          );
          const preview = live
            ? t("runningFor", { seconds: seconds ?? 0 })
            : waiting
              ? tStatus(c.status as "awaiting_approval")
              : outputPreview(c.tool_name, c.result) ||
                (c.decision_reason && c.decision !== "allow" ? c.decision_reason : undefined);
          return (
            <StepRow
              key={item.id}
              icon={icon}
              tone={live ? "text-sky" : waiting ? "text-amber-600" : failed ? "text-destructive" : "text-grass"}
              title={t(`tools.${label.key}` as "tools.other", label.params as { tool: string })}
              preview={preview}
              open={isOpen(item.id)}
              onToggle={() => toggle(item.id)}
              testId="step-tool"
            >
              <p className="text-xs text-muted-foreground">
                <span className="font-mono">{c.tool_name}</span> · {tStatus.has(c.status as "succeeded") ? tStatus(c.status as "succeeded") : c.status}
                {c.duration_ms !== null && ` · ${(c.duration_ms / 1000).toFixed(1)} ${t("seconds")}`}
              </p>
              <div>
                <p className="mb-1 text-xs text-muted-foreground">{t("args")}</p>
                <pre className="max-h-64 overflow-auto bg-muted p-2 text-xs whitespace-pre-wrap break-all">
                  {JSON.stringify(c.args, null, 2)}
                </pre>
              </div>
              {c.result && (
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">{t("output")}</p>
                  <pre className="max-h-96 overflow-auto bg-muted p-2 text-xs whitespace-pre-wrap break-all">{c.result}</pre>
                </div>
              )}
            </StepRow>
          );
        })}
        {running && !busyTool && (
          <li className="flex items-center gap-2 px-2 py-1.5 text-sm text-sky" role="status" data-testid="step-live">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            {status === "queued" ? t("queued") : t("thinking")}
          </li>
        )}
      </ol>
    </section>
  );
}
