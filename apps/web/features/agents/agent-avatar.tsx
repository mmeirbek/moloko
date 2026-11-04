"use client";

import { useId, useMemo, type ReactNode } from "react";

import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { assignLooks, lookOf, moodOf, type Accessory, type Animal, type Expression, type Look, type Mood } from "./agent-looks";

/*
 * Agent faces: an exotic animal (the moloko cow is the Orchestrator's), an accessory, an
 * expression on a soft round backdrop — our own flat drawings in a 64×64 box
 * (assets/MANIFEST.md). Each animal says where its eyes, the top of its head and its mouth are,
 * so every accessory and every mood fits every animal.
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
  amur_tiger: {
    eyeY: 34,
    eyeDX: 7.5,
    topY: 20,
    mouthY: 47,
    body: (
      <>
        <circle cx="17" cy="22" r="6" fill="#e8742c" />
        <circle cx="47" cy="22" r="6" fill="#e8742c" />
        <circle cx="17" cy="22" r="3" fill="#fff3e3" />
        <circle cx="47" cy="22" r="3" fill="#fff3e3" />
        <ellipse cx="32" cy="37" rx="19" ry="17" fill="#e8742c" />
        <path d="M13 40 Q18 53 32 54 Q46 53 51 40 Q42 46 32 45 Q22 46 13 40 Z" fill="#fff3e3" />
        <ellipse cx="32" cy="45" rx="7.5" ry="5.5" fill="#fff3e3" />
        <path d="M32 21 L32 28 M26.5 22.5 L28.5 27.5 M37.5 22.5 L35.5 27.5" stroke="#2b2b2b" strokeWidth="2" strokeLinecap="round" />
        <path d="M13.5 32 L20 34.5 M13.5 37.5 L19 38.5 M50.5 32 L44 34.5 M50.5 37.5 L45 38.5" stroke="#2b2b2b" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M29 41 L35 41 L32 44 Z" fill="#d1606a" />
      </>
    ),
  },
  snow_leopard: {
    eyeY: 34,
    eyeDX: 7,
    topY: 21,
    mouthY: 47,
    body: (
      <>
        <circle cx="18" cy="23" r="5.5" fill="#d9d6cf" />
        <circle cx="46" cy="23" r="5.5" fill="#d9d6cf" />
        <circle cx="18" cy="23" r="2.6" fill="#b9b4aa" />
        <circle cx="46" cy="23" r="2.6" fill="#b9b4aa" />
        <ellipse cx="32" cy="37" rx="18" ry="16" fill="#ece9e2" />
        <ellipse cx="32" cy="45" rx="8.5" ry="6" fill="#f8f7f3" />
        <g fill="none" stroke="#5a5a5a" strokeWidth="1.2">
          <circle cx="25" cy="25.5" r="2" />
          <circle cx="39" cy="25.5" r="2" />
          <circle cx="18.5" cy="33" r="1.8" />
          <circle cx="45.5" cy="33" r="1.8" />
        </g>
        <g fill="#5a5a5a">
          <circle cx="32" cy="23.5" r="1.4" />
          <circle cx="20" cy="40.5" r="1.2" />
          <circle cx="44" cy="40.5" r="1.2" />
        </g>
        <path d="M29.5 41.5 L34.5 41.5 L32 44 Z" fill="#e39aa0" />
      </>
    ),
  },
  pallas_cat: {
    eyeY: 35,
    eyeDX: 7,
    topY: 24,
    mouthY: 48.5,
    body: (
      <>
        <ellipse cx="13.5" cy="29" rx="5" ry="3.8" fill="#8d8278" />
        <ellipse cx="50.5" cy="29" rx="5" ry="3.8" fill="#8d8278" />
        <path d="M9 38 Q8 26 20 24 Q32 21 44 24 Q56 26 55 38 Q57 47 50 50 Q44 55 32 55 Q20 55 14 50 Q7 47 9 38 Z" fill="#a99e92" />
        <g fill="#5b5149">
          <circle cx="26" cy="27.5" r="1" />
          <circle cx="30" cy="26" r="1" />
          <circle cx="34" cy="26" r="1" />
          <circle cx="38" cy="27.5" r="1" />
        </g>
        <circle cx="25" cy="35" r="4.4" fill="#efe2b0" />
        <circle cx="39" cy="35" r="4.4" fill="#efe2b0" />
        <path d="M21 40 L15.5 44 M23 42.5 L18.5 47.5 M43 40 L48.5 44 M41 42.5 L45.5 47.5" stroke="#3d3530" strokeWidth="1.4" strokeLinecap="round" />
        <ellipse cx="32" cy="46.5" rx="7.5" ry="5" fill="#f1ece4" />
        <ellipse cx="32" cy="42.5" rx="2.2" ry="1.6" fill="#c77a7a" />
      </>
    ),
  },
  fennec_fox: {
    eyeY: 37,
    eyeDX: 6.5,
    topY: 27,
    mouthY: 50,
    body: (
      <>
        <path d="M8 35 L12 3 L28 24 Z M56 35 L52 3 L36 24 Z" fill="#ecc995" />
        <path d="M12.5 29 L14 10 L24 24 Z M51.5 29 L50 10 L40 24 Z" fill="#f2b8a8" />
        <ellipse cx="32" cy="39" rx="16.5" ry="14" fill="#f0d3a4" />
        <path d="M17.5 40 Q24 53 32 53.5 Q40 53 46.5 40 Q39 45.5 32 45.5 Q25 45.5 17.5 40 Z" fill="#fff6e8" />
        <ellipse cx="32" cy="46" rx="2.4" ry="1.8" fill="#2b2b2b" />
      </>
    ),
  },
  red_panda: {
    eyeY: 34,
    eyeDX: 7,
    topY: 21,
    mouthY: 48,
    body: (
      <>
        <circle cx="17" cy="22" r="6.5" fill="#f3efe9" />
        <circle cx="47" cy="22" r="6.5" fill="#f3efe9" />
        <circle cx="17" cy="22.5" r="4" fill="#a2401c" />
        <circle cx="47" cy="22.5" r="4" fill="#a2401c" />
        <ellipse cx="32" cy="37" rx="18" ry="16" fill="#c4521f" />
        <ellipse cx="24" cy="28" rx="3.2" ry="2" fill="#fbf6ee" />
        <ellipse cx="40" cy="28" rx="3.2" ry="2" fill="#fbf6ee" />
        <ellipse cx="18.5" cy="41" rx="4.5" ry="3.5" fill="#fbf6ee" />
        <ellipse cx="45.5" cy="41" rx="4.5" ry="3.5" fill="#fbf6ee" />
        <ellipse cx="32" cy="45" rx="9.5" ry="6.5" fill="#fbf6ee" />
        <path d="M25 37.5 Q23.5 43 25.5 49 M39 37.5 Q40.5 43 38.5 49" stroke="#7a2d12" strokeWidth="2.6" strokeLinecap="round" fill="none" />
        <ellipse cx="32" cy="42.5" rx="2.6" ry="1.8" fill="#2b2b2b" />
      </>
    ),
  },
  capybara: {
    eyeY: 29,
    eyeDX: 9,
    topY: 18,
    mouthY: 49.5,
    body: (
      <>
        <ellipse cx="18.5" cy="18.5" rx="3.6" ry="3" fill="#7a5a3e" />
        <ellipse cx="45.5" cy="18.5" rx="3.6" ry="3" fill="#7a5a3e" />
        <rect x="12" y="17" width="40" height="39" rx="16" fill="#a47b55" />
        <rect x="16.5" y="37" width="31" height="17" rx="8.5" fill="#8e6748" />
        <ellipse cx="26" cy="42.5" rx="1.7" ry="1.3" fill="#3b2a1d" />
        <ellipse cx="38" cy="42.5" rx="1.7" ry="1.3" fill="#3b2a1d" />
      </>
    ),
  },
  axolotl: {
    eyeY: 35,
    eyeDX: 9,
    topY: 25,
    mouthY: 44,
    body: (
      <>
        <path d="M14 31 L5 22 M13 36 L2.5 34 M14 41 L5 47 M50 31 L59 22 M51 36 L61.5 34 M50 41 L59 47" stroke="#e0607e" strokeWidth="3.4" strokeLinecap="round" />
        <ellipse cx="32" cy="38" rx="19.5" ry="15" fill="#f6b5c8" />
        <circle cx="19" cy="42" r="3" fill="#ef8fa8" opacity="0.7" />
        <circle cx="45" cy="42" r="3" fill="#ef8fa8" opacity="0.7" />
      </>
    ),
  },
  quokka: {
    eyeY: 34,
    eyeDX: 7,
    topY: 22,
    mouthY: 47,
    body: (
      <>
        <circle cx="19" cy="22" r="5" fill="#8c6a4c" />
        <circle cx="45" cy="22" r="5" fill="#8c6a4c" />
        <circle cx="19" cy="22" r="2.5" fill="#c9a27f" />
        <circle cx="45" cy="22" r="2.5" fill="#c9a27f" />
        <ellipse cx="32" cy="38" rx="17" ry="16" fill="#a9825c" />
        <ellipse cx="32" cy="45" rx="9.5" ry="6.5" fill="#c9a27f" />
        <ellipse cx="32" cy="41.5" rx="3" ry="2.2" fill="#2b2b2b" />
        <circle cx="21" cy="42" r="2.6" fill="#e9a3a3" opacity="0.55" />
        <circle cx="43" cy="42" r="2.6" fill="#e9a3a3" opacity="0.55" />
      </>
    ),
  },
  okapi: {
    eyeY: 33,
    eyeDX: 7,
    topY: 18,
    mouthY: null,
    sclera: true,
    body: (
      <>
        <rect x="27" y="12" width="3" height="7" rx="1.5" fill="#4a2c22" />
        <rect x="34" y="12" width="3" height="7" rx="1.5" fill="#4a2c22" />
        <ellipse cx="14" cy="25" rx="7.5" ry="4.5" fill="#4a2c22" transform="rotate(-25 14 25)" />
        <ellipse cx="50" cy="25" rx="7.5" ry="4.5" fill="#4a2c22" transform="rotate(25 50 25)" />
        <ellipse cx="32" cy="36" rx="14.5" ry="19" fill="#5a3628" />
        <path d="M18.5 37 Q19.5 55 32 56 Q44.5 55 45.5 37 Q39 44 32 44 Q25 44 18.5 37 Z" fill="#f1e6d6" />
        <ellipse cx="32" cy="50.5" rx="4" ry="2.5" fill="#2b2b2b" />
      </>
    ),
  },
  tarsier: {
    eyeY: 34,
    eyeDX: 8,
    topY: 21,
    mouthY: 49,
    body: (
      <>
        <ellipse cx="11" cy="22" rx="7" ry="9" fill="#b48a68" />
        <ellipse cx="53" cy="22" rx="7" ry="9" fill="#b48a68" />
        <ellipse cx="11" cy="22" rx="4" ry="6" fill="#e2b9a0" />
        <ellipse cx="53" cy="22" rx="4" ry="6" fill="#e2b9a0" />
        <circle cx="32" cy="38" r="17" fill="#c49a74" />
        <circle cx="24" cy="34" r="7.8" fill="#e8a43c" stroke="#6b4a2e" strokeWidth="1" />
        <circle cx="40" cy="34" r="7.8" fill="#e8a43c" stroke="#6b4a2e" strokeWidth="1" />
        <ellipse cx="32" cy="45" rx="1.6" ry="1.2" fill="#6b4a2e" />
      </>
    ),
  },
  ring_tailed_lemur: {
    eyeY: 34,
    eyeDX: 7,
    topY: 21,
    mouthY: null,
    lightEyes: true,
    body: (
      <>
        <path d="M12 27 L13 11 L24 21 Z M52 27 L51 11 L40 21 Z" fill="#8d8d8f" />
        <ellipse cx="32" cy="36" rx="18.5" ry="16" fill="#9a9a9c" />
        <ellipse cx="32" cy="38.5" rx="13" ry="14" fill="#f5f5f3" />
        <ellipse cx="25" cy="34" rx="4.6" ry="5.2" fill="#2b2b2b" transform="rotate(25 25 34)" />
        <ellipse cx="39" cy="34" rx="4.6" ry="5.2" fill="#2b2b2b" transform="rotate(-25 39 34)" />
        <path d="M28 40 L36 40 L32 51 Z" fill="#2b2b2b" />
      </>
    ),
  },
  malayan_tapir: {
    eyeY: 32,
    eyeDX: 7.5,
    topY: 20,
    mouthY: null,
    lightEyes: true,
    body: (
      <>
        <ellipse cx="17" cy="21" rx="5" ry="6" fill="#2b2b2b" stroke="#f4f4f4" strokeWidth="1.6" />
        <ellipse cx="47" cy="21" rx="5" ry="6" fill="#2b2b2b" stroke="#f4f4f4" strokeWidth="1.6" />
        <ellipse cx="32" cy="35" rx="17" ry="16" fill="#2f3033" />
        <path d="M25 41 Q24 55 32 56 Q40 55 39 41 Z" fill="#3b3c40" />
        <ellipse cx="32" cy="55" rx="5" ry="2.2" fill="#1f1f22" />
        <path d="M27.5 47 Q32 48.5 36.5 47 M27 51 Q32 52.5 37 51" stroke="#55565b" strokeWidth="1" fill="none" />
      </>
    ),
  },
  sea_otter: {
    eyeY: 35,
    eyeDX: 7,
    topY: 20,
    mouthY: 48,
    body: (
      <>
        <circle cx="16" cy="27" r="3.6" fill="#6e4b33" />
        <circle cx="48" cy="27" r="3.6" fill="#6e4b33" />
        <circle cx="32" cy="37" r="18" fill="#7b563b" />
        <ellipse cx="32" cy="38.5" rx="14" ry="13" fill="#e8dccb" />
        <ellipse cx="32" cy="45" rx="8" ry="5.5" fill="#f5efe6" />
        <ellipse cx="32" cy="42" rx="3" ry="2" fill="#2b2b2b" />
        <path d="M23 45 L13 43 M23 47 L14 48.5 M41 45 L51 43 M41 47 L50 48.5" stroke="#8a7a68" strokeWidth="1" strokeLinecap="round" />
      </>
    ),
  },
  atlantic_puffin: {
    eyeY: 33,
    eyeDX: 7,
    topY: 17,
    mouthY: null,
    body: (
      <>
        <circle cx="32" cy="34" r="19" fill="#222326" />
        <ellipse cx="32" cy="37" rx="15" ry="12" fill="#f2f2f0" />
        <circle cx="25" cy="33" r="3.2" fill="none" stroke="#e06a4a" strokeWidth="1.2" />
        <circle cx="39" cy="33" r="3.2" fill="none" stroke="#e06a4a" strokeWidth="1.2" />
        <path d="M25 39 L39 39 L32 56 Z" fill="#e8552e" />
        <path d="M25 39 L39 39 L37.6 42.5 L26.4 42.5 Z" fill="#5d6b78" />
        <path d="M26.4 42.5 L37.6 42.5 L36.8 44.6 L27.2 44.6 Z" fill="#f2c14e" />
        <path d="M29 47.5 L35 47.5 M30.3 51 L33.7 51" stroke="#b83b1d" strokeWidth="0.9" />
      </>
    ),
  },
  three_toed_sloth: {
    eyeY: 34,
    eyeDX: 8,
    topY: 19,
    mouthY: 46.5,
    lightEyes: true,
    body: (
      <>
        <circle cx="32" cy="36" r="19" fill="#9b8468" />
        <ellipse cx="32" cy="38" rx="14.5" ry="13.5" fill="#e9dcc4" />
        <ellipse cx="23" cy="34" rx="7.2" ry="3.8" fill="#4a3626" transform="rotate(15 23 34)" />
        <ellipse cx="41" cy="34" rx="7.2" ry="3.8" fill="#4a3626" transform="rotate(-15 41 34)" />
        <ellipse cx="32" cy="42" rx="2.6" ry="1.8" fill="#3a2a1e" />
      </>
    ),
  },
  platypus: {
    eyeY: 29,
    eyeDX: 7,
    topY: 17,
    mouthY: null,
    body: (
      <>
        <ellipse cx="32" cy="32" rx="17.5" ry="16" fill="#7a5537" />
        <ellipse cx="32" cy="47.5" rx="16.5" ry="8" fill="#3f4651" />
        <ellipse cx="32" cy="45.5" rx="12" ry="4.5" fill="#4f5866" />
        <ellipse cx="28" cy="44.5" rx="1.2" ry="0.8" fill="#23272e" />
        <ellipse cx="36" cy="44.5" rx="1.2" ry="0.8" fill="#23272e" />
      </>
    ),
  },
  barn_owl: {
    eyeY: 35,
    eyeDX: 7,
    topY: 18,
    mouthY: null,
    body: (
      <>
        <ellipse cx="32" cy="36" rx="19.5" ry="18.5" fill="#d9a35a" />
        <path d="M32 26 C26 16 12 20 14 34 C15 45 25 53 32 55 C39 53 49 45 50 34 C52 20 38 16 32 26 Z" fill="#fbf6ee" stroke="#c58e48" strokeWidth="1.2" />
        <path d="M30.5 40 L33.5 40 L32 45.5 Z" fill="#e6c9a8" />
      </>
    ),
  },
  saiga: {
    eyeY: 32,
    eyeDX: 7.5,
    topY: 19,
    mouthY: null,
    body: (
      <>
        <path d="M25.5 21 Q22 12 24.5 3 M38.5 21 Q42 12 39.5 3" stroke="#e8d6a8" strokeWidth="3.2" strokeLinecap="round" fill="none" />
        <path d="M22.6 15 L25.6 14.4 M22.6 10 L25.4 9.6 M41.4 15 L38.4 14.4 M41.4 10 L38.6 9.6" stroke="#b89f68" strokeWidth="1" />
        <ellipse cx="14" cy="28" rx="6.5" ry="3" fill="#c9a46e" transform="rotate(-20 14 28)" />
        <ellipse cx="50" cy="28" rx="6.5" ry="3" fill="#c9a46e" transform="rotate(20 50 28)" />
        <ellipse cx="32" cy="34" rx="14" ry="15" fill="#d4b07a" />
        <ellipse cx="32" cy="47" rx="10.5" ry="8.5" fill="#c79f69" />
        <path d="M23.5 43 Q32 38.5 40.5 43" stroke="#b08a56" strokeWidth="1.2" fill="none" />
        <ellipse cx="28" cy="50" rx="1.6" ry="2.1" fill="#5c4528" />
        <ellipse cx="36" cy="50" rx="1.6" ry="2.1" fill="#5c4528" />
      </>
    ),
  },
  mandrill: {
    eyeY: 33,
    eyeDX: 7.5,
    topY: 18,
    mouthY: null,
    body: (
      <>
        <circle cx="32" cy="36" r="19" fill="#6f6a3d" />
        <path d="M17 43 Q21 59 32 59 Q43 59 47 43 Z" fill="#f1e6b8" />
        <ellipse cx="23.5" cy="43" rx="6" ry="9" fill="#4a7fd1" />
        <ellipse cx="40.5" cy="43" rx="6" ry="9" fill="#4a7fd1" />
        <path d="M21 37 L22 50 M24 36.5 L25 50.5 M43 37 L42 50 M40 36.5 L39 50.5" stroke="#2f5ea8" strokeWidth="1" />
        <rect x="28.5" y="30" width="7" height="22" rx="3.5" fill="#d93b3b" />
        <ellipse cx="32" cy="51" rx="4.2" ry="2.6" fill="#e5484d" />
        <path d="M19.5 29.5 Q32 25 44.5 29.5" stroke="#3e3a20" strokeWidth="2.4" strokeLinecap="round" fill="none" />
      </>
    ),
  },
  emperor_tamarin: {
    eyeY: 34,
    eyeDX: 6,
    topY: 20,
    mouthY: null,
    lightEyes: true,
    body: (
      <>
        <circle cx="32" cy="36" r="18" fill="#5f5a57" />
        <ellipse cx="32" cy="37" rx="12" ry="13" fill="#2f2c2b" />
        <ellipse cx="32" cy="41" rx="2" ry="1.4" fill="#1a1a1a" />
        <ellipse cx="32" cy="49" rx="3" ry="2" fill="#e9e9e7" />
        <path d="M32 44 Q24 42.5 19 48 Q14 54 12 61 M32 44 Q40 42.5 45 48 Q50 54 52 61" stroke="#f7f7f5" strokeWidth="3.4" strokeLinecap="round" fill="none" />
      </>
    ),
  },
};

/** What the eyes and mouth show: the look's own expression, or how the agent feels now. */
type Shown = Expression | "wide" | "up" | "sad" | "closed";

