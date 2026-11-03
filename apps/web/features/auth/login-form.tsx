"use client";

import type { MeResponse } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { KeyRound } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authKeys, getMe, login } from "@/lib/api/auth";
import { safeNextPath } from "@/lib/utils";

import { usePasskeyErrorMessage } from "./passkey-error";
import { usePasskeyLogin } from "./passkey-login";

export function LoginForm() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const next = safeNextPath(useSearchParams().get("next"));
  const queryClient = useQueryClient();
  const toMessage = usePasskeyErrorMessage();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // Already signed in (e.g. opened /login on a second tab)? Go straight in.
  const me = useQuery({ queryKey: authKeys.me, queryFn: ({ signal }) => getMe(signal), retry: false });
  useEffect(() => {
    if (me.data) router.replace(next);
  }, [me.data, next, router]);

  const signedIn = useCallback(
    (data: MeResponse) => {
      queryClient.setQueryData(authKeys.me, data);
      router.replace(next);
    },
    [queryClient, router, next],
  );

  const mutation = useMutation({ mutationFn: login, onSuccess: signedIn });
  // Face ID / Touch ID: offered in the username field's autofill and as a button; the
  // password stays as the fallback.
  const passkey = usePasskeyLogin(signedIn);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password) return;
    passkey.clearError();
    mutation.mutate({ username: username.trim(), password });
  }

  const failure = passkey.error ?? mutation.error;
  const error = failure ? toMessage(failure) : null;
  const busy = mutation.isPending || passkey.pending;

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      <div className="flex flex-col gap-2">
        <Label htmlFor="username">{t("username")}</Label>
        <Input
          id="username"
          name="username"
          // "webauthn": the browser may offer saved passkeys right here (conditional UI).
          autoComplete="username webauthn"
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
          className="border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm"
        >
          <p>{error.message}</p>
          {error.errorId && (
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {tc("errorId", { id: error.errorId })}
            </p>
          )}
        </div>
      )}
      <Button type="submit" disabled={busy || !username.trim() || !password} className="w-full">
        {mutation.isPending ? t("submitting") : t("submit")}
      </Button>
      {passkey.enabled && (
        <>
          <div className="flex items-center gap-3 text-xs text-muted-foreground" aria-hidden="true">
            <span className="h-0.5 flex-1 bg-border" />
            {t("or")}
            <span className="h-0.5 flex-1 bg-border" />
          </div>
          <Button
            type="button"
            variant="outline"
            className="w-full"
            disabled={busy}
            onClick={() => {
              mutation.reset();
              passkey.signIn();
            }}
            data-testid="passkey-login"
          >
            <KeyRound />
            {passkey.pending ? t("passkeyPending") : t("passkey")}
          </Button>
          <p className="text-xs text-muted-foreground">{t("passkeyHint")}</p>
        </>
      )}
    </form>
  );
}
