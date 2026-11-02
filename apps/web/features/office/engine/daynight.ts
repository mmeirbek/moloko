/** Day and night in the office follow the owner's real local time. Pure: tested. */
export type Phase = "night" | "dawn" | "day" | "dusk";

export interface Sky {
  phase: Phase;
  /** window sky colours, top → bottom */
  sky: [number, number];
  hill: number;
  /** colour laid over the whole office and its strength */
  tint: number;
  tintAlpha: number;
  stars: boolean;
  sun: boolean;
  moon: boolean;
}

export function phaseFor(hour: number): Phase {
  const h = ((Math.floor(hour) % 24) + 24) % 24;
  if (h >= 22 || h < 5) return "night";
  if (h < 7) return "dawn";
  if (h < 19) return "day";
  return "dusk";
}

export function isNight(hour: number): boolean {
  return phaseFor(hour) === "night";
}

const SKIES: Record<Phase, Omit<Sky, "phase">> = {
  day: { sky: [0x6ec3f5, 0xa9dcfb], hill: 0x5bbf4a, tint: 0xffffff, tintAlpha: 0, stars: false, sun: true, moon: false },
  dawn: { sky: [0xf6b38a, 0xfde3b0], hill: 0x4f9e3a, tint: 0xff9a5a, tintAlpha: 0.08, stars: false, sun: true, moon: false },
  dusk: { sky: [0x6b4fa0, 0xf08a6a], hill: 0x3f7f32, tint: 0x6b4fa0, tintAlpha: 0.14, stars: false, sun: false, moon: true },
  night: { sky: [0x0c1024, 0x1f2a57], hill: 0x1f4a2a, tint: 0x0c1024, tintAlpha: 0.38, stars: true, sun: false, moon: true },
};

export function skyFor(hour: number): Sky {
  const phase = phaseFor(hour);
  return { phase, ...SKIES[phase] };
}
