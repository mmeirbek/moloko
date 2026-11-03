"use client";

import { useId, useMemo, type ReactNode } from "react";

import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { assignLooks, lookOf, type Accessory, type Animal, type Expression, type Look } from "./agent-looks";

/*
 * Agent faces: an animal, an accessory, an expression on a soft round backdrop — our own flat
 * drawings in a 64×64 box (assets/MANIFEST.md). Each animal says where its eyes, the top of its
 * head and its mouth are, so every accessory fits every animal.
 */

const INK = "#1f1f1f";

interface Face {
  eyeY: number;
  eyeDX: number;
  topY: number;
  mouthY: number | null;
  /** Eyes on a dark patch are drawn light. */
  lightEyes?: boolean;
  /** Eyes always get a white (frog, raccoon). */
  sclera?: boolean;
  body: ReactNode;
}

const FACES: Record<Animal, Face> = {
  cow: {
    eyeY: 33,
    eyeDX: 7,
    topY: 19,
    mouthY: null,
    body: (
      <>
        <path d="M19 21 L22 10 L27 19 Z M45 21 L42 10 L37 19 Z" fill="#e9d9b5" />
        <ellipse cx="13" cy="30" rx="6" ry="3.5" fill="#d8d2c6" transform="rotate(-20 13 30)" />
        <ellipse cx="51" cy="30" rx="6" ry="3.5" fill="#d8d2c6" transform="rotate(20 51 30)" />
        <ellipse cx="32" cy="36" rx="17" ry="17" fill="#fbf8f1" />
        <ellipse cx="23" cy="27" rx="6" ry="4.5" fill="#2b2b2b" />
        <ellipse cx="32" cy="46" rx="11" ry="6.5" fill="#f4b3b3" />
        <ellipse cx="28" cy="46" rx="1.6" ry="2.2" fill="#b56f6f" />
        <ellipse cx="36" cy="46" rx="1.6" ry="2.2" fill="#b56f6f" />
      </>
    ),
  },
  cat: {
    eyeY: 34,
    eyeDX: 7,
    topY: 21,
    mouthY: 45,
    body: (
      <>
        <path d="M15 28 L19 9 L30 20 Z M49 28 L45 9 L34 20 Z" fill="#f2a65a" />
        <path d="M18 24 L20 14 L26 20 Z M46 24 L44 14 L38 20 Z" fill="#f6c3c0" />
        <ellipse cx="32" cy="37" rx="18" ry="16" fill="#f2a65a" />
        <path d="M28 22 L29 27 M32 21 L32 26 M36 22 L35 27" stroke="#c9743a" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M30 40 L34 40 L32 42.5 Z" fill="#e8838f" />
        <path d="M21 42 L12 40 M21 44 L12 45 M43 42 L52 40 M43 44 L52 45" stroke="#7a4a22" strokeWidth="1" strokeLinecap="round" />
      </>
    ),
  },
  dog: {
    eyeY: 32,
    eyeDX: 7,
    topY: 18,
    mouthY: 47,
    body: (
      <>
        <ellipse cx="32" cy="35" rx="16" ry="17" fill="#c98d5a" />
        <ellipse cx="15" cy="36" rx="6" ry="11" fill="#7a4f2e" transform="rotate(15 15 36)" />
        <ellipse cx="49" cy="36" rx="6" ry="11" fill="#7a4f2e" transform="rotate(-15 49 36)" />
        <ellipse cx="32" cy="44" rx="9" ry="7" fill="#e8c39b" />
        <ellipse cx="32" cy="40.5" rx="3.2" ry="2.4" fill="#2b2b2b" />
        <rect x="29.5" y="48" width="5" height="5" rx="2.5" fill="#ef7b8b" />
      </>
    ),
  },
  frog: {
    eyeY: 25,
    eyeDX: 9,
    topY: 18,
    mouthY: 46,
    sclera: true,
    body: (
      <>
        <circle cx="23" cy="25" r="7.5" fill="#7cc36e" />
        <circle cx="41" cy="25" r="7.5" fill="#7cc36e" />
        <ellipse cx="32" cy="40" rx="20" ry="15" fill="#7cc36e" />
        <circle cx="19" cy="44" r="3" fill="#f2a1a1" opacity="0.6" />
        <circle cx="45" cy="44" r="3" fill="#f2a1a1" opacity="0.6" />
      </>
    ),
  },
  raccoon: {
    eyeY: 34,
    eyeDX: 7,
    topY: 21,
    mouthY: 48,
    sclera: true,
    body: (
      <>
        <circle cx="18" cy="23" r="6" fill="#9aa0a6" />
        <circle cx="46" cy="23" r="6" fill="#9aa0a6" />
        <circle cx="18" cy="23" r="3" fill="#4a4f55" />
        <circle cx="46" cy="23" r="3" fill="#4a4f55" />
        <ellipse cx="32" cy="37" rx="18" ry="16" fill="#9aa0a6" />
        <rect x="13" y="29" width="38" height="10" rx="5" fill="#3d4146" />
        <ellipse cx="32" cy="45" rx="8" ry="6" fill="#e9eaec" />
        <ellipse cx="32" cy="42" rx="2.6" ry="1.9" fill="#2b2b2b" />
      </>
    ),
  },
  penguin: {
    eyeY: 34,
    eyeDX: 6,
    topY: 18,
    mouthY: null,
    body: (
      <>
        <circle cx="32" cy="36" r="18" fill="#2b2d33" />
        <ellipse cx="32" cy="39" rx="13" ry="12" fill="#f5f5f5" />
        <path d="M27.5 41 L36.5 41 L32 47 Z" fill="#f2a33a" />
        <circle cx="22" cy="42" r="2.4" fill="#f2a1a1" opacity="0.7" />
        <circle cx="42" cy="42" r="2.4" fill="#f2a1a1" opacity="0.7" />
      </>
    ),
  },
  fox: {
    eyeY: 34,
    eyeDX: 7,
    topY: 22,
    mouthY: 51,
    body: (
      <>
        <path d="M12 31 L17 9 L29 22 Z M52 31 L47 9 L35 22 Z" fill="#e8833a" />
        <path d="M15 17 L17 9 L21 13 Z M49 17 L47 9 L43 13 Z" fill="#3a2a22" />
        <ellipse cx="32" cy="37" rx="18" ry="15" fill="#e8833a" />
        <path d="M14 37 Q20 50 32 53 Q44 50 50 37 Q41 43 32 44 Q23 43 14 37 Z" fill="#fff4e6" />
        <ellipse cx="32" cy="46" rx="2.6" ry="2" fill="#2b2b2b" />
      </>
    ),
  },
  bear: {
    eyeY: 34,
    eyeDX: 7,
    topY: 19,
    mouthY: 49,
    body: (
      <>
        <circle cx="17" cy="22" r="6.5" fill="#8b5e3c" />
        <circle cx="47" cy="22" r="6.5" fill="#8b5e3c" />
        <circle cx="17" cy="22" r="3.2" fill="#c99a72" />
        <circle cx="47" cy="22" r="3.2" fill="#c99a72" />
        <circle cx="32" cy="37" r="18" fill="#8b5e3c" />
        <ellipse cx="32" cy="45" rx="9" ry="7" fill="#c99a72" />
        <ellipse cx="32" cy="42" rx="3" ry="2.2" fill="#2b2b2b" />
      </>
    ),
  },
  owl: {
    eyeY: 34,
    eyeDX: 7,
    topY: 20,
    mouthY: null,
    body: (
      <>
        <path d="M16 25 L18 12 L27 21 Z M48 25 L46 12 L37 21 Z" fill="#8a6d4e" />
        <ellipse cx="32" cy="37" rx="18" ry="17" fill="#8a6d4e" />
        <circle cx="25" cy="34" r="7.5" fill="#f3e6c8" />
        <circle cx="39" cy="34" r="7.5" fill="#f3e6c8" />
        <path d="M29.5 40 L34.5 40 L32 45.5 Z" fill="#e8a33a" />
        <path d="M24 49 Q28 52 32 49 Q36 52 40 49" stroke="#6b5139" strokeWidth="1.4" fill="none" />
      </>
    ),
  },
  panda: {
    eyeY: 35,
    eyeDX: 7,
    topY: 19,
    mouthY: 47,
    lightEyes: true,
    body: (
      <>
        <circle cx="18" cy="22" r="6" fill="#2b2b2b" />
        <circle cx="46" cy="22" r="6" fill="#2b2b2b" />
        <circle cx="32" cy="37" r="18" fill="#f7f7f5" />
        <ellipse cx="25" cy="35" rx="5" ry="6.2" fill="#2b2b2b" transform="rotate(20 25 35)" />
        <ellipse cx="39" cy="35" rx="5" ry="6.2" fill="#2b2b2b" transform="rotate(-20 39 35)" />
        <ellipse cx="32" cy="42.5" rx="2.6" ry="1.9" fill="#2b2b2b" />
      </>
    ),
  },
  pig: {
    eyeY: 33,
    eyeDX: 7,
    topY: 19,
    mouthY: 50,
    body: (
      <>
        <path d="M15 26 L18 12 L28 20 Z M49 26 L46 12 L36 20 Z" fill="#ec8fa2" />
        <circle cx="32" cy="37" r="18" fill="#f4a7b5" />
        <ellipse cx="32" cy="43" rx="8" ry="5.5" fill="#ec8fa2" />
        <ellipse cx="29.5" cy="43" rx="1.3" ry="2" fill="#b95d6e" />
        <ellipse cx="34.5" cy="43" rx="1.3" ry="2" fill="#b95d6e" />
      </>
    ),
  },
  bunny: {
    eyeY: 37,
    eyeDX: 6.5,
    topY: 24,
    mouthY: 48,
    body: (
      <>
        <ellipse cx="24" cy="15" rx="4.6" ry="13" fill="#ecebef" />
        <ellipse cx="40" cy="15" rx="4.6" ry="13" fill="#ecebef" />
        <ellipse cx="24" cy="16" rx="2" ry="9" fill="#f3b8c4" />
        <ellipse cx="40" cy="16" rx="2" ry="9" fill="#f3b8c4" />
        <circle cx="32" cy="39" r="17" fill="#ecebef" />
        <ellipse cx="32" cy="43" rx="2.2" ry="1.6" fill="#ef8fa0" />
        <rect x="30.4" y="46.5" width="3.2" height="4" rx="0.8" fill="#ffffff" stroke="#c9c7cf" strokeWidth="0.6" />
        <circle cx="22" cy="44" r="2.6" fill="#f3b8c4" opacity="0.6" />
        <circle cx="42" cy="44" r="2.6" fill="#f3b8c4" opacity="0.6" />
      </>
    ),
  },
};

