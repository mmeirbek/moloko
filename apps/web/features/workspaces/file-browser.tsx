"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, File, Folder, RefreshCw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { toolingKeys, workspaceFile, workspaceFiles } from "@/lib/api/tooling";

export function parentOf(path: string): string {
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.length ? parts.join("/") : ".";
}

/** Read-only view of a workspace: what agents created and changed. */
export function FileBrowser({ workspaceId }: { workspaceId: string }) {
  const t = useTranslations("workspaces");
  const format = useFormatter();
  const [path, setPath] = useState(".");
  const [open, setOpen] = useState<string | null>(null);
  const entries = useQuery({
    queryKey: toolingKeys.files(workspaceId, path),
    queryFn: ({ signal }) => workspaceFiles(workspaceId, path, signal),
  });
  const file = useQuery({
    queryKey: toolingKeys.file(workspaceId, open ?? ""),
    queryFn: ({ signal }) => workspaceFile(workspaceId, open ?? "", signal),
    enabled: open !== null,
  });
  return (
    <div className="flex flex-col gap-2 text-sm" data-testid="file-browser">
      <div className="flex items-center gap-2">
        {path !== "." && (
          <Button size="icon" variant="ghost" aria-label={t("up")} onClick={() => setPath(parentOf(path))}>
            <ChevronLeft />
          </Button>
        )}
        <span className="min-w-0 flex-1 truncate font-mono text-xs">/{path === "." ? "" : path}</span>
        <Button size="icon" variant="ghost" aria-label={t("refresh")} onClick={() => void entries.refetch()}>
          <RefreshCw />
        </Button>
      </div>
      {entries.data?.length === 0 && <p className="text-muted-foreground">{t("empty")}</p>}
      <ul className="flex flex-col divide-y rounded-md border">
        {entries.data?.map((e) => (
          <li key={e.path}>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent"
              onClick={() => (e.type === "dir" ? setPath(e.path) : e.type === "file" ? setOpen(e.path) : undefined)}
            >
              {e.type === "dir" ? <Folder className="size-4 shrink-0" /> : <File className="size-4 shrink-0" />}
              <span className="min-w-0 flex-1 truncate">{e.path.split("/").pop()}</span>
              {e.type === "file" && <span className="text-xs text-muted-foreground">{format.number(e.size)} B</span>}
              {e.type === "link" && <span className="text-xs text-muted-foreground">{t("link")}</span>}
            </button>
          </li>
        ))}
      </ul>
      {open && file.data && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-mono text-xs">{file.data.path}</span>
            <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>
              {t("close")}
            </Button>
          </div>
          <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap break-all">
            {file.data.content}
          </pre>
          {file.data.truncated && <p className="text-xs text-muted-foreground">{t("truncated")}</p>}
        </div>
      )}
    </div>
  );
}
