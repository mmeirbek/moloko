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
        // A pixel window: notched frame and a hard shadow; the page behind dims without blur.
        "overflow-visible bg-card p-0 text-card-foreground backdrop:bg-black/50",
        variant === "sheet"
          ? "mx-0 mt-auto mb-0 w-full max-w-none border-t-(length:--px) border-(--frame) pb-[env(safe-area-inset-bottom)]"
          : "m-auto w-[min(32rem,calc(100vw-2rem))] pixel-frame",
        className,
      )}
      {...rest}
    >
      {open && children}
    </dialog>
  );
}
