"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { LogoMark } from "@/components/brand/logo";
import { usePendingApprovalCount } from "@/features/approvals/approvals-badge";
import { cn } from "@/lib/utils";

import { IslandPanel } from "./island-panel";
import { useActiveAgentCount } from "./status";

/**
 * The site's "Dynamic Island": a small black pill at the top centre that says what needs the
 * owner (approvals) and how many agents work; a click opens the island — the office, approvals
 * and the saved agents to drag in. Escape, a click outside or the pill closes it. Desktop only;
 * phones have the tab bar, and the Mac app shows the same island at the notch (/island).
 */
export function DynamicIsland() {
  const t = useTranslations("island");
  const [open, setOpen] = useState(false);
  const pending = usePendingApprovalCount();
  const active = useActiveAgentCount();
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onPointer = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onPointer);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <div
      // Centred over the page content (right of the sidebar), not over the whole window.
      className="dark pointer-events-none fixed top-3 right-0 left-(--sidebar-width) z-30 hidden justify-center px-4 md:flex sidebar-collapsed:left-16"
      data-testid="dynamic-island"
    >
      <div
        ref={root}
        className={cn(
          "pointer-events-auto flex max-h-[calc(100dvh-1.5rem)] flex-col bg-[#05070f] text-foreground pixel-frame [--frame:#2a3460]",
          open && "w-full max-w-5xl",
        )}
      >
        <button
          type="button"
          aria-expanded={open}
          aria-controls="island-panel"
          aria-label={open ? t("collapse") : t("expand")}
          onClick={() => setOpen((v) => !v)}
          className="flex h-10 items-center gap-3 self-center px-3 text-sm outline-none focus-visible:bg-accent"
        >
          <LogoMark size="sm" className="size-6" />
          {active > 0 ? (
            <span className="flex items-center gap-2">
              <span aria-hidden className="size-2 bg-grass" />
              {t("working", { count: active })}
            </span>
          ) : (
            <span className="text-muted-foreground">{t("quiet")}</span>
          )}
          {pending > 0 && (
            <span className="bg-amber-400 px-1.5 text-xs text-amber-950" data-testid="island-pending">
              {t("pendingCount", { count: pending })}
            </span>
          )}
        </button>
        {open && (
          <div id="island-panel" className="flex h-[min(40rem,calc(100dvh-5rem))] min-h-0 border-t-2 border-[#2a3460]">
            <IslandPanel className="w-full" onNavigate={() => setOpen(false)} />
          </div>
        )}
      </div>
    </div>
  );
}
