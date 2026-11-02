"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ConfirmProvider } from "@/components/ui/confirm";
import { WalkingCow } from "@/features/mascot/pixel-cow";
import { authKeys, getMe } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import { RealtimeProvider } from "@/lib/realtime/provider";

import { postToNative } from "./bridge";
import { IslandBridge } from "./island-bridge";
import { IslandPanel } from "./island-panel";

/** /island: the island alone, full window — for the Mac notch app (also works in a browser). */
export function IslandShell() {
  const t = useTranslations("common");
  const router = useRouter();
  const me = useQuery({ queryKey: authKeys.me, queryFn: ({ signal }) => getMe(signal) });
  const signedOut = me.error instanceof ApiError && me.error.isUnauthenticated;

  useEffect(() => {
    if (!signedOut) return;
    postToNative({ type: "status", pendingApprovals: 0, activeAgents: 0, signedIn: false });
    router.replace("/login?next=/island");
  }, [signedOut, router]);

  if (!me.data) {
    return (
      <div className="dark flex h-dvh flex-col items-center justify-center gap-3 bg-[#05070f] text-sm text-muted-foreground">
        <WalkingCow size={64} />
        <span>{t("loading")}</span>
      </div>
    );
  }
  return (
    <RealtimeProvider>
      <ConfirmProvider>
        <IslandBridge />
        <main className="dark flex h-dvh flex-col bg-[#05070f] text-foreground">
          <IslandPanel className="flex-1" />
        </main>
      </ConfirmProvider>
    </RealtimeProvider>
  );
}