function shownFor(base: Expression, mood: Mood): Shown {
  switch (mood) {
    case "happy":
      return "happy";
    case "sad":
      return "sad";
    case "thinking":
      return "up";
    case "waiting":
      return "wide";
    case "sleepy":
      return "closed";
    default:
      return base;
  }
}

function Eyes({ face, shown }: { face: Face; shown: Shown }) {
  const color = face.lightEyes ? "#ffffff" : INK;
  return (
    <>
      {[-1, 1].map((side) => {
        const x = 32 + side * face.eyeDX;
        const y = face.eyeY;
        const white = face.sclera || shown === "side" || shown === "wide" || shown === "up";
        const ink = white ? INK : color;
        return (
          <g key={side}>
            {white && <circle cx={x} cy={y} r={shown === "wide" ? 4 : 3.4} fill="#ffffff" stroke={INK} strokeWidth="0.6" />}
            {shown === "happy" && (
              <path d={`M${x - 3} ${y + 1} Q${x} ${y - 3.5} ${x + 3} ${y + 1}`} stroke={ink} strokeWidth="2" strokeLinecap="round" fill="none" />
            )}
            {shown === "smug" && (
              <>
                <circle cx={x} cy={y + 0.8} r="1.7" fill={ink} />
                <path d={`M${x - 3.2} ${y - 0.6} L${x + 3.2} ${y - 1.6}`} stroke={ink} strokeWidth="1.8" strokeLinecap="round" />
              </>
            )}
            {shown === "side" && <circle cx={x + 1.4} cy={y + 0.4} r="1.7" fill={INK} />}
            {shown === "dot" && <circle cx={x} cy={y} r={white ? 1.8 : 2.3} fill={ink} />}
            {shown === "wide" && <circle cx={x} cy={y} r="2" fill={INK} />}
            {shown === "up" && <circle cx={x - 0.9} cy={y - 1.5} r="1.6" fill={INK} />}
            {shown === "sad" && (
              <>
                <circle cx={x} cy={y + 0.8} r="1.8" fill={ink} />
                <path d={`M${x - side * 3.4} ${y - 3.6} L${x + side * 2.6} ${y - 2}`} stroke={ink} strokeWidth="1.6" strokeLinecap="round" />
              </>
            )}
            {shown === "closed" && (
              <path d={`M${x - 3} ${y} Q${x} ${y + 2.6} ${x + 3} ${y}`} stroke={ink} strokeWidth="1.8" strokeLinecap="round" fill="none" />
            )}
          </g>
        );
      })}
    </>
  );
}

