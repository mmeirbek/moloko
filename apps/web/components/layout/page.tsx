import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A reading page (lists, forms, settings): one centred column of the same width everywhere,
 * so nothing hugs the left edge of a wide screen and the title does not jump between pages.
 * The offices and the chat use the whole width and do not use this.
 */
export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("mx-auto w-full max-w-4xl", className)} data-testid="page">
      {children}
    </div>
  );
}
