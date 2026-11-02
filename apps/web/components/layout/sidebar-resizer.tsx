"use client";

import { useTranslations } from "next-intl";
import { useRef, type KeyboardEvent, type PointerEvent } from "react";

import { SIDEBAR_COLLAPSE_AT, SIDEBAR_DEFAULT, SIDEBAR_MAX, SIDEBAR_MIN } from "./sidebar-prefs";
import { applyWidth, currentWidth, setCollapsed, useSidebarCollapsed, useSidebarWidth } from "./use-sidebar";

const STEP = 16; // px per arrow key; Shift = ×4

/**
 * The sidebar's right edge: drag to resize (like Claude's sidebar), drag far left to fold it
 * into the icon rail, double-click for the default width. A focusable separator, so the
 * keyboard can do the same: ←/→ resize, Home/End min/max, Enter folds or unfolds.
 */
export function SidebarResizer({ controls }: { controls: string }) {
  const t = useTranslations("nav");
  const collapsed = useSidebarCollapsed();
  const width = useSidebarWidth();
  const drag = useRef<{ x: number; width: number; moved: boolean } | null>(null);

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, width: collapsed ? SIDEBAR_COLLAPSE_AT : currentWidth(), moved: false };
    document.documentElement.dataset.resizing = "";
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const d = drag.current;
    if (!d) return;
    const next = d.width + e.clientX - d.x;
    d.moved ||= Math.abs(e.clientX - d.x) > 2;
    if (next < SIDEBAR_COLLAPSE_AT) {
      if (!collapsed) setCollapsed(true);
      return;
    }
    if (collapsed) setCollapsed(false);
    applyWidth(next);
  }

  function onPointerUp(e: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    delete document.documentElement.dataset.resizing;
    if (drag.current.moved && !collapsed) applyWidth(currentWidth(), true);
    drag.current = null;
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const step = e.shiftKey ? STEP * 4 : STEP;
    const keys: Record<string, () => void> = {
      ArrowLeft: () => (collapsed ? undefined : width - step < SIDEBAR_MIN ? setCollapsed(true) : applyWidth(width - step, true)),
      ArrowRight: () => (collapsed ? setCollapsed(false) : applyWidth(width + step, true)),
      Home: () => applyWidth(SIDEBAR_MIN, true),
      End: () => applyWidth(SIDEBAR_MAX, true),
      Enter: () => setCollapsed(!collapsed),
    };
    const action = keys[e.key];
    if (!action) return;
    e.preventDefault();
    action();
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-controls={controls}
      aria-label={t("resize")}
      aria-valuemin={SIDEBAR_MIN}
      aria-valuemax={SIDEBAR_MAX}
      aria-valuenow={collapsed ? SIDEBAR_MIN : width}
      aria-valuetext={collapsed ? t("collapsed") : t("widthPx", { px: width })}
      title={t("resizeHint")}
      tabIndex={0}
      data-testid="sidebar-resizer"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onDoubleClick={() => {
        setCollapsed(false);
        applyWidth(SIDEBAR_DEFAULT, true);
      }}
      onKeyDown={onKeyDown}
      // A wide, invisible grab area over the border; the line lights up on hover, focus and drag.
      className="group absolute inset-y-0 -right-1.5 z-20 w-3 cursor-col-resize touch-none outline-none"
    >
      <span className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-transparent transition-colors group-hover:bg-ring/60 group-focus-visible:bg-ring group-active:bg-ring" />
    </div>
  );
}
