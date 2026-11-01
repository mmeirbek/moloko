"use client";

import type { MemoryOut, MemoryType } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Pencil, Pin, PinOff, Plus, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConfirm } from "@/components/ui/confirm";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { systemLimits, systemLimitsKey } from "@/lib/api/agents";
import {
  agentMemoryContext,
  createMemory,
  deleteMemory,
  listMemories,
  memoryKeys,
  memoryRevisions,
  updateMemory,
  type MemoryScope,
} from "@/lib/api/memories";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/features/mascot/empty-state";
import { ErrorState, LoadingState } from "@/features/system/query-state";

const textareaClass = "rounded-md border border-input bg-background px-3 py-2 text-base md:text-sm";

/** Which memory types can be added in a scope (same rules as the API). */
export function typesFor(scope: MemoryScope): MemoryType[] {
  return "agentId" in scope ? ["agent", "project", "task_context", "conversation_context"] : ["user", "project"];
}

function MemoryEditor({ scope, memory, onDone }: { scope: MemoryScope; memory?: MemoryOut; onDone: () => void }) {
  const t = useTranslations("memory");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const uid = useId();
  const limits = useQuery({ queryKey: systemLimitsKey, queryFn: ({ signal }) => systemLimits(signal) });
  const [type, setType] = useState<MemoryType>((memory?.memory_type as MemoryType) ?? typesFor(scope)[0]);
  const [title, setTitle] = useState(memory?.title ?? "");
  const [content, setContent] = useState(memory?.content ?? "");
  const [project, setProject] = useState(memory?.project ?? "");
  const [pinned, setPinned] = useState(memory?.pinned ?? false);
  const max = limits.data?.memory_entry_max_chars;
  const tooLong = max !== undefined && content.trim().length > max;
  const needsProject = type === "project" && !project.trim();
  const valid = Boolean(title.trim() && content.trim()) && !tooLong && !needsProject;

  const save = useMutation({
    mutationFn: () =>
      memory
        ? updateMemory(memory.id, {
            title: title.trim(),
            content,
            pinned,
            ...(memory.memory_type === "project" ? { project: project.trim() } : {}),
          })
        : createMemory({
            memory_type: type,
            agent_id: "agentId" in scope && type !== "user" ? scope.agentId : null,
            project: type === "project" ? project.trim() : null,
            title: title.trim(),
            content,
            pinned,
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: memoryKeys.all });
      onDone();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (valid) save.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      {!memory && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${uid}-type`}>{t("type")}</Label>
          <select
            id={`${uid}-type`}
            value={type}
            onChange={(e) => setType(e.target.value as MemoryType)}
            className="h-10 rounded-md border border-input bg-background px-2 text-sm"
          >
            {typesFor(scope).map((ty) => (
              <option key={ty} value={ty}>
                {t(`types.${ty}`)}
              </option>
            ))}
          </select>
        </div>
      )}
      {(type === "project" || memory?.memory_type === "project") && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${uid}-project`}>{t("project")}</Label>
          <Input id={`${uid}-project`} value={project} maxLength={100} onChange={(e) => setProject(e.target.value)} />
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${uid}-title`}>{t("title")}</Label>
        <Input id={`${uid}-title`} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} autoFocus />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${uid}-content`}>{t("content")}</Label>
        <textarea
          id={`${uid}-content`}
          rows={5}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className={textareaClass}
          aria-invalid={tooLong}
        />
        {max !== undefined && (
          <p className={cn("text-xs", tooLong ? "text-destructive" : "text-muted-foreground")}>
            {t("chars", { count: content.trim().length, max })}
          </p>
        )}
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} />
        {t("pinned")}
      </label>
      {save.error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(save.error).message}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={!valid || save.isPending}>
          {t("save")}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t("cancel")}
        </Button>
      </div>
    </form>
  );
}

function Revisions({ memoryId }: { memoryId: string }) {
  const t = useTranslations("memory");
  const format = useFormatter();
  const revisions = useQuery({
    queryKey: memoryKeys.revisions(memoryId),
    queryFn: ({ signal }) => memoryRevisions(memoryId, signal),
  });
  return (
    <ol className="flex flex-col gap-2 border-l-2 pl-3 text-sm" aria-label={t("history")}>
      {revisions.data?.map((r) => (
        <li key={r.revision}>
          <p className="text-xs text-muted-foreground">
            {t("version", { n: r.revision })} ·{" "}
            {format.dateTime(new Date(r.created_at), { dateStyle: "short", timeStyle: "short" })}
          </p>
          <p className="font-medium">{r.title}</p>
          <p className="whitespace-pre-wrap text-muted-foreground">{r.content}</p>
        </li>
      ))}
    </ol>
  );
}

