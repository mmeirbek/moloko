import { cn } from "@/lib/utils";

/** A soft placeholder that shimmers while its content loads (like Claude's lists). */
export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "block rounded-md bg-[linear-gradient(90deg,var(--color-muted)_0%,var(--color-accent)_50%,var(--color-muted)_100%)] bg-[length:200%_100%] motion-safe:animate-[shimmer_1.6s_ease-in-out_infinite]",
        className,
      )}
    />
  );
}

/** Rows of placeholders: a list that is on its way (avatar + two lines each). */
export function SkeletonRows({ rows = 4, avatar = true, className }: { rows?: number; avatar?: boolean; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3", className)} aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-2.5">
          {avatar && <Skeleton className="size-6 shrink-0 rounded-full" />}
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <Skeleton className="h-3 w-4/5" />
            <Skeleton className="h-2.5 w-2/5" />
          </div>
        </div>
      ))}
    </div>
  );
}
