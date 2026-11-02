"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { ExternalLink } from "@/components/icons";
import { ApprovalCard } from "@/features/approvals/approval-card";
import { usePendingApprovals } from "@/features/approvals/approvals-view";
import { AgentPalette } from "@/features/office/agent-palette";
import { OfficeView } from "@/features/office/office-view";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { IslandTask, type TaskTarget } from "./island-task";

/**
 * The island's content (the Mac notch app): the office on a small map, the approvals waiting
 * for the owner, and the saved agents to drag into the office.
 */
export function IslandPanel({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  const t = useTranslations("island");
  const [target, setTarget] = useState<TaskTarget>("orchestrator");
  const { pending } = usePendingApprovals();
  const agents = useRealtimeStore((s) => s.agents);
  // A click on a character on the map makes it the task's addressee (persistent agents and the Orchestrator).
  const pick = (id: string | null) => {
    const agent = id ? agents[id] : undefined;
    if (agent?.agent_type === "autonomous") setTarget(agent.id);
    else if (agent?.agent_type === "orchestrator") setTarget("orchestrator");
  };

  return (
    <div className={cn("flex min-h-0 flex-col gap-3 p-3", className)}>
      <header className="flex items-center gap-3">
        <h2 className="font-pixel text-lg">{t("agents")}</h2>
        <span className="flex-1" />
        {pending.length === 0 && <span className="text-xs text-muted-foreground">{t("noApprovals")}</span>}
        <Link
          href="/office/agents"
          onClick={onNavigate}
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
        >
          {t("openOffice")} <ExternalLink className="size-3" />
        </Link>
      </header>

      {/* Approvals take a column only while something waits; otherwise the map has the whole width. */}
      <div className={cn("grid min-h-0 flex-1 grid-cols-1 gap-5", pending.length > 0 && "sm:grid-cols-[minmax(0,1fr)_15rem]")}>
        <OfficeView compact onSelect={pick} />
        {pending.length > 0 && (
          <section aria-labelledby="island-approvals" className="flex min-h-0 flex-col gap-3">
            <h2 id="island-approvals" className="flex items-center gap-2 font-pixel text-lg">
              {t("approvals")}
              <span className="bg-amber-400 px-1.5 font-sans text-xs text-amber-950">{pending.length}</span>
            </h2>
            <div className="flex min-h-0 flex-col gap-4 overflow-y-auto p-(--px)" data-testid="island-approvals">
              {pending.map((a) => (
                <ApprovalCard key={a.id} approval={a} compact />
              ))}
            </div>
          </section>
        )}
      </div>

      <IslandTask target={target} onTargetChange={setTarget} className="px-(--px)" />
      <AgentPalette variant="strip" />
    </div>
  );
}
