"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Send, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { PixelCow } from "@/features/mascot/pixel-cow";
import { MicButton } from "@/features/voice/mic-button";
import { runKeys, startRun } from "@/lib/api/runs";

/** "New task" for the Orchestrator, opened from the cow button (phone tab bar, sidebar). */
export function NewTaskDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useTranslations("newTask");
  const toMessage = useErrorMessage();
  const router = useRouter();
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDialogElement>(null);
  const [text, setText] = useState("");

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const start = useMutation({
    mutationFn: () => {
      const title = text.split("\n")[0]!.slice(0, 120).trim() || t("untitled");
      return startRun({ title, description: text });
    },
    onSuccess: (started) => {
      setText("");
      void queryClient.invalidateQueries({ queryKey: runKeys.list });
      onClose();
      router.push(`/office/subagents?run=${started.run.id}`);
    },
  });

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="new-task-title"
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-xl border bg-card p-0 text-card-foreground shadow-xl backdrop:bg-black/40"
      data-testid="new-task-dialog"
    >
      <form
        method="dialog"
        className="flex flex-col gap-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) start.mutate();
        }}
      >
        <div className="flex items-center gap-3">
          <PixelCow mood="happy" size={40} />
          <h2 id="new-task-title" className="flex-1 text-lg">
            {t("title")}
          </h2>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label={t("close")}>
            <X />
          </Button>
        </div>
        <label htmlFor="new-task-text" className="text-sm text-muted-foreground">
          {t("hint")}
        </label>
        <textarea
          id="new-task-text"
          rows={4}
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("placeholder")}
          className="rounded-md border border-input bg-background px-3 py-2 text-base md:text-sm"
        />
        {start.error && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(start.error).message}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <MicButton onText={(spoken) => setText((cur) => (cur ? `${cur.trimEnd()} ${spoken}` : spoken))} />
          <Button type="submit" disabled={!text.trim() || start.isPending}>
            <Send /> {t("start")}
          </Button>
        </div>
      </form>
    </dialog>
  );
}

/** Renders `children(open)` plus the dialog; keeps the open state in one place. */
export function NewTaskLauncher({ children }: { children: (open: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {children(() => setOpen(true))}
      <NewTaskDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
