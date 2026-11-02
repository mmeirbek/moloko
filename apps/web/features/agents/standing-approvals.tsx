"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";

import { ShieldCheck, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { useStandingWhat } from "@/features/approvals/standing-text";
import { agentKeys, removeStandingApproval } from "@/lib/api/agents";

type Rule = { id: string; tool: string; scope?: string; since?: string };

export function standingRules(permissions: Record<string, unknown> | null | undefined): Rule[] {
  const value = permissions?.always;
  return Array.isArray(value) ? (value as Rule[]).filter((r) => r && typeof r.id === "string") : [];
}

/** «Разрешено без вопросов»: what the owner allowed this agent with «Одобрить и больше не
 *  спрашивать», each with «Убрать» (the action asks again). Hidden while there is none. */
export function StandingApprovals({ agentId, permissions }: { agentId: string; permissions: Record<string, unknown> | null | undefined }) {
  const t = useTranslations("agents.standing");
  const standingWhat = useStandingWhat();
  const format = useFormatter();
  const confirm = useConfirm();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: (ruleId: string) => removeStandingApproval(agentId, ruleId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: agentKeys.all }),
  });
  const rules = standingRules(permissions);
  if (rules.length === 0) return null;
  return (
    <section className="flex flex-col gap-2 bg-card p-3 text-sm pixel-frame" data-testid="standing-approvals">
      <h2 className="inline-flex items-center gap-1.5 font-medium">
        <ShieldCheck className="size-4 text-sky" aria-hidden /> {t("title")}
      </h2>
      <p className="text-xs text-muted-foreground">{t("hint")}</p>
      <ul className="flex flex-col divide-y-2">
        {rules.map((rule) => {
          const what = standingWhat(rule.tool, [rule.scope ?? ""]);
          return (
            <li key={rule.id} className="flex items-center justify-between gap-2 py-1.5">
              <span className="min-w-0">
                <span className="break-words">{what}</span>
                {rule.since && (
                  <span className="text-xs text-muted-foreground">
                    {" · "}
                    {t("since", { date: format.dateTime(new Date(rule.since), { dateStyle: "medium" }) })}
                  </span>
                )}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={remove.isPending}
                onClick={async () => {
                  if (await confirm({ title: t("removeConfirm", { what }), confirmLabel: t("remove") })) remove.mutate(rule.id);
                }}
              >
                <X /> {t("remove")}
              </Button>
            </li>
          );
        })}
      </ul>
      {remove.error && (
        <p role="alert" className="text-xs text-destructive">
          {toMessage(remove.error).message}
        </p>
      )}
    </section>
  );
}
