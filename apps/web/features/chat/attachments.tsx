"use client";

import type { AttachmentOut } from "@moloko/shared-types";
import { useMutation } from "@tanstack/react-query";
import { Paperclip, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { uploadAttachment } from "@/lib/api/chat";

import { AttachmentChip } from "./attachment-chip";

export const MAX_ATTACHMENTS = 5; // files per message
const ACCEPT =
  ".txt,.md,.markdown,.csv,.tsv,.json,.yaml,.yml,.xml,.html,.log,.py,.js,.ts,.tsx,.jsx,.sql,.sh,.toml,.ini,.cfg,text/*,image/png,image/jpeg,image/webp,image/gif,application/pdf,.pdf";

/**
 * Files waiting to go with the next message. `ensureChat` gives the chat to upload into —
 * a new chat is created by the first file, so files can be added before the first message.
 */
export function useComposerAttachments({ chatId, ensureChat }: { chatId: string | null; ensureChat: () => Promise<string> }) {
  const t = useTranslations("chat");
  const [pending, setPending] = useState<AttachmentOut[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [skipped, setSkipped] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    // Each file on its own: one failure keeps the others that did upload.
    mutationFn: async (files: File[]) => {
      const id = await ensureChat();
      return Promise.allSettled(files.map((f) => uploadAttachment(id, f)));
    },
    onSuccess: (results) => {
      const added = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
      const failed = results.find((r) => r.status === "rejected");
      setPending((list) => [...list, ...added].slice(0, MAX_ATTACHMENTS));
      if (failed) setError(failed.reason);
    },
    onError: setError,
  });

  function button({ disabled }: { disabled?: boolean }) {
    return (
      <>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={ACCEPT}
          onChange={(e) => {
            const chosen = [...(e.target.files ?? [])];
            e.target.value = "";
            const files = chosen.slice(0, MAX_ATTACHMENTS - pending.length);
            setSkipped(chosen.length - files.length);
            if (files.length) {
              setError(null);
              upload.mutate(files);
            }
          }}
        />
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="shrink-0 rounded-full text-muted-foreground"
          aria-label={t("attach")}
          title={t("attach")}
          disabled={disabled || upload.isPending || pending.length >= MAX_ATTACHMENTS}
          onClick={() => input.current?.click()}
        >
          <Paperclip />
        </Button>
      </>
    );
  }

  const chips =
    pending.length > 0 && chatId ? (
      <ul className="flex flex-wrap gap-1 px-3 pt-3" aria-label={t("attachments")}>
        {pending.map((a) => (
          <AttachmentChip key={a.id} chatId={chatId} attachment={a}>
            <button
              type="button"
              aria-label={t("removeAttachment", { name: a.filename })}
              className="-m-1.5 flex size-7 items-center justify-center rounded-full text-muted-foreground hover:text-foreground"
              onClick={() => setPending((list) => list.filter((x) => x.id !== a.id))}
            >
              <X className="size-3" />
            </button>
          </AttachmentChip>
        ))}
      </ul>
    ) : null;

  const notice =
    skipped > 0 ? (
      <p role="status" className="px-4 text-xs text-muted-foreground">
        {t("tooManyFiles", { max: MAX_ATTACHMENTS, count: skipped })}
      </p>
    ) : null;

  return {
    pending,
    /** Takes the files for a message being sent; `restore` puts them back if it was not accepted. */
    take: () => {
      const kept = pending;
      setPending([]);
      return kept;
    },
    restore: (kept: AttachmentOut[]) => setPending((list) => (list.length ? list : kept)),
    error,
    clearError: () => setError(null),
    button,
    chips,
    notice,
  };
}
