import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import type { CowMood } from "./art";
import { PixelCow } from "./pixel-cow";

/** "Nothing here yet" with the cow. */
export function EmptyState({
  title,
  hint,
  mood = "idle",
  action,
  className,
  size = 72,
}: {
  title: string;
  hint?: string;
  mood?: CowMood;
  action?: ReactNode;
  className?: string;
  size?: number;
}) {
  return (
    <div
      className={cn("flex flex-col items-center gap-2 px-4 py-8 text-center", className)}
      data-testid="empty-state"
    >
      <PixelCow mood={mood} size={size} interactive />
      <p className="font-pixel text-base">{title}</p>
      {hint && <p className="max-w-sm text-sm text-muted-foreground">{hint}</p>}
      {action}
    </div>
  );
}