function Eyes({ face, expression }: { face: Face; expression: Expression }) {
  const color = face.lightEyes ? "#ffffff" : INK;
  return (
    <>
      {[-1, 1].map((side) => {
        const x = 32 + side * face.eyeDX;
        const y = face.eyeY;
        const white = face.sclera || expression === "side";
        return (
          <g key={side}>
            {white && <circle cx={x} cy={y} r="3.4" fill="#ffffff" stroke={INK} strokeWidth="0.6" />}
            {expression === "happy" && (
              <path d={`M${x - 3} ${y + 1} Q${x} ${y - 3.5} ${x + 3} ${y + 1}`} stroke={white ? INK : color} strokeWidth="2" strokeLinecap="round" fill="none" />
            )}
            {expression === "smug" && (
              <>
                <circle cx={x} cy={y + 0.8} r="1.7" fill={white ? INK : color} />
                <path d={`M${x - 3.2} ${y - 0.6} L${x + 3.2} ${y - 1.6}`} stroke={white ? INK : color} strokeWidth="1.8" strokeLinecap="round" />
              </>
            )}
            {expression === "side" && <circle cx={x + 1.4} cy={y + 0.4} r="1.7" fill={INK} />}
            {expression === "dot" && <circle cx={x} cy={y} r={white ? 1.8 : 2.3} fill={white ? INK : color} />}
          </g>
        );
      })}
    </>
  );
}

