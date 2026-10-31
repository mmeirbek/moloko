import { cn } from "@/lib/utils";

/*
 * PLACEHOLDER brand mark. The owner's real logo (pixel-art cow + "moloko" wordmark)
 * will be uploaded as public/brand/logo.png; when it lands, swap the icon below for
 * crops of that file. This is the only place the brand mark is drawn.
 */
function PlaceholderIcon({ className }: { className?: string }) {
  // 16×16 pixel scene in the logo's colours: sky, cloud, grass, soil.
  return (
    <svg
      viewBox="0 0 16 16"
      className={cn("pixelated", className)}
      shapeRendering="crispEdges"
      aria-hidden="true"
    >
      <rect x="0" y="0" width="16" height="16" fill="#f6efdc" />
      <rect x="1" y="1" width="14" height="9" fill="#4aa8e8" />
      <rect x="3" y="3" width="4" height="1" fill="#ffffff" />
      <rect x="4" y="2" width="2" height="1" fill="#ffffff" />
      <rect x="10" y="4" width="3" height="1" fill="#ffffff" />
      <rect x="1" y="10" width="14" height="3" fill="#5bbf4a" />
      <rect x="1" y="13" width="14" height="2" fill="#6b4a2f" />
      <rect x="5" y="7" width="6" height="3" fill="#ffffff" />
      <rect x="6" y="8" width="2" height="1" fill="#3b2a24" />
      <rect x="11" y="6" width="2" height="2" fill="#ffffff" />
      <rect x="5" y="10" width="1" height="1" fill="#3b2a24" />
      <rect x="10" y="10" width="1" height="1" fill="#3b2a24" />
    </svg>
  );
}

export function Logo({ className, showWordmark = true }: { className?: string; showWordmark?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <PlaceholderIcon className="size-8 rounded-sm" />
      {showWordmark && (
        <span className="font-mono text-xl font-extrabold tracking-tight lowercase">moloko</span>
      )}
    </span>
  );
}
