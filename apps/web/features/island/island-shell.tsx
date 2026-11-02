"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ConfirmProvider } from "@/components/ui/confirm";
import { usePendingApprovalCount } from "@/features/approvals/approvals-badge";
import { WalkingCow } from "@/features/mascot/pixel-cow";
import { authKeys, getMe } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import { RealtimeProvider } from "@/lib/realtime/provider";

import { IslandPanel } from "./island-panel";
import { useActiveAgentCount } from "./status";

type Bridge = { postMessage: (message: unknown) => void };

/** The Mac notch app's web view (apps/mac-island), when this page runs inside it. */
function nativeBridge(): Bridge | undefined {
  return (window as unknown as { webkit?: { messageHandlers?: { molokoIsland?: Bridge } } }).webkit?.messageHandlers
    ?.molokoIsland;
}

/**
 * Tells the notch app what to show on the collapsed pill: waiting approvals, working agents,
 * signed in. Contract with apps/mac-island: messages `{type: "status", …}`; the app sends the
 * window event `moloko-island` `{open}` when the panel opens or closes.
 */
function IslandBridge() {
  const queryClient = useQueryClient();
  const pendingApprovals = usePendingApprovalCount();
  const activeAgents = useActiveAgentCount();
  useEffect(() => {
    nativeBridge()?.postMessage({ type: "status", pendingApprovals, activeAgents, signedIn: true });
  }, [pendingApprovals, activeAgents]);
  useEffect(() => {
    const onIsland = (e: Event) => {
      if ((e as CustomEvent<{ open?: boolean }>).detail?.open) void queryClient.invalidateQueries();
    };
    window.addEventListener("moloko-island", onIsland);
    return () => window.removeEventListener("moloko-island", onIsland);
  }, [queryClient]);
  return null;
}

/** /island: the island alone, full window — for the Mac notch app (also works in a browser). */
export function IslandShell() {
  const t = useTranslations("common");
  const router = useRouter();
  const me = useQuery({ queryKey: authKeys.me, queryFn: ({ signal }) => getMe(signal) });
  const signedOut = me.error instanceof ApiError && me.error.isUnauthenticated;

  useEffect(() => {
    if (!signedOut) return;
    nativeBridge()?.postMessage({ type: "status", pendingApprovals: 0, activeAgents: 0, signedIn: false });
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
