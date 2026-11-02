"use client";

import type { SearchHitOut } from "@moloko/shared-types";
import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import {
  Brain,
  FileText,
  ListChecks,
  MessageSquare,
  Paperclip,
  Search as SearchIcon,
  Send,
  Sparkles,
} from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/features/agents/status-badge";
import { EmptyState } from "@/features/mascot/empty-state";
import { MicButton } from "@/features/voice/mic-button";
import { searchAll, searchKeys } from "@/lib/api/search";
import { cn } from "@/lib/utils";
import { ErrorState } from "@/features/system/query-state";

const TYPES = ["memory", "file", "attachment", "task", "agent_message", "chat_message"] as const;
type HitType = (typeof TYPES)[number];
const ICON = {
  memory: Brain,
  file: FileText,
  attachment: Paperclip,
  task: ListChecks,
  agent_message: Send,
  chat_message: MessageSquare,
} as const;

/** Where a hit lives in the app. Pure: tested. */
export function hitHref(hit: SearchHitOut): string {
  switch (hit.source_type) {
    case "attachment":
    case "chat_message":
      return hit.conversation_id ? `/chat/${hit.conversation_id}` : "/chat";
    case "memory":
      return hit.agent_id ? `/office/agents/${hit.agent_id}` : "/settings";
    case "task":
      return `/tasks/${hit.source_id}`;
    case "agent_message":
      if (hit.agent_id) return `/office/agents/${hit.agent_id}?tab=messages`;
      return hit.task_id ? `/tasks/${hit.task_id}` : "/office";
    default:
      return "/integrations";
  }
}

/** Who did it: the agent of a task, "A → B" for agents' messages, you / reply in chats. */
function HitWho({ hit }: { hit: SearchHitOut }) {
  const t = useTranslations("search");
  if (hit.source_type === "task") return hit.agent_name ? <span>{hit.agent_name}</span> : null;
  if (hit.source_type === "agent_message")
    return <span>{t("from", { from: hit.agent_name ?? "?", to: hit.peer_agent_name ?? "?" })}</span>;
  if (hit.source_type === "chat_message" && (hit.role === "user" || hit.role === "assistant"))
    return <span>{t(`role.${hit.role}`)}</span>;
  return null;
}

/** Search memories, files, chat files and the work history — by meaning when available. */
export function SearchView() {
  const t = useTranslations("search");
  const format = useFormatter();
  const initial = useSearchParams().get("q") ?? "";
  const [text, setText] = useState(initial);
  const [query, setQuery] = useState(initial);
  const [types, setTypes] = useState<string[]>([...TYPES]);
  const typesKey = types.join(",");
  const results = useQuery({
    queryKey: searchKeys.query(query, typesKey),
    queryFn: ({ signal }) => searchAll(query, typesKey, signal),
    enabled: query.trim().length > 0 && types.length > 0,
  });
  const hits = results.data?.hits ?? [];

  return (
    <div className="flex flex-col gap-4">
      <form
        role="search"
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(text.trim());
        }}
      >
        <div className="relative flex-1">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("placeholder")}
            aria-label={t("label")}
            className="pl-12"
            autoFocus
          />
        </div>
        <MicButton
          onText={(spoken) => {
            setText(spoken);
            setQuery(spoken);
          }}
        />
        <Button type="submit" disabled={!text.trim()}>
          {t("go")}
        </Button>
      </form>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t("filters")}>
        {TYPES.map((type) => {
          const on = types.includes(type);
          const Icon = ICON[type];
          return (
            <button
              key={type}
              type="button"
              aria-pressed={on}
              onClick={() => setTypes((list) => (on ? list.filter((x) => x !== type) : [...list, type]))}
              className={cn(
                "inline-flex items-center gap-1.5 border-2 px-3 py-1 text-sm",
                on ? "bg-accent text-accent-foreground" : "text-muted-foreground",
              )}
            >
              <Icon className="size-3.5" /> {t(`types.${type}`)}
            </button>
          );
        })}
      </div>

      {results.isFetching && <p role="status" className="text-sm text-muted-foreground">{t("searching")}</p>}
      {query && results.isError && !results.isFetching && (
        <ErrorState error={results.error} onRetry={() => results.refetch()} />
      )}
      {query && results.isSuccess && hits.length === 0 && (
        <EmptyState title={t("nothing")} hint={t("nothingHint")} mood="sad" className="border-2 border-dashed" />
      )}
      {hits.length > 0 && (
        <>
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            {hits[0]!.mode === "semantic" ? (
              <>
                <Sparkles className="size-3.5" /> {t("bySense")}
              </>
            ) : (
              t("byWords")
            )}
          </p>
          <ol className="flex flex-col gap-2" data-testid="search-results">
            {hits.map((hit) => {
              const known = (TYPES as readonly string[]).includes(hit.source_type);
              const Icon = known ? ICON[hit.source_type as HitType] : FileText;
              return (
                <li key={`${hit.source_type}-${hit.source_id}`} className="bg-card p-3 pixel-frame">
                  <Link href={hitHref(hit)} className="flex items-center gap-2 font-medium hover:underline">
                    <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
                    <span className="truncate">{hit.title}</span>
                    <span className="ml-auto shrink-0 text-xs font-normal text-muted-foreground">
                      {known ? t(`types.${hit.source_type as HitType}`) : hit.source_type}
                    </span>
                  </Link>
                  {(hit.source_at || hit.agent_name || hit.role || hit.status) && (
                    <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                      {hit.source_at && (
                        <time dateTime={hit.source_at}>
                          {format.dateTime(new Date(hit.source_at), { dateStyle: "short", timeStyle: "short" })}
                        </time>
                      )}
                      <HitWho hit={hit} />
                      {hit.source_type === "task" && hit.status && <StatusBadge status={hit.status} />}
                    </p>
                  )}
                  <p className="mt-1 line-clamp-3 text-sm whitespace-pre-line text-muted-foreground">{hit.snippet}</p>
                </li>
              );
            })}
          </ol>
        </>
      )}
      {!query && <EmptyState title={t("start")} hint={t("startHint")} mood="happy" />}
    </div>
  );
}
