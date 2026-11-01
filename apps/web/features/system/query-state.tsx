"use client";

import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { cn } from "@/lib/utils";

/** "Loading…" for a part of a page. */
export function LoadingState({ className }: { className?: string }) {
  const t = useTranslations("common");
  return (
    <p role="status" className={cn("text-sm text-muted-foreground", className)}>
      {t("loading")}
    </p>
  );
}

/** A failed request said in words, with its error id and a retry — never an endless "Loading…". */
export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const t = useTranslations("common");
  const toMessage = useErrorMessage();
  const { message, errorId } = toMessage(error);
  return (
    <div role="alert" className={cn("flex flex-col items-start gap-2 rounded-lg border p-4 text-sm", className)}>
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
