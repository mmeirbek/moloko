// Adapted from shadcn/ui (MIT) — see THIRD_PARTY_NOTICES.md.
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "flex h-10 w-full bg-card px-3 text-sm placeholder:text-muted-foreground pixel-frame pixel-sunken focus-visible:outline-none focus-visible:[--frame-color:var(--color-ring)] disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
