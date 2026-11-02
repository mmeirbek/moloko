"use client";

import type { AttachmentOut } from "@moloko/shared-types";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent } from "react";

import { File as FileIcon, FileText, Paperclip, RotateCcw, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { uploadAttachment } from "@/lib/api/chat";
import { cn } from "@/lib/utils";

const PARALLEL = 3; // uploads at the same time; the rest wait their turn

type Item = {
  key: string;
  name: string;
  size: number;
  type: string;
  file: File | null; // null for a file put back after a failed send (already uploaded)
  preview: string | null; // object URL of a picture, shown before the upload finishes
  status: "uploading" | "done" | "failed";
  progress: number; // 0…1
  attachment: AttachmentOut | null;
  error: unknown;
};

function hasFiles(e: DragEvent): boolean {
  return Array.from(e.dataTransfer.types).includes("Files");
}

/** "2,4 МБ" */
export function useFileSize() {
  const format = useFormatter();
  return (bytes: number) => {
    const units = ["byte", "kilobyte", "megabyte", "gigabyte"] as const;
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return format.number(value, { style: "unit", unit: units[unit], unitDisplay: "short", maximumFractionDigits: unit ? 1 : 0 });
  };
}

/**
 * Files going with the next message — any number, any size, any type. Each uploads on its own
 * (progress, cancel, retry); pictures show at once. Files come from the button, a drop onto the
 * chat, or a paste. `ensureChat` gives the chat to upload into (a new chat is created by the
 * first file). Sending waits for the uploads in flight.
 */
export function useComposerAttachments({ ensureChat }: { ensureChat: () => Promise<string> }) {
  const t = useTranslations("chat");
  const toMessage = useErrorMessage();
  const fileSize = useFileSize();
  const [items, setItems] = useState<Item[]>([]);
  const latest = useRef<Item[]>([]); // the same list for async code (take() runs after awaits)
  const controllers = useRef(new Map<string, AbortController>());
  const running = useRef(new Map<string, Promise<void>>());
  const slots = useRef({ free: PARALLEL, waiting: [] as (() => void)[] });
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const depth = useRef(0);

  const commit = (change: (list: Item[]) => Item[]) => {
    latest.current = change(latest.current);
    setItems(latest.current);
  };
  const patch = (key: string, values: Partial<Item>) =>
    commit((list) => list.map((i) => (i.key === key ? { ...i, ...values } : i)));

  // Pictures' object URLs are released when the composer goes away.
  useEffect(() => {
    const kept = latest;
    return () => kept.current.forEach((i) => i.preview && URL.revokeObjectURL(i.preview));
  }, []);

  async function slot() {
    if (slots.current.free > 0) {
      slots.current.free -= 1;
      return;
    }
    await new Promise<void>((resolve) => slots.current.waiting.push(resolve));
  }
  function release() {
    const next = slots.current.waiting.shift();
    if (next) next();
    else slots.current.free += 1;
  }

  function upload(item: Item) {
    if (!item.file) return;
    const file = item.file;
    const controller = new AbortController();
    controllers.current.set(item.key, controller);
    const job = (async () => {
      await slot();
      try {
        if (controller.signal.aborted) return;
        const id = await ensureChat();
        const attachment = await uploadAttachment(id, file, {
          signal: controller.signal,
          onProgress: (progress) => patch(item.key, { progress }),
        });
        patch(item.key, { status: "done", progress: 1, attachment });
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) patch(item.key, { status: "failed", error });
      } finally {
        release();
        controllers.current.delete(item.key);
        running.current.delete(item.key);
      }
    })();
    running.current.set(item.key, job);
  }

  function add(files: File[]) {
    const added: Item[] = files.map((file) => ({
      key: crypto.randomUUID(),
      name: file.name || t("pastedFile"),
      size: file.size,
      type: file.type,
      file,
      preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : null,
      status: "uploading",
      progress: 0,
      attachment: null,
      error: null,
    }));
    if (!added.length) return;
    commit((list) => [...list, ...added]);
    added.forEach(upload);
  }

  function remove(key: string) {
    controllers.current.get(key)?.abort();
    const item = latest.current.find((i) => i.key === key);
    if (item?.preview) URL.revokeObjectURL(item.preview);
    commit((list) => list.filter((i) => i.key !== key));
  }

  function retry(key: string) {
    const item = latest.current.find((i) => i.key === key);
    if (!item?.file) return;
    patch(key, { status: "uploading", progress: 0, error: null });
    upload(item);
  }

  const uploading = items.some((i) => i.status === "uploading");
  const failed = items.filter((i) => i.status === "failed").length;

  // Drop files anywhere on the chat; the office's own drag type is not files, so it is ignored.
  const dropProps = {
    onDragEnter: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setOver(true);
    },
    onDragOver: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setOver(false);
    },
    onDrop: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setOver(false);
      add(Array.from(e.dataTransfer.files));
    },
  };

  /** ⌘V of a screenshot or copied files attaches them (text pastes as usual). */
  function onPaste(e: ClipboardEvent) {
    const files = Array.from(e.clipboardData.files);
    if (!files.length) return;
    e.preventDefault();
    add(files);
  }

  function button({ disabled }: { disabled?: boolean }) {
    return (
      <>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            const chosen = Array.from(e.target.files ?? []);
            e.target.value = "";
            add(chosen);
          }}
        />
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="shrink-0 text-muted-foreground"
          aria-label={t("attach")}
          title={t("attach")}
          disabled={disabled}
          onClick={() => input.current?.click()}
        >
          <Paperclip />
        </Button>
      </>
    );
  }

  const chips =
    items.length > 0 ? (
      <ul className="flex flex-wrap gap-3 px-3 pt-3" aria-label={t("attachments")} data-testid="composer-files">
        {items.map((i) => (
          <li
            key={i.key}
            data-attachment={i.name}
            data-status={i.status}
            title={i.status === "failed" ? toMessage(i.error).message : `${i.name} · ${fileSize(i.size)}`}
            className={cn(
              "relative flex max-w-64 items-center gap-2 bg-card py-1 pr-1 pl-2 text-xs pixel-frame",
              i.status === "failed" && "[--frame-color:var(--color-destructive)]",
            )}
          >
            {i.preview ? (
              // eslint-disable-next-line @next/next/no-img-element -- a local preview (object URL)
              <img src={i.preview} alt={i.name} className="size-8 shrink-0 object-cover" />
            ) : i.type === "application/pdf" || i.type.startsWith("text/") ? (
              <FileText className="shrink-0 text-muted-foreground" aria-hidden />
            ) : (
              <FileIcon className="shrink-0 text-muted-foreground" aria-hidden />
            )}
            <span className="flex min-w-0 flex-col">
              <span className="truncate">{i.name}</span>
              <span className="text-muted-foreground">
                {i.status === "uploading"
                  ? t("uploading", { percent: Math.round(i.progress * 100) })
                  : i.status === "failed"
                    ? t("uploadFailed")
                    : fileSize(i.size)}
              </span>
            </span>
            {i.status === "failed" && i.file && (
              <button
                type="button"
                aria-label={t("retryUpload", { name: i.name })}
                title={t("retryUpload", { name: i.name })}
                className="flex size-6 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
                onClick={() => retry(i.key)}
              >
                <RotateCcw className="size-3" />
              </button>
            )}
            <button
              type="button"
              aria-label={t("removeAttachment", { name: i.name })}
              title={t("removeAttachment", { name: i.name })}
              className="flex size-6 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
              onClick={() => remove(i.key)}
            >
              <X className="size-3" />
            </button>
            {i.status === "uploading" && (
              <span className="absolute inset-x-0 bottom-0 h-1 bg-muted" aria-hidden>
                <span className="block h-full bg-sky" style={{ width: `${Math.round(i.progress * 100)}%` }} />
              </span>
            )}
          </li>
        ))}
      </ul>
    ) : null;

  const dropOverlay = over ? (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-2 z-30 flex items-center justify-center bg-background/85 pixel-frame [--frame-color:var(--color-sky)]"
      data-testid="file-drop"
    >
      <p className="flex items-center gap-3 font-pixel text-lg">
        <Paperclip /> {t("dropFiles")}
      </p>
    </div>
  ) : null;

  const notice =
    failed > 0 ? (
      <p role="alert" className="px-4 text-xs text-destructive">
        {t("someUploadsFailed", { count: failed })}
      </p>
    ) : uploading ? (
      <p role="status" className="px-4 text-xs text-muted-foreground">
        {t("uploadingFiles")}
      </p>
    ) : null;

  return {
    uploading,
    /** For a message being sent: waits for uploads in flight, then takes the uploaded files. */
    take: async (): Promise<AttachmentOut[]> => {
      await Promise.all([...running.current.values()]);
      const done = latest.current.filter((i) => i.status === "done" && i.attachment);
      done.forEach((i) => i.preview && URL.revokeObjectURL(i.preview));
      commit((list) => list.filter((i) => i.status !== "done"));
      return done.map((i) => i.attachment!);
    },
    /** Puts files back after a send the server did not accept. */
    restore: (kept: AttachmentOut[]) =>
      commit((list) => [
        ...kept.map<Item>((a) => ({
          key: a.id,
          name: a.filename,
          size: a.size,
          type: a.content_type,
          file: null,
          preview: null,
          status: "done",
          progress: 1,
          attachment: a,
          error: null,
        })),
        ...list,
      ]),
    button,
    chips,
    notice,
    dropProps,
    dropOverlay,
    onPaste,
  };
}
