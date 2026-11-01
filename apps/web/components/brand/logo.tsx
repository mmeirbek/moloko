"use client";

import { COW } from "@/features/mascot/art";
import { CowSvg } from "@/features/mascot/pixel-cow";
import { cn } from "@/lib/utils";

/*
 * The owner's moloko logo: the cow-in-a-meadow tile (redrawn as 32×32 pixel art in
 * features/mascot/cow-art.json → "logo") and the pixel wordmark. This is the only place
 * the mark is composed; favicon and PWA icons come from the same art (scripts/make-icons.mjs).
 */
export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
  return <CowSvg rows={COW.logo.rows} palette={COW.logo.palette} width={size} height={size} className={className} />;
}

export function Logo({ className, showWordmark = true }: { className?: string; showWordmark?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark className="size-8" />
      {showWordmark && (
        <span className="font-pixel text-xl font-bold tracking-tight lowercase [text-shadow:2px_2px_0_rgb(0_0_0/0.18)] dark:text-[#f6efdc] dark:[text-shadow:2px_2px_0_#000]">
          moloko
        </span>
      )}
    </span>
  );
}
