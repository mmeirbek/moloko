"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A modal on the native <dialog> (showModal): the browser traps focus, closes on Escape and
 * makes the page behind it inert. A click on the backdrop closes it too. `sheet` slides up
 * from the bottom edge (phone menus); `center` is a regular dialog.
 */
export function Dialog({
  open,
  onClose,
  labelledBy,
  variant = "center",
  className,
  children,
  ...rest
}: {
  open: boolean;
  onClose: () => void;
  labelledBy?: string;
  variant?: "center" | "sheet";
  className?: string;
  children: ReactNode;
  "data-testid"?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      // The backdrop belongs to the <dialog> element itself; the content fills its box.
      onClick={(e) => e.target === e.currentTarget && onClose()}
      aria-labelledby={labelledBy}
      className={cn(
        // A soft window over the dimmed, slightly blurred page; on phones a sheet from the bottom.
        "overflow-visible bg-card p-0 text-card-foreground shadow-2xl backdrop:bg-black/40 backdrop:backdrop-blur-[2px]",
        variant === "sheet"
          ? "mx-0 mt-auto mb-0 w-full max-w-none rounded-t-2xl border-t pb-[env(safe-area-inset-bottom)]"
          : "m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl pixel-frame",
        className,
      )}
      {...rest}
    >
      {open && children}
    </dialog>
  );
}