function Mouth({ y, shown }: { y: number; shown: Shown }) {
  const stroke = { stroke: "#3a2a22", strokeWidth: 1.7, strokeLinecap: "round" as const, fill: "none" };
  if (shown === "happy") return <path d={`M27.5 ${y - 0.5} Q32 ${y + 5} 36.5 ${y - 0.5}`} {...stroke} />;
  if (shown === "smug") return <path d={`M28 ${y + 1} Q33 ${y + 2.2} 37 ${y - 1.5}`} {...stroke} />;
  if (shown === "side" || shown === "closed") return <path d={`M29 ${y + 1} L35 ${y + 1}`} {...stroke} />;
  if (shown === "sad") return <path d={`M28.5 ${y + 2.5} Q32 ${y - 1} 35.5 ${y + 2.5}`} {...stroke} />;
  if (shown === "wide" || shown === "up") return <ellipse cx="32" cy={y + 1} rx="1.8" ry="2.2" {...stroke} />;
  return <circle cx="32" cy={y + 1} r="1.6" {...stroke} />;
}

/** A small sign of the mood in the top right: thought dots, a question, Zz, sparkles, a tear. */
function MoodSign({ face, mood }: { face: Face; mood: Mood }) {
  switch (mood) {
    case "thinking":
      return (
        <g className="avatar-sign">
          <circle cx="50" cy="13" r="8" fill="#ffffff" stroke={INK} strokeWidth="0.8" />
          {[46.5, 50, 53.5].map((cx, i) => (
            <circle key={cx} cx={cx} cy="13" r="1.3" fill={INK} className={`avatar-think avatar-think-${i}`} />
          ))}
        </g>
      );
    case "waiting":
      return (
        <g className="avatar-sign avatar-pulse">
          <circle cx="50" cy="13" r="8" fill="#ffd166" stroke={INK} strokeWidth="0.8" />
          <path d="M47.6 11 Q47.8 8 50.2 8 Q52.8 8.2 52.6 10.8 Q52.4 12.4 50.2 13.4 L50.2 15" stroke={INK} strokeWidth="1.7" strokeLinecap="round" fill="none" />
          <circle cx="50.2" cy="17.6" r="1" fill={INK} />
        </g>
      );
    case "sleepy":
      return (
        <path className="avatar-sign avatar-float" d="M46 9 L52 9 L46 15 L52 15 M53.5 3.5 L57 3.5 L53.5 7 L57 7" stroke="#5b6b8c" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      );
    case "happy":
      return (
        <g fill="#ffd166" stroke="#c99a1d" strokeWidth="0.5">
          <path className="avatar-twinkle" d="M51 6 L52.3 10.2 L56.5 11.5 L52.3 12.8 L51 17 L49.7 12.8 L45.5 11.5 L49.7 10.2 Z" />
          <path className="avatar-twinkle avatar-twinkle-late" d="M12 9 L12.8 11.7 L15.5 12.5 L12.8 13.3 L12 16 L11.2 13.3 L8.5 12.5 L11.2 11.7 Z" />
        </g>
      );
    case "sad":
      return (
        <path
          className="avatar-tear"
          d={`M${32 + face.eyeDX + 1.5} ${face.eyeY + 3} Q${32 + face.eyeDX + 4} ${face.eyeY + 7.5} ${32 + face.eyeDX + 1.5} ${face.eyeY + 8.5} Q${32 + face.eyeDX - 1} ${face.eyeY + 7.5} ${32 + face.eyeDX + 1.5} ${face.eyeY + 3} Z`}
          fill="#6bb7f0"
        />
      );
    default:
      return null;
  }
}

