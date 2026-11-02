import { cn } from "@/lib/utils";

/*
 * The owner's moloko logo: the cow-in-a-meadow tile and the "moloko" wordmark, both cut
 * from the owner's image (assets/brand/logo-source.jpg) by scripts/make-brand.py — the
 * favicon and PWA icons come from the same script. This is the only place the mark is composed.
 */
const SIZES = {
  sm: { mark: "size-7", word: "h-4" },
  md: { mark: "size-8", word: "h-5" },
  lg: { mark: "size-16", word: "h-10" },
} as const;

type LogoSize = keyof typeof SIZES;

export function LogoMark({ size = "md", className }: { size?: LogoSize; className?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a small static brand image, no optimisation needed
    <img src="/brand/logo-tile.png" alt="" width={64} height={64} className={cn("shrink-0", SIZES[size].mark, className)} />
  );
}

/** The wordmark in the logo's own lettering, tinted with the theme's text colour (CSS mask). */
export function Wordmark({ size = "md", className }: { size?: LogoSize; className?: string }) {
  return <span role="img" aria-label="moloko" className={cn("wordmark", SIZES[size].word, className)} />;
}

export function Logo({
  size = "md",
  className,
  showWordmark = true,
}: {
  size?: LogoSize;
  className?: string;
  showWordmark?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center", size === "lg" ? "gap-4" : "gap-2.5", className)}>
      <LogoMark size={size} />
      {showWordmark && <Wordmark size={size} />}
    </span>
  );
}
