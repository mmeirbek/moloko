"use client";

import type { AttachmentOut } from "@moloko/shared-types";
import { FileText, Paperclip } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { attachmentUrl } from "@/lib/api/chat";

/** One attached file: pictures as thumbnails, PDFs with their page count, text files as a chip. */
export function AttachmentChip({
  chatId,
  attachment: a,
  children,
}: {
  chatId: string;
  attachment: AttachmentOut;
  children?: ReactNode;
}) {
  const t = useTranslations("chat");
  const url = attachmentUrl(chatId, a.id);
  if (a.kind === "image") {
    return (
      <li className="relative" data-attachment={a.filename}>
        <a href={url} target="_blank" rel="noreferrer" title={a.filename}>
          {/* eslint-disable-next-line @next/next/no-img-element -- authenticated same-origin file */}
          <img src={url} alt={a.filename} className="size-20 rounded-md border object-cover" loading="lazy" />
        </a>
        {children && <span className="absolute top-0.5 right-0.5 rounded bg-card/90">{children}</span>}
      </li>
    );
  }
  return (
    <li className="inline-flex items-center gap-1 rounded-md border bg-card px-2 py-1 text-xs" data-attachment={a.filename}>
      {a.kind === "pdf" ? <FileText className="size-3" aria-hidden /> : <Paperclip className="size-3" aria-hidden />}
      <a href={url} className="hover:underline" download={a.filename}>
        {a.filename}
      </a>
      {a.kind === "pdf" && a.pages ? (
        <span className="text-muted-foreground">· {t("pages", { count: a.pages })}</span>
      ) : null}
      {children}
    </li>
  );
}
