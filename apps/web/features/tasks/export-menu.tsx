"use client";

import { Check, FileDown, FileText, Link2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { ApiError } from "@/lib/api/errors";
import { exportTaskPdf, taskMarkdownUrl } from "@/lib/api/export";

/** Download the result as Markdown or PDF, or copy a link to it (opens after sign-in). */
export function ExportMenu({ taskId, title }: { taskId: string; title: string }) {
  const t = useTranslations("export");
  const toMessage = useErrorMessage();
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pdf() {
    setBusy(true);
    setError(null);
    try {
      const blob = await exportTaskPdf(taskId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title.slice(0, 60) || "result"}.pdf`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      // No sandbox browser on this server: the browser's own "Save as PDF" still works.
      if (e instanceof ApiError && e.code === "pdf_unavailable") window.print();
      else setError(toMessage(e).message);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/tasks/${taskId}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError(t("copyFailed"));
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1 print:hidden" data-testid="export-menu">
      <Button size="sm" variant="outline" asChild>
        <a href={taskMarkdownUrl(taskId)} download>
          <FileText /> Markdown
        </a>
      </Button>
      <Button size="sm" variant="outline" onClick={() => void pdf()} disabled={busy}>
        <FileDown /> PDF
      </Button>
      <Button size="sm" variant="ghost" onClick={() => void copy()}>
        {copied ? <Check /> : <Link2 />} {copied ? t("copied") : t("link")}
      </Button>
      {error && (
        <p role="alert" className="w-full text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
