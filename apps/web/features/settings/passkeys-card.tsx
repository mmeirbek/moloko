"use client";

import type { PasskeyListOut, PasskeyOptionsOut, PasskeyOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { Check, Info, KeyRound, Pencil, Plus, Trash2, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { usePasskeyErrorMessage } from "@/features/auth/passkey-error";
import { ErrorState, LoadingState } from "@/features/system/query-state";
import {
  deletePasskey,
  listPasskeys,
  passkeyKeys,
  passkeyRegisterOptions,
  passkeyRegisterVerify,
  renamePasskey,
} from "@/lib/api/passkeys";
import { createPasskey, detectPasskeySupport, deviceName, PasskeyCeremonyError, type PasskeySupport } from "@/lib/webauthn";

const NAME_MAX = 64;

/**
 * Settings → System and data: passkeys, to sign in with Face ID / Touch ID instead of the
 * password. Adding and deleting one asks for the moloko password (a borrowed or stolen
 * session can neither add a way in nor remove the owner's); the password always keeps working.
 */
export function PasskeysCard() {
  const t = useTranslations("passkeys");
  const list = useQuery({ queryKey: passkeyKeys.list, queryFn: ({ signal }) => listPasskeys(signal) });
  const [support, setSupport] = useState<PasskeySupport | null>(null);
  useEffect(() => {
    let alive = true;
    void detectPasskeySupport().then((s) => alive && setSupport(s));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <Card data-testid="passkeys-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound /> {t("title")}
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {list.isPending && <LoadingState />}
        {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
        {list.data && <PasskeysBody data={list.data} support={support} />}
      </CardContent>
    </Card>
  );
}

function Note({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 border-2 border-dashed p-3 text-sm">
      <Info className="mt-0.5 text-muted-foreground" />
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  );
}

function PasskeysBody({ data, support }: { data: PasskeyListOut; support: PasskeySupport | null }) {
  const t = useTranslations("passkeys");
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<string | null>(null);
  const canAdd = data.enabled && support?.available === true && data.passkeys.length < data.max_passkeys;

  return (
    <>
      {!data.enabled && (
        <Note>
          <p>{t("disabled")}</p>
          <p className="text-xs text-muted-foreground">{t("disabledHint")}</p>
        </Note>
      )}
      {data.enabled && support && !support.available && (
        <Note>
          <p>{t("unsupported")}</p>
        </Note>
      )}

      {data.passkeys.length > 0 ? (
        <ul className="flex flex-col divide-y-2" data-testid="passkey-list">
          {data.passkeys.map((p) => (
            <PasskeyRow key={p.id} passkey={p} />
          ))}
        </ul>
      ) : (
        data.enabled && <p className="text-sm text-muted-foreground">{t("empty")}</p>
      )}

      {added && (
        <p role="status" className="text-sm text-grass">
          {t("added", { name: added })}
        </p>
      )}

      {data.enabled && data.passkeys.length >= data.max_passkeys && (
        <p className="text-xs text-muted-foreground">{t("limit", { max: data.max_passkeys })}</p>
      )}

      {adding ? (
        <AddPasskeyForm
          onDone={(name) => {
            setAdding(false);
            setAdded(name);
          }}
          onCancel={() => setAdding(false)}
        />
      ) : (
        canAdd && (
          <div>
            <Button
              variant="outline"
              onClick={() => {
                setAdded(null);
                setAdding(true);
              }}
            >
              <Plus /> {t("add")}
            </Button>
          </div>
        )
      )}
      {data.rp_id && <p className="text-xs text-muted-foreground">{t("site", { site: data.rp_id })}</p>}
    </>
  );
}

function PasskeyRow({ passkey }: { passkey: PasskeyOut }) {
  const t = useTranslations("passkeys");
  const tc = useTranslations("common");
  const format = useFormatter();
  const toMessage = usePasskeyErrorMessage();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(passkey.name);
  const [deleting, setDeleting] = useState(false);

  const rename = useMutation({
    mutationFn: () => renamePasskey(passkey.id, name.trim()),
    onSuccess: (updated) => {
      queryClient.setQueryData<PasskeyListOut>(passkeyKeys.list, (old) =>
        old ? { ...old, passkeys: old.passkeys.map((p) => (p.id === updated.id ? updated : p)) } : old,
      );
      setEditing(false);
    },
  });

  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    rename.mutate();
  }

  return (
    <li className="flex flex-col gap-2 py-3" data-testid="passkey-row">
      {editing ? (
        <form className="flex flex-col gap-2" onSubmit={submit}>
          <Label htmlFor={`passkey-name-${passkey.id}`}>{t("name")}</Label>
          <div className="flex gap-2">
            <Input
              id={`passkey-name-${passkey.id}`}
              value={name}
              maxLength={NAME_MAX}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              className="min-w-0 flex-1"
            />
            <Button type="submit" size="icon" aria-label={t("saveName")} disabled={rename.isPending || !name.trim()}>
              <Check />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={tc("cancel")}
              onClick={() => {
                setName(passkey.name);
                setEditing(false);
                rename.reset();
              }}
            >
              <X />
            </Button>
          </div>
          {rename.isError && (
            <p role="alert" className="text-sm text-destructive">
              {toMessage(rename.error).message}
            </p>
          )}
        </form>
      ) : (
        <div className="flex items-start gap-3">
          <KeyRound className="mt-0.5 shrink-0 text-muted-foreground" />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <span className="truncate font-semibold">{passkey.name}</span>
              {passkey.backed_up && (
                <span className="border-2 px-1.5 text-xs text-muted-foreground" title={t("syncedHint")}>
                  {t("synced")}
                </span>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("createdAt", { date: date(passkey.created_at) })}
              {" · "}
              {passkey.last_used_at ? t("lastUsed", { date: date(passkey.last_used_at) }) : t("neverUsed")}
            </p>
          </div>
          <div className="flex shrink-0 gap-1">
            <Button variant="ghost" size="icon" aria-label={t("rename", { name: passkey.name })} onClick={() => setEditing(true)}>
              <Pencil />
            </Button>
            <Button variant="ghost" size="icon" aria-label={t("delete", { name: passkey.name })} onClick={() => setDeleting(true)}>
              <Trash2 />
            </Button>
          </div>
        </div>
      )}
      <DeletePasskeyDialog passkey={passkey} open={deleting} onClose={() => setDeleting(false)} />
    </li>
  );
}

function DeletePasskeyDialog({ passkey, open, onClose }: { passkey: PasskeyOut; open: boolean; onClose: () => void }) {
  const t = useTranslations("passkeys");
  const tc = useTranslations("common");
  const toMessage = usePasskeyErrorMessage();
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const remove = useMutation({
    mutationFn: () => deletePasskey(passkey.id, password),
    onSuccess: () => {
      setPassword("");
      onClose();
      void queryClient.invalidateQueries({ queryKey: passkeyKeys.list });
    },
    onError: () => setPassword(""),
  });

  function close() {
    setPassword("");
    remove.reset();
    onClose();
  }

  const titleId = `passkey-delete-${passkey.id}`;
  return (
    <Dialog open={open} onClose={close} labelledBy={titleId} data-testid="passkey-delete-dialog">
      <form
        className="flex flex-col gap-4 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (password) remove.mutate();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <p id={titleId} className="font-pixel text-lg">
            {t("deleteTitle", { name: passkey.name })}
          </p>
          <p className="text-sm text-muted-foreground">{t("deleteDescription")}</p>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${titleId}-password`}>{t("password")}</Label>
          <Input
            id={`${titleId}-password`}
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {remove.isError && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(remove.error).message}
          </p>
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={close}>
            {tc("cancel")}
          </Button>
          <Button type="submit" variant="destructive" disabled={!password || remove.isPending}>
            <Trash2 /> {t("deleteConfirm")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

type AddStep = { kind: "form" } | { kind: "device"; options: PasskeyOptionsOut; until: number; name: string };

/**
 * Adding a passkey: the password first (checked by the server, which then issues a challenge
 * bound to this session), then the device's own prompt (Face ID / Touch ID). If the browser
 * did not show the prompt — Safari only does inside a click — or the owner closed it, a button
 * asks again with the same, still valid challenge.
 */
function AddPasskeyForm({ onDone, onCancel }: { onDone: (name: string) => void; onCancel: () => void }) {
  const t = useTranslations("passkeys");
  const tc = useTranslations("common");
  const toMessage = usePasskeyErrorMessage();
  const queryClient = useQueryClient();
  const [name, setName] = useState(() => (typeof navigator === "undefined" ? "" : deviceName(navigator.userAgent)));
  const [password, setPassword] = useState("");
  const [step, setStep] = useState<AddStep>({ kind: "form" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function ask(options: PasskeyOptionsOut, until: number, chosenName: string) {
    setStep({ kind: "device", options, until, name: chosenName });
    let credential: Record<string, unknown>;
    try {
      credential = await createPasskey(options.options);
    } catch (e) {
      setBusy(false);
      // Closed or not shown: offer the button (still the same valid challenge).
      if (!(e instanceof PasskeyCeremonyError && e.kind === "cancelled")) setError(e);
      return;
    }
    try {
      const saved = await passkeyRegisterVerify(credential, chosenName);
      queryClient.setQueryData<PasskeyListOut>(passkeyKeys.list, (old) =>
        old ? { ...old, passkeys: [...old.passkeys, saved] } : old,
      );
      void queryClient.invalidateQueries({ queryKey: passkeyKeys.list });
      onDone(saved.name);
    } catch (e) {
      // The challenge is used up now: start again with the password.
      setError(e);
      setStep({ kind: "form" });
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password || !name.trim()) return;
    setBusy(true);
    setError(null);
    const chosenName = name.trim();
    let options: PasskeyOptionsOut;
    try {
      options = await passkeyRegisterOptions(password);
    } catch (err) {
      setBusy(false);
      setError(err);
      return;
    } finally {
      setPassword("");
    }
    await ask(options, Date.now() + (options.expires_in_seconds - 10) * 1000, chosenName);
  }

  function retry() {
    if (step.kind !== "device") return;
    setError(null);
    if (step.until <= Date.now()) {
      setStep({ kind: "form" });
      return;
    }
    setBusy(true);
    void ask(step.options, step.until, step.name);
  }

  return (
    <form className="flex flex-col gap-3 border-2 p-4" onSubmit={submit} data-testid="passkey-add">
      <p className="font-pixel text-lg">{t("addTitle")}</p>
      {step.kind === "form" ? (
        <>
          <div className="flex flex-col gap-1.5 sm:max-w-sm">
            <Label htmlFor="passkey-new-name">{t("name")}</Label>
            <Input
              id="passkey-new-name"
              value={name}
              maxLength={NAME_MAX}
              onChange={(e) => setName(e.target.value)}
              aria-describedby="passkey-new-name-hint"
            />
            <p id="passkey-new-name-hint" className="text-xs text-muted-foreground">
              {t("nameHint")}
            </p>
          </div>
          <div className="flex flex-col gap-1.5 sm:max-w-sm">
            <Label htmlFor="passkey-password">{t("password")}</Label>
            <Input
              id="passkey-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby="passkey-password-hint"
            />
            <p id="passkey-password-hint" className="text-xs text-muted-foreground">
              {t("passwordHint")}
            </p>
          </div>
        </>
      ) : (
        <p className="text-sm">{busy ? t("devicePrompt") : t("deviceRetry")}</p>
      )}
      {error !== null && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(error).message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {step.kind === "form" ? (
          <Button type="submit" disabled={busy || !password || !name.trim()}>
            <KeyRound /> {busy ? t("creating") : t("create")}
          </Button>
        ) : (
          <Button type="button" onClick={retry} disabled={busy}>
            <KeyRound /> {busy ? t("creating") : t("createAgain")}
          </Button>
        )}
        <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
          {tc("cancel")}
        </Button>
      </div>
    </form>
  );
}