function MemoryItem({ memory, scope }: { memory: MemoryOut; scope: MemoryScope }) {
  const t = useTranslations("memory");
  const confirm = useConfirm();
  const format = useFormatter();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [history, setHistory] = useState(false);
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: memoryKeys.all });
  const pin = useMutation({
    mutationFn: () => updateMemory(memory.id, { pinned: !memory.pinned }),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: () => deleteMemory(memory.id), onSuccess: invalidate });
  const error = pin.error ?? remove.error;

  if (editing) return <MemoryEditor scope={scope} memory={memory} onDone={() => setEditing(false)} />;
  return (
    <li className="flex flex-col gap-2 rounded-lg border bg-card p-4" data-memory-id={memory.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 font-medium">
            {memory.pinned && <Pin className="size-3.5 shrink-0" aria-label={t("pinned")} />}
            <span className="truncate">{memory.title}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            {t(`types.${memory.memory_type as MemoryType}`)}
            {memory.project ? ` · ${memory.project}` : ""} · {t("version", { n: memory.revision })} ·{" "}
            {format.dateTime(new Date(memory.updated_at), { dateStyle: "short", timeStyle: "short" })}
          </p>
        </div>
        <div className="flex gap-1">
          <Button size="icon" variant="ghost" aria-label={t("edit")} onClick={() => setEditing(true)}>
            <Pencil />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label={memory.pinned ? t("unpin") : t("pin")}
            onClick={() => pin.mutate()}
          >
            {memory.pinned ? <PinOff /> : <Pin />}
          </Button>
          {memory.revision > 1 && (
            <Button
              size="icon"
              variant="ghost"
              aria-label={t("history")}
              aria-expanded={history}
              onClick={() => setHistory((v) => !v)}
            >
              <History />
            </Button>
          )}
          <Button
            size="icon"
            variant="ghost"
            aria-label={t("forget")}
            disabled={remove.isPending}
            onClick={async () => {
              if (await confirm({ title: t("forgetConfirm", { title: memory.title }), confirmLabel: t("forget"), destructive: true }))
                remove.mutate();
            }}
          >
            <Trash2 />
          </Button>
        </div>
      </div>
      <p className="text-sm whitespace-pre-wrap">{memory.content}</p>
      {history && <Revisions memoryId={memory.id} />}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(error).message}
        </p>
      )}
    </li>
  );
}

/** What the agent's prompt really receives from memory, and how much of the budget it uses. */
export function MemoryContextPreview({ agentId }: { agentId: string }) {
  const t = useTranslations("memory.context");
  const ctx = useQuery({
    queryKey: memoryKeys.context(agentId),
    queryFn: ({ signal }) => agentMemoryContext(agentId, signal),
  });
  if (!ctx.data) return null;
  const { enabled, chars, max_chars, included, omitted, text } = ctx.data;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-dashed p-4 text-sm" data-testid="memory-context">
      {!enabled ? (
        <p className="text-muted-foreground">{t("disabled")}</p>
      ) : (
        <>
          <p>{t("summary", { included: included.length, chars, max: max_chars })}</p>
          {omitted.length > 0 && (
            <p className="text-amber-700 dark:text-amber-300">{t("omitted", { count: omitted.length })}</p>
          )}
          {text && (
            <details>
              <summary className="cursor-pointer text-muted-foreground">{t("show")}</summary>
              <pre className="mt-2 max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">
                {text}
              </pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}

export function MemoryPanel({ scope }: { scope: MemoryScope }) {
  const t = useTranslations("memory");
  const [adding, setAdding] = useState(false);
  const memories = useQuery({
    queryKey: memoryKeys.list(scope),
    queryFn: ({ signal }) => listMemories(scope, signal),
  });
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-prose text-sm text-muted-foreground">
          {"agentId" in scope ? t("agentIntro") : t("sharedIntro")}
        </p>
        {!adding && (
          <Button onClick={() => setAdding(true)}>
            <Plus /> {t("add")}
          </Button>
        )}
      </div>
      {"agentId" in scope && <MemoryContextPreview agentId={scope.agentId} />}
      {adding && <MemoryEditor scope={scope} onDone={() => setAdding(false)} />}
      {memories.isPending && <LoadingState />}
      {memories.isError && !memories.data && <ErrorState error={memories.error} onRetry={() => memories.refetch()} />}
      <ul className="flex flex-col gap-3">
        {memories.data?.map((m) => (
          <MemoryItem key={m.id} memory={m} scope={scope} />
        ))}
      </ul>
      {memories.data?.length === 0 && !adding && (
        <EmptyState title={t("empty")} mood="sleep" className="rounded-lg border border-dashed" />
      )}
    </div>
  );
}
