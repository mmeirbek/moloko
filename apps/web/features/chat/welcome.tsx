"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/features/mascot/empty-state";
import { PixelCow } from "@/features/mascot/pixel-cow";
import { authKeys, getMe } from "@/lib/api/auth";

/** The top of an empty chat: a greeting — or, without any AI model, the one thing to do first. */
export function ChatWelcome({ noModels }: { noModels: boolean }) {
  const t = useTranslations("chat");
  const me = useQuery({ queryKey: authKeys.me, queryFn: ({ signal }) => getMe(signal) });
  const name = me.data ? me.data.user.display_name || me.data.user.username : "";

  if (noModels) {
    return (
      <EmptyState
        title={t("noModels")}
        hint={t("noModelsHint")}
        mood="sad"
        className="py-2"
        action={
          <Button asChild className="mt-2">
            <Link href="/settings#ai">{t("openSettings")}</Link>
          </Button>
        }
      />
    );
  }
  return (
    <div className="flex flex-col items-center gap-3 text-center">
      <PixelCow mood="happy" size={64} interactive />
      <h2 className="font-pixel text-2xl sm:text-3xl">{name ? t("greeting", { name }) : t("greetingNoName")}</h2>
      <p className="max-w-md text-sm text-muted-foreground">{t("emptyHint")}</p>
    </div>
  );
}
