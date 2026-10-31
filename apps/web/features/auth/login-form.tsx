"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authKeys, getMe, login } from "@/lib/api/auth";
import { safeNextPath } from "@/lib/utils";

import { useErrorMessage } from "./use-error-message";

export function LoginForm() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const next = safeNextPath(useSearchParams().get("next"));
  const queryClient = useQueryClient();
  const toMessage = useErrorMessage();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // Already signed in (e.g. opened /login on a second tab)? Go straight in.
  const me = useQuery({ queryKey: authKeys.me, queryFn: ({ signal }) => getMe(signal), retry: false });
  useEffect(() => {
    if (me.data) router.replace(next);
  }, [me.data, next, router]);

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      queryClient.setQueryData(authKeys.me, data);
      router.replace(next);
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password) return;
    mutation.mutate({ username: username.trim(), password });
  }

  const error = mutation.error ? toMessage(mutation.error) : null;

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      <div className="flex flex-col gap-2">
        <Label htmlFor="username">{t("username")}</Label>
        <Input
          id="username"
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="password">{t("password")}</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      {error && (
        <div
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm"
        >
          <p>{error.message}</p>
          {error.errorId && (
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {tc("errorId", { id: error.errorId })}
            </p>
          )}
        </div>
      )}
      <Button
        type="submit"
        disabled={mutation.isPending || !username.trim() || !password}
        className="w-full"
      >
        {mutation.isPending ? t("submitting") : t("submit")}
      </Button>
    </form>
  );
}
