"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { ExternalLink } from "@/components/icons";
import { ApprovalCard } from "@/features/approvals/approval-card";
import { usePendingApprovals } from "@/features/approvals/approvals-view";
import { AgentPalette } from "@/features/office/agent-palette";
import { OfficeView, type OfficeMode } from "@/features/office/office-view";
import { cn } from "@/lib/utils";

/**
 * The island's content (site and Mac notch app): the office — agents' or subagents' — on a
 * small map, the approvals waiting for the owner, and the saved agents to drag into the office.
 */
export function IslandPanel({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  const t = useTranslations("island");
  const [mode, setMode] = useState<OfficeMode>("agents");
  const { pending } = usePendingApprovals();

  return (
    <div className={cn("flex min-h-0 flex-col gap-4 p-4", className)}>
      <header className="flex items-center gap-3">
        <div role="group" aria-label={t("officeSwitch")} className="inline-flex gap-1">
          {(["agents", "subagents"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={cn(
                "h-9 px-3 text-sm",
                mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              {t(m)}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        {pending.length === 0 && <span className="text-xs text-muted-foreground">{t("noApprovals")}</span>}
        <Link
          href={mode === "agents" ? "/office/agents" : "/office/subagents"}
          onClick={onNavigate}
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
        >
          {t("openOffice")} <ExternalLink className="size-3" />
        </Link>
      </header>

      {/* Approvals take a column only while something waits; otherwise the map has the whole width. */}
      <div className={cn("grid min-h-0 flex-1 grid-cols-1 gap-5", pending.length > 0 && "sm:grid-cols-[minmax(0,1fr)_15rem]")}>
        <OfficeView compact initialMode="agents" mode={mode} onModeChange={setMode} />
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

      <AgentPalette variant="strip" onAdded={() => setMode("agents")} />
    </div>
  );
}
