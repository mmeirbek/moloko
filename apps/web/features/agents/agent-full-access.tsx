"use client";

import type { AgentOut } from "@moloko/shared-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";

import { KeyRound, ShieldAlert } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { agentKeys, setAgentFullAccess } from "@/lib/api/agents";
import { cn } from "@/lib/utils";

import { fullAccessBody } from "./agent-form-model";

/** «Полный доступ» next to an agent's name (agent page, agents list, office inspector). */
export function FullAccessBadge({ className }: { className?: string }) {
  const t = useTranslations("agents.fullAccess");
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 bg-destructive/15 px-2 py-0.5 text-xs font-medium whitespace-nowrap text-destructive",
        className,
      )}
      title={t("badgeHint")}
      data-testid="full-access-badge"
    >
      <ShieldAlert className="size-3.5" aria-hidden="true" />
      {t("badge")}
    </span>
  );
}

/**
 * The danger option in the agent form's autonomy section: what full access means, and the
 * switch. Turning it on asks for the moloko password in a dialog; turning it off does not.
 */
export function FullAccessOption({ agent, onChanged }: { agent: AgentOut; onChanged: (agent: AgentOut) => void }) {
  const t = useTranslations("agents.fullAccess");
  const format = useFormatter();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const on = agent.full_access === true;

  const applied = (result: AgentOut) => {
    queryClient.setQueryData(agentKeys.detail(result.id), result);
    void queryClient.invalidateQueries({ queryKey: agentKeys.all });
    onChanged(result);
  };
  const revoke = useMutation({
    mutationFn: () => setAgentFullAccess(agent.id, fullAccessBody(false)),
    onSuccess: applied,
  });

  return (
    <div
      className={cn("flex flex-col gap-2 border-2 border-destructive/50 p-3 text-sm", on && "bg-destructive/10")}
      data-testid="full-access-option"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 font-medium text-destructive">
          <ShieldAlert className="size-4" aria-hidden="true" />
          {t("title")}
        </p>
        {on && <FullAccessBadge />}
      </div>
      <p className="text-xs text-muted-foreground">{t("body")}</p>
      <ul className="flex list-disc flex-col gap-0.5 pl-5 text-xs text-muted-foreground">
        <li>{t("stillApplies")}</li>
        <li>{t("exceptions")}</li>
      </ul>
      {on ? (
        <div className="flex flex-wrap items-center gap-3">
          <p role="status" className="text-xs">
            {agent.full_access_since
              ? t("onSince", {
                  date: format.dateTime(new Date(agent.full_access_since), { dateStyle: "medium", timeStyle: "short" }),
                })
              : t("on")}
          </p>
          <Button type="button" variant="outline" size="sm" disabled={revoke.isPending} onClick={() => revoke.mutate()}>
            {t("turnOff")}
          </Button>
        </div>
      ) : (
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-destructive/50 text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => setOpen(true)}
          >
            <KeyRound /> {t("turnOn")}
          </Button>
        </div>
      )}
      {revoke.error && (
        <p role="alert" className="text-xs text-destructive">
          {toMessage(revoke.error).message}
        </p>
      )}
      {/* Outside the agent form in the DOM (a form inside a form is invalid); mounted only
          while open, so it never renders on the server. */}
      {open &&
        createPortal(
          <Dialog open onClose={() => setOpen(false)} labelledBy="full-access-title" data-testid="full-access-dialog">
            <GrantForm
              agent={agent}
              onCancel={() => setOpen(false)}
              onDone={(result) => {
                setOpen(false);
                applied(result);
              }}
            />
          </Dialog>,
          document.body,
        )}
    </div>
  );
}

function GrantForm({
  agent,
  onCancel,
  onDone,
}: {
  agent: AgentOut;
  onCancel: () => void;
  onDone: (agent: AgentOut) => void;
}) {
  const t = useTranslations("agents.fullAccess");
  const tc = useTranslations("common");
  const toMessage = useErrorMessage();
  const uid = useId();
  const [password, setPassword] = useState("");
  const grant = useMutation({
    mutationFn: () => setAgentFullAccess(agent.id, fullAccessBody(true, password)),
    onSuccess: onDone,
    onError: () => setPassword(""),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    e.stopPropagation(); // React bubbles through the portal: never submit the agent form
    if (password) grant.mutate();
  }

  return (
    <form className="flex flex-col gap-4 p-5" onSubmit={submit}>
      <div className="flex flex-col gap-1.5">
        <p id="full-access-title" className="flex items-center gap-2 font-pixel text-lg text-destructive">
          <ShieldAlert className="size-4" aria-hidden="true" />
          {t("dialogTitle", { name: agent.name })}
        </p>
        <p className="text-sm">{t("body")}</p>
        <p className="text-sm text-muted-foreground">{t("stillApplies")}</p>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${uid}-password`}>{t("password")}</Label>
        <Input
          id={`${uid}-password`}
          type="password"
          autoComplete="current-password"
          required
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-describedby={`${uid}-hint`}
        />
        <p id={`${uid}-hint`} className="text-xs text-muted-foreground">
          {t("passwordHint")}
        </p>
      </div>
      {grant.error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(grant.error).message}
        </p>
      )}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="outline" onClick={onCancel}>
          {tc("cancel")}
        </Button>
        <Button type="submit" variant="destructive" disabled={!password || grant.isPending}>
          {t("confirm")}
        </Button>
      </div>
    </form>
  );
}