function Mouth({ y, expression }: { y: number; expression: Expression }) {
  const stroke = { stroke: "#3a2a22", strokeWidth: 1.7, strokeLinecap: "round" as const, fill: "none" };
  if (expression === "happy") return <path d={`M28 ${y} Q32 ${y + 4} 36 ${y}`} {...stroke} />;
  if (expression === "smug") return <path d={`M28 ${y + 1} Q33 ${y + 2.2} 37 ${y - 1.5}`} {...stroke} />;
  if (expression === "side") return <path d={`M29 ${y + 1} L35 ${y + 1}`} {...stroke} />;
  return <circle cx="32" cy={y + 1} r="1.6" {...stroke} />;
}

function Wear({ face, accessory }: { face: Face; accessory: Accessory }) {
  const { eyeY: y, eyeDX: dx, topY: top } = face;
  switch (accessory) {
    case "shades":
      return (
        <g>
          <rect x={32 - dx - 6} y={y - 3.6} width="12" height="7.2" rx="2.6" fill="#141414" />
          <rect x={32 + dx - 6} y={y - 3.6} width="12" height="7.2" rx="2.6" fill="#141414" />
          <path d={`M${32 - dx + 6} ${y - 1.5} L${32 + dx - 6} ${y - 1.5}`} stroke="#141414" strokeWidth="2" />
          <path d={`M${32 - dx - 3} ${y - 1.5} L${32 - dx - 0.5} ${y - 1.5} M${32 + dx - 3} ${y - 1.5} L${32 + dx - 0.5} ${y - 1.5}`} stroke="#ffffff" strokeWidth="1.2" strokeLinecap="round" opacity="0.85" />
        </g>
      );
    case "glasses":
      return (
        <g fill="#ffffff" fillOpacity="0.25" stroke="#222222" strokeWidth="1.6">
          <circle cx={32 - dx} cy={y} r="4.8" />
          <circle cx={32 + dx} cy={y} r="4.8" />
          <path d={`M${32 - dx + 4.8} ${y} L${32 + dx - 4.8} ${y}`} fill="none" />
        </g>
      );
    case "cap":
      return (
        <g>
          <path d={`M15 ${top + 7} Q32 ${top - 11} 49 ${top + 7} Z`} fill="#e5484d" />
          <path d={`M40 ${top + 5} Q56 ${top + 3} 59 ${top + 8} L42 ${top + 9} Z`} fill="#c2353a" />
          <circle cx="32" cy={top - 3} r="1.8" fill="#c2353a" />
        </g>
      );
    case "beanie":
      return (
        <g>
          <path d={`M13 ${top + 9} Q32 ${top - 13} 51 ${top + 9} Z`} fill="#2f80ed" />
          <rect x="13" y={top + 5} width="38" height="5.5" rx="2.5" fill="#1f5fbf" />
          <circle cx="32" cy={top - 9} r="3.8" fill="#ffffff" />
        </g>
      );
    case "headphones":
      return (
        <g>
          <path d={`M14 ${y + 2} Q13 ${top - 7} 32 ${top - 7} Q51 ${top - 7} 50 ${y + 2}`} stroke="#2b2b2b" strokeWidth="3" fill="none" strokeLinecap="round" />
          <rect x="9" y={y - 4} width="8" height="12" rx="3.5" fill="#7c5cff" />
          <rect x="47" y={y - 4} width="8" height="12" rx="3.5" fill="#7c5cff" />
        </g>
      );
    case "crown":
      return (
        <g>
          <path
            d={`M22 ${top + 2} L22 ${top - 8} L27 ${top - 3} L32 ${top - 11} L37 ${top - 3} L42 ${top - 8} L42 ${top + 2} Z`}
            fill="#f5c542"
            stroke="#c99a1d"
            strokeWidth="1"
            strokeLinejoin="round"
          />
          <circle cx="32" cy={top - 2} r="1.6" fill="#e5484d" />
        </g>
      );
    case "party":
      return (
        <g>
          <path d={`M23 ${top + 4} L39 ${top + 2} L35 ${top - 15} Z`} fill="#7c5cff" />
          <path d={`M26 ${top - 1} L38 ${top - 3} M30 ${top - 7} L37 ${top - 8}`} stroke="#ffd166" strokeWidth="1.6" />
          <circle cx="35" cy={top - 16} r="2.6" fill="#ffd166" />
        </g>
      );
    case "bowtie":
      return (
        <g>
          <path d="M24 53 L24 61 L32 57 Z M40 53 L40 61 L32 57 Z" fill="#e5484d" />
          <circle cx="32" cy="57" r="2" fill="#c2353a" />
        </g>
      );
  }
}

