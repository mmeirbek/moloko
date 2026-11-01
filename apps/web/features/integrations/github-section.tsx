"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { getGitHub, putGitHub, testGitHub, toolingKeys } from "@/lib/api/tooling";

export function parseRepos(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/[\s,]+/)
        .map((r) => r.trim())
        .filter(Boolean),
    ),
  ];
}

export function GitHubSection() {
  const t = useTranslations("integrations.github");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const uid = useId();
  const github = useQuery({ queryKey: toolingKeys.github, queryFn: ({ signal }) => getGitHub(signal) });
  const [token, setToken] = useState("");
  const [repos, setRepos] = useState<string | null>(null);
  const reposText = repos ?? (github.data?.allowed_repos ?? []).join("\n");
  const done = () => {
    setToken("");
    setRepos(null);
    void queryClient.invalidateQueries({ queryKey: toolingKeys.github });
    void queryClient.invalidateQueries({ queryKey: toolingKeys.tools });
    void queryClient.invalidateQueries({ queryKey: toolingKeys.status });
  };
  const save = useMutation({
    mutationFn: () => putGitHub({ ...(token ? { token } : {}), allowed_repos: parseRepos(reposText) }),
    onSuccess: done,
  });
  const disconnect = useMutation({ mutationFn: () => putGitHub({ clear_token: true }), onSuccess: done });
  const test = useMutation({ mutationFn: testGitHub, onSuccess: done });
  const data = github.data;
  const error = save.error ?? disconnect.error ?? test.error;

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <Card id="github">
      <CardHeader>
        <CardTitle>GitHub</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm" role="status">
          {data?.connected
            ? data.status === "error"
              ? t("error", { error: data.last_error ?? "" })
              : t("connected", { login: data.login ?? "?", hint: data.token_hint ?? "" })
            : t("notConnected")}
        </p>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${uid}-token`}>{data?.connected ? t("newToken") : t("token")}</Label>
            <Input
              id={`${uid}-token`}
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="github_pat_…"
            />
            <p className="text-xs text-muted-foreground">{t("tokenHint")}</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${uid}-repos`}>{t("repos")}</Label>
            <textarea
              id={`${uid}-repos`}
              rows={3}
              value={reposText}
              onChange={(e) => setRepos(e.target.value)}
              placeholder="owner/repository"
              className="rounded-md border border-input bg-background px-3 py-2 font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">{t("reposHint")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={save.isPending || (!token && !data?.connected)}>
              {t("save")}
            </Button>
            {data?.connected && (
              <>
                <Button type="button" variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>
                  {t("test")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  className="text-destructive"
                  onClick={() => {
                    if (window.confirm(t("disconnectConfirm"))) disconnect.mutate();
                  }}
                >
                  {t("disconnect")}
                </Button>
              </>
            )}
          </div>
        </form>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(error).message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
