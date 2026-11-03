import { useId } from "react";

/**
 * A glass that fills with milk, then empties, while something takes a while (app start, a long
 * load). Our own drawing (assets/MANIFEST.md); still when the owner prefers less motion.
 */
export function MilkGlass({ size = 56, className }: { size?: number; className?: string }) {
  const inside = useId();
  return (
    <svg viewBox="0 0 48 64" width={(size * 48) / 64} height={size} aria-hidden="true" focusable="false" className={className}>
      <defs>
        <clipPath id={inside}>
          <path d="M10 14 L38 14 L35 58 Q34.6 61 31.6 61 L16.4 61 Q13.4 61 13 58 Z" />
        </clipPath>
      </defs>
      {/* a drop falls in */}
      <circle cx="24" cy="4" r="2.4" fill="#f2e6c9" className="motion-safe:animate-[milk-drop_1.8s_ease-in_infinite]" />
      <g clipPath={`url(#${inside})`}>
        {/* no style attribute (the CSP forbids inline styles): the start level is an SVG offset */}
        <g transform="translate(0 20)">
        <g className="motion-safe:animate-[milk-fill_3.6s_ease-in-out_infinite]">
          <g className="motion-safe:animate-[milk-wave_1.4s_linear_infinite]">
            <path
              d="M0 20 Q6 17 12 20 T24 20 T36 20 T48 20 T60 20 T72 20 T84 20 T96 20 L96 70 L0 70 Z"
              fill="#f7f1e1"
            />
          </g>
        </g>
        </g>
      </g>
      <path
        d="M10 14 L38 14 L35 58 Q34.6 61 31.6 61 L16.4 61 Q13.4 61 13 58 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
        opacity="0.55"
      />
      <path d="M15 20 L16.4 52" stroke="#ffffff" strokeWidth="1.6" strokeLinecap="round" opacity="0.5" />
    </svg>
  );
}
