"use client";

import type { McpServerOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import {
  addGitHubMcp,
  addMcpServer,
  deleteMcpServer,
  integrationsStatus,
  listMcpServers,
  refreshMcpServer,
  toolingKeys,
  updateMcpServer,
} from "@/lib/api/tooling";

import { ToolRow } from "./tools-section";

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: toolingKeys.mcp });
    void queryClient.invalidateQueries({ queryKey: toolingKeys.tools });
  };
}

function AddServer({ onDone }: { onDone: () => void }) {
  const t = useTranslations("integrations.mcp");
  const toMessage = useErrorMessage();
  const invalidate = useInvalidate();
  const uid = useId();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const add = useMutation({
    mutationFn: () => addMcpServer({ name: name.trim(), url: url.trim(), token: token || null }),
    onSuccess: () => {
      invalidate();
      onDone();
    },
  });
  const valid = name.trim() && /^https?:\/\//.test(url.trim());
  return (
    <form
      className="flex flex-col gap-3 rounded-lg border p-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        if (valid) add.mutate();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${uid}-name`}>{t("name")}</Label>
          <Input id={`${uid}-name`} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${uid}-url`}>{t("url")}</Label>
          <Input
            id={`${uid}-url`}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="http://mcp-time:8000/mcp"
          />
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${uid}-token`}>{t("token")}</Label>
        <Input
          id={`${uid}-token`}
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
      </div>
      <p className="text-xs text-muted-foreground">{t("addHint")}</p>
      {add.error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(add.error).message}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={!valid || add.isPending}>
          {t("add")}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t("cancel")}
        </Button>
      </div>
    </form>
  );
}

function ServerCard({ server }: { server: McpServerOut }) {
  const t = useTranslations("integrations.mcp");
  const toMessage = useErrorMessage();
  const invalidate = useInvalidate();
  const refresh = useMutation({ mutationFn: () => refreshMcpServer(server.id), onSuccess: invalidate });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => updateMcpServer(server.id, { enabled }),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: () => deleteMcpServer(server.id), onSuccess: invalidate });
  const error = refresh.error ?? toggle.error ?? remove.error;
  return (
    <li className="flex flex-col gap-2 rounded-lg border p-4" data-mcp-server={server.slug}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{server.name}</p>
          <p className="truncate font-mono text-xs text-muted-foreground">{server.url}</p>
          <p className="text-xs" role="status">
            {server.status === "ok"
              ? t("statusOk")
              : server.status === "error"
                ? t("statusError", { error: server.last_error ?? "" })
                : t("statusUnknown")}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <label className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={server.enabled} onChange={(e) => toggle.mutate(e.target.checked)} />
            {t("enabled")}
          </label>
          <Button
            size="icon"
            variant="ghost"
            aria-label={t("refresh")}
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            <RefreshCw />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label={t("remove")}
            onClick={() => {
              if (window.confirm(t("removeConfirm", { name: server.name }))) remove.mutate();
            }}
          >
            <Trash2 />
          </Button>
        </div>
      </div>
      {server.tools.length > 0 && (
        <ul className="divide-y border-t">
          {server.tools.map((tool) => (
            <ToolRow key={tool.name} tool={tool} />
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(error).message}
        </p>
      )}
    </li>
  );
}

const TOOLSETS = ["repos", "issues", "pull_requests", "actions", "code_security", "notifications"] as const;

/** One click: the official GitHub MCP server with the token from Integrations → GitHub. */
function GitHubMcp({ connected, present }: { connected: boolean; present: boolean }) {
  const t = useTranslations("integrations.mcp.github");
  const toMessage = useErrorMessage();
  const invalidate = useInvalidate();
  const [readonly, setReadonly] = useState(true);
  const [toolsets, setToolsets] = useState<string[]>(["repos", "issues", "pull_requests"]);
  const add = useMutation({ mutationFn: () => addGitHubMcp({ readonly, toolsets }), onSuccess: invalidate });
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-dashed p-4 text-sm" data-testid="github-mcp">
      <p className="font-medium">{t("title")}</p>
      <p className="text-xs text-muted-foreground">{connected ? t("hint") : t("needsToken")}</p>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={readonly} onChange={(e) => setReadonly(e.target.checked)} />
        {t("readonly")}
      </label>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {TOOLSETS.map((ts) => (
          <label key={ts} className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={toolsets.includes(ts)}
              onChange={(e) => setToolsets((list) => (e.target.checked ? [...list, ts] : list.filter((x) => x !== ts)))}
            />
            {ts}
          </label>
        ))}
      </div>
      <Button
        size="sm"
        className="self-start"
        disabled={!connected || toolsets.length === 0 || add.isPending}
        onClick={() => add.mutate()}
      >
        {present ? t("update") : t("connect")}
      </Button>
      {add.error && (
        <p role="alert" className="text-destructive">
          {toMessage(add.error).message}
        </p>
      )}
    </div>
  );
}

export function McpSection() {
  const t = useTranslations("integrations.mcp");
  const [adding, setAdding] = useState(false);
  const servers = useQuery({ queryKey: toolingKeys.mcp, queryFn: ({ signal }) => listMcpServers(signal) });
  const status = useQuery({ queryKey: toolingKeys.status, queryFn: ({ signal }) => integrationsStatus(signal) });
  const hasGitHub = servers.data?.some((s) => s.auth_source === "github") ?? false;
  return (
    <Card id="mcp">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <GitHubMcp connected={status.data?.github.connected ?? false} present={hasGitHub} />
        {!adding && (
          <Button variant="outline" className="self-start" onClick={() => setAdding(true)}>
            <Plus /> {t("addServer")}
          </Button>
        )}
        {adding && <AddServer onDone={() => setAdding(false)} />}
        <ul className="flex flex-col gap-3">
          {servers.data?.map((s) => (
            <ServerCard key={s.id} server={s} />
          ))}
        </ul>
        {servers.data?.length === 0 && !adding && <p className="text-sm text-muted-foreground">{t("empty")}</p>}
      </CardContent>
    </Card>
  );
}
