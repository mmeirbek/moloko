"use client";

import type { SearchHitOut } from "@moloko/shared-types";
import { useQuery } from "@tanstack/react-query";
import { Brain, FileText, MessageSquare, Search as SearchIcon, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/features/mascot/empty-state";
import { MicButton } from "@/features/voice/mic-button";
import { searchAll, searchKeys } from "@/lib/api/search";
import { cn } from "@/lib/utils";

const TYPES = ["memory", "file", "attachment"] as const;
const ICON = { memory: Brain, file: FileText, attachment: MessageSquare } as const;

/** Where a hit lives in the app. Pure: tested. */
export function hitHref(hit: SearchHitOut): string {
  if (hit.source_type === "attachment" && hit.conversation_id) return `/chat/${hit.conversation_id}`;
  if (hit.source_type === "memory") return hit.agent_id ? `/office/agents/${hit.agent_id}` : "/settings";
  return "/integrations";
}

/** Search memories, workspace files and chat files — by meaning when available. */
export function SearchView() {
  const t = useTranslations("search");
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
    <div className="flex max-w-3xl flex-col gap-4">
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
            className="pl-9"
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
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm",
                on ? "bg-accent text-accent-foreground" : "text-muted-foreground",
              )}
            >
              <Icon className="size-3.5" /> {t(`types.${type}`)}
            </button>
          );
        })}
      </div>

      {results.isFetching && <p className="text-sm text-muted-foreground">{t("searching")}</p>}
      {query && results.isSuccess && hits.length === 0 && (
        <EmptyState title={t("nothing")} hint={t("nothingHint")} mood="sad" className="rounded-lg border border-dashed" />
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
              const Icon = ICON[hit.source_type as keyof typeof ICON] ?? FileText;
              return (
                <li key={`${hit.source_type}-${hit.source_id}`} className="rounded-lg border bg-card p-3">
                  <Link href={hitHref(hit)} className="flex items-center gap-2 font-medium hover:underline">
                    <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
                    <span className="truncate">{hit.title}</span>
                    <span className="ml-auto shrink-0 text-xs font-normal text-muted-foreground">
                      {t(`types.${hit.source_type as (typeof TYPES)[number]}`)}
                    </span>
                  </Link>
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
