"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { OctagonX, Play } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { startEngine, stopAll, systemState, systemStateKey, taskKeys } from "@/lib/api/agents";

export function KillSwitchCard() {
  const t = useTranslations("system");
  const confirm = useConfirm();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const state = useQuery({ queryKey: systemStateKey, queryFn: ({ signal }) => systemState(signal) });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: systemStateKey });
    void queryClient.invalidateQueries({ queryKey: taskKeys.all });
  };
  const stop = useMutation({ mutationFn: stopAll, onSuccess: refresh });
  const start = useMutation({ mutationFn: startEngine, onSuccess: refresh });
  const stopped = state.data?.engine_stopped;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("engineTitle")}</CardTitle>
        <CardDescription>
          {stopped ? t("engineStopped") : t("engineRunning", { count: state.data?.active_tasks ?? 0 })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {stopped ? (
          <Button onClick={() => start.mutate()} disabled={start.isPending}>
            <Play /> {t("startEngine")}
          </Button>
        ) : (
          <Button
            variant="destructive"
            disabled={stop.isPending}
            onClick={async () => {
              if (await confirm({ title: t("confirmStopAll"), confirmLabel: t("stopAll"), destructive: true })) stop.mutate();
            }}
          >
            <OctagonX /> {t("stopAll")}
          </Button>
        )}
        {stop.data && <p className="mt-2 text-sm text-muted-foreground">{t("stoppedCount", { count: stop.data.cancelled_tasks })}</p>}
        {/* A failed emergency stop must never look like a successful one. */}
        {(stop.error ?? start.error) && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {toMessage(stop.error ?? start.error).message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