function Wear({ face, accessory }: { face: Face; accessory: Accessory }) {
  const { eyeY: y, eyeDX: dx, topY: top } = face;
  switch (accessory) {
    case "none":
      return null;
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

/** Blinks of nearby faces should not happen at once. */
const BLINKS = ["avatar-blink-0", "avatar-blink-1", "avatar-blink-2", "avatar-blink-3"] as const;

/**
 * The picture of a look. Decorative: the agent's name is always shown next to it. It blinks,
 * and with a mood it shows how the agent feels: busy (bobs), thinking (eyes up, thought dots),
 * waiting for the owner (a question), done (^^, sparkles), failed (sad, a tear), paused (Zz).
 * Animations stop for people who ask the system for less motion.
 */
export function AvatarArt({
  look,
  size = 28,
  mood = "calm",
  animated = true,
  className,
}: {
  look: Look;
  size?: number;
  mood?: Mood;
  animated?: boolean;
  className?: string;
}) {
  const clip = useId();
  const face = FACES[look.animal];
  const shown = shownFor(look.expression, mood);
  const blink = BLINKS[(look.backdrop.charCodeAt(2) + look.animal.length) % BLINKS.length];
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      className={cn("shrink-0 rounded-full", animated && "avatar-live", className)}
      data-avatar={`${look.animal}-${look.accessory}-${look.expression}`}
      data-mood={mood}
    >
      <defs>
        <clipPath id={clip}>
          <circle cx="32" cy="32" r="32" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clip})`}>
        <rect width="64" height="64" fill={look.backdrop} />
        <g className={mood === "busy" ? "avatar-bob" : mood === "happy" ? "avatar-hop" : mood === "sad" ? "avatar-droop" : undefined}>
          {face.body}
          <g className={shown === "closed" || shown === "happy" ? undefined : cn("avatar-eyes", blink)}>
            <Eyes face={face} shown={shown} />
          </g>
          {face.mouthY !== null && <Mouth y={face.mouthY} shown={shown} />}
          <Wear face={face} accessory={look.accessory} />
        </g>
        <MoodSign face={face} mood={mood} />
      </g>
    </svg>
  );
}

/** The faces of the whole office, recomputed when its agents change. */
export function useAgentLooks(): Map<string, Look> {
  const agents = useRealtimeStore((s) => s.agents);
  return useMemo(() => assignLooks(Object.values(agents)), [agents]);
}

/**
 * An agent's face (also for one the office no longer lists). Its mood follows the agent's
 * status live (or `status` when given, e.g. a task's); `mood` sets it outright.
 */
export function AgentAvatar({
  agentId,
  size = 28,
  status,
  mood,
  animated = true,
  className,
}: {
  agentId: string | null | undefined;
  size?: number;
  status?: string | null;
  mood?: Mood;
  animated?: boolean;
  className?: string;
}) {
  const looks = useAgentLooks();
  const agent = useRealtimeStore((s) => (agentId ? s.agents[agentId] : undefined));
  const look = agentId ? (looks.get(agentId) ?? lookOf(agentId, agent?.animal)) : null;
  if (!look)
    return (
      <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true" className={cn("shrink-0 text-muted", className)}>
        <circle cx="32" cy="32" r="32" fill="currentColor" />
      </svg>
    );
  const feeling = mood ?? moodOf(status !== undefined ? status : agent?.status);
  return <AvatarArt look={look} size={size} mood={feeling} animated={animated} className={className} />;
}