/** The picture of a look. Decorative: the agent's name is always shown next to it. */
export function AvatarArt({ look, size = 28, className }: { look: Look; size?: number; className?: string }) {
  const clip = useId();
  const face = FACES[look.animal];
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      className={cn("shrink-0 rounded-full", className)}
      data-avatar={`${look.animal}-${look.accessory}-${look.expression}`}
    >
      <defs>
        <clipPath id={clip}>
          <circle cx="32" cy="32" r="32" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clip})`}>
        <rect width="64" height="64" fill={look.backdrop} />
        {face.body}
        <Eyes face={face} expression={look.expression} />
        {face.mouthY !== null && <Mouth y={face.mouthY} expression={look.expression} />}
        <Wear face={face} accessory={look.accessory} />
      </g>
    </svg>
  );
}

/** The faces of the whole office, recomputed when its agents change. */
export function useAgentLooks(): Map<string, Look> {
  const agents = useRealtimeStore((s) => s.agents);
  return useMemo(() => assignLooks(Object.values(agents)), [agents]);
}

/** An agent's face (also for one the office no longer lists). */
export function AgentAvatar({ agentId, size = 28, className }: { agentId: string | null | undefined; size?: number; className?: string }) {
  const looks = useAgentLooks();
  const look = agentId ? (looks.get(agentId) ?? lookOf(agentId)) : null;
  if (!look)
    return (
      <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true" className={cn("shrink-0 text-muted", className)}>
        <circle cx="32" cy="32" r="32" fill="currentColor" />
      </svg>
    );
  return <AvatarArt look={look} size={size} className={className} />;
}
