"use client";

import type { RecalledSourceOut } from "@moloko/shared-types";
import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { Brain, History, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { chatKeys, getChatSummary } from "@/lib/api/chat";

import { recallHref, recallKind } from "./recall";

/** «Older messages are condensed into a summary» + a dialog that shows the summary itself. */
export function SummaryNotice({ chatId, count }: { chatId: string; count: number }) {
  const t = useTranslations("chat.memory");
  const [open, setOpen] = useState(false);
  return (
    <>
      <div
        className="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-2 bg-card px-3 py-1.5 text-xs text-muted-foreground pixel-frame"
        data-testid="chat-summary-notice"
      >
        <History className="size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1">{t("summarised", { count })}</span>
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => setOpen(true)}>
          {t("showSummary")}
        </Button>
      </div>
      <SummaryDialog chatId={chatId} open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function SummaryDialog({ chatId, open, onClose }: { chatId: string; open: boolean; onClose: () => void }) {
  const t = useTranslations("chat.memory");
  const format = useFormatter();
  const toMessage = useErrorMessage();
  const summary = useQuery({
    queryKey: chatKeys.summary(chatId),
    queryFn: ({ signal }) => getChatSummary(chatId, signal),
    enabled: open,
  });
  const data = summary.data;
  return (
    <Dialog open={open} onClose={onClose} labelledBy="chat-summary-title" data-testid="chat-summary-dialog">
      <div className="flex flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <History className="size-5" aria-hidden="true" />
          <h2 id="chat-summary-title" className="flex-1 font-pixel text-lg">
            {t("summaryTitle")}
          </h2>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label={t("close")}>
            <X />
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">{t("summaryHint")}</p>
        {summary.isPending && <p className="text-sm text-muted-foreground">{t("loading")}</p>}
        {summary.error && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(summary.error).message}
          </p>
        )}
        {data &&
          (data.summary ? (
            <>
              <div className="max-h-[60vh] overflow-y-auto bg-background px-3 py-2 text-sm whitespace-pre-wrap pixel-frame pixel-sunken">
                {data.summary}
              </div>
              {data.summary_updated_at && (
                <p className="text-xs text-muted-foreground">
                  {t("summaryMeta", {
                    count: data.summary_messages,
                    when: format.dateTime(new Date(data.summary_updated_at), { dateStyle: "medium", timeStyle: "short" }),
                  })}
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{t("noSummary")}</p>
          ))}
      </div>
    </Dialog>
  );
}

/** «Taken into account from the past: …» under an answer that recall contributed to. */
export function RecalledSources({ sources }: { sources: RecalledSourceOut[] }) {
  const t = useTranslations("chat.memory");
  const format = useFormatter();
  if (sources.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground" data-testid="recalled-sources">
      <Brain className="size-3.5 shrink-0" aria-hidden="true" />
      <span>{t("recalled")}</span>
      <ul className="contents">
        {sources.map((s) => {
          const href = recallHref(s);
          const label = (
            <>
              <span className="max-w-48 truncate">{s.title || t(`kinds.${recallKind(s)}`)}</span>
              <span className="opacity-70">
                {t(`kinds.${recallKind(s)}`)}
                {s.date && ` · ${format.dateTime(new Date(s.date), { dateStyle: "short" })}`}
              </span>
            </>
          );
          return (
            <li key={`${s.type}-${s.id}`}>
              {href ? (
                <Link href={href} className="inline-flex items-center gap-1 bg-card px-1.5 py-0.5 hover:underline pixel-frame">
                  {label}
                </Link>
              ) : (
                <span className="inline-flex items-center gap-1 bg-card px-1.5 py-0.5 pixel-frame">{label}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
