"use client";

import { useTranslations } from "next-intl";

import { RotateCcw } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { cn } from "@/lib/utils";

/** A part of a page on its way: placeholder lines (the words stay for screen readers). */
export function LoadingState({ className, rows = 3 }: { className?: string; rows?: number }) {
  const t = useTranslations("common");
  return (
    <div role="status" className={cn("flex flex-col gap-2.5 py-1", className)}>
      <span className="sr-only">{t("loading")}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn("h-3.5", i === rows - 1 ? "w-3/5" : "w-full")} />
      ))}
    </div>
  );
}

/** A failed request said in words, with its error id and a retry — never an endless "Loading…". */
export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const t = useTranslations("common");
  const toMessage = useErrorMessage();
  const { message, errorId } = toMessage(error);
  return (
    <div role="alert" className={cn("flex flex-col items-start gap-2 rounded-xl border p-4 text-sm", className)}>
      <p>{message}</p>
      {errorId && <p className="font-mono text-xs text-muted-foreground">{t("errorId", { id: errorId })}</p>}
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCcw /> {t("retry")}
        </Button>
      )}
    </div>
  );
}
