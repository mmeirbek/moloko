"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { Copy, Save } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { saveAgentAsTemplate } from "@/lib/api/agents";

/**
 * «Save as template»: the agent's configuration (not its memory or history) becomes an own
 * template in the office palette, next to the built-in ones.
 */
export function SaveTemplateButton({ agent }: { agent: { id: string; name: string } }) {
  const t = useTranslations("agents.saveTemplate");
  const tc = useTranslations("common");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(agent.name);
  const [saved, setSaved] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => saveAgentAsTemplate(agent.id, { name: name.trim() || null }),
    onSuccess: (template) => {
      void queryClient.invalidateQueries({ queryKey: ["agents", "templates"] });
      setSaved(template.name);
      setOpen(false);
    },
  });

  return (
    <div className="flex flex-col items-start gap-1.5">
      <Button
        variant="outline"
        onClick={() => {
          setName(agent.name);
          setSaved(null);
          save.reset();
          setOpen(true);
        }}
        data-testid="save-as-template"
      >
        <Copy /> {t("button")}
      </Button>
      {saved && (
        <p role="status" className="text-sm text-grass">
          {t("saved", { name: saved })}{" "}
          <Link href="/office/agents" className="underline underline-offset-2">
            {t("openOffice")}
          </Link>
        </p>
      )}
      <Dialog open={open} onClose={() => setOpen(false)} labelledBy="save-template-title" data-testid="save-template-dialog">
        <form
          className="flex flex-col gap-4 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) save.mutate();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <p id="save-template-title" className="font-pixel text-lg">
              {t("title")}
            </p>
            <p className="text-sm text-muted-foreground">{t("description")}</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="save-template-name">{t("name")}</Label>
            <Input
              id="save-template-name"
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={Boolean(save.error)}
              autoFocus
            />
          </div>
          {save.error && (
            <p role="alert" className="text-sm text-destructive">
              {toMessage(save.error).message}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" disabled={!name.trim() || save.isPending} data-testid="save-template-submit">
              <Save /> {t("save")}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
