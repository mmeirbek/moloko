"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { FileBrowser } from "@/features/workspaces/file-browser";
import { createWorkspace, listWorkspaces, toolingKeys } from "@/lib/api/tooling";

export function WorkspacesSection() {
  const t = useTranslations("workspaces");
  const format = useFormatter();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const workspaces = useQuery({
    queryKey: toolingKeys.workspaces,
    queryFn: ({ signal }) => listWorkspaces(undefined, signal),
  });
  const create = useMutation({
    mutationFn: () => createWorkspace(name.trim()),
    onSuccess: () => {
      setName("");
      void queryClient.invalidateQueries({ queryKey: toolingKeys.workspaces });
    },
  });
  return (
    <Card id="workspaces">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <form
          className="flex gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (name.trim()) create.mutate();
          }}
        >
          <Input
            aria-label={t("newProject")}
            placeholder={t("newProject")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit" disabled={!name.trim() || create.isPending}>
            {t("create")}
          </Button>
        </form>
        {create.error && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(create.error).message}
          </p>
        )}
        <ul className="flex flex-col divide-y rounded-md border">
          {workspaces.data?.map((ws) => (
            <li key={ws.id} className="flex flex-col gap-2 p-3">
              <button
                type="button"
                className="flex items-center justify-between gap-2 text-left text-sm"
                onClick={() => setOpen(open === ws.id ? null : ws.id)}
                aria-expanded={open === ws.id}
              >
                <span className="min-w-0 truncate font-medium">{ws.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {t(`kinds.${ws.kind as "task"}`)} · {format.dateTime(new Date(ws.created_at), { dateStyle: "short" })}
                  {ws.cleaned_at ? ` · ${t("cleaned")}` : ""}
                </span>
              </button>
              {open === ws.id && <FileBrowser workspaceId={ws.id} />}
            </li>
          ))}
        </ul>
        {workspaces.data?.length === 0 && <p className="text-sm text-muted-foreground">{t("none")}</p>}
      </CardContent>
    </Card>
  );
}
