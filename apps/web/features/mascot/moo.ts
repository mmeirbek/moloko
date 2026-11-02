/**
 * A synthesized "moo" (Web Audio, no sound file): a buzzy low tone that glides down,
 * shaped by two vowel-like filters. Played only when the owner turned sounds on.
 */
export function playMoo(): void {
  const Ctx =
    typeof window === "undefined"
      ? undefined
      : (window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext);
  if (!Ctx) return;
  try {
    const ctx = new Ctx();
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(150, now);
    osc.frequency.linearRampToValueAtTime(175, now + 0.25);
    osc.frequency.exponentialRampToValueAtTime(105, now + 1.1);
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.25, now + 0.12);
    gain.gain.setValueAtTime(0.25, now + 0.8);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.25);
    const out = ctx.createGain();
    out.gain.value = 0.6;
    for (const [freq, q] of [
      [600, 4],
      [1000, 6],
    ] as const) {
      const f = ctx.createBiquadFilter();
      f.type = "bandpass";
      f.frequency.setValueAtTime(freq * 0.7, now); // "mmm" → "ooo"
      f.frequency.linearRampToValueAtTime(freq, now + 0.4);
      f.Q.value = q;
      gain.connect(f).connect(out);
    }
    osc.connect(gain);
    out.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 1.3);
    osc.onended = () => void ctx.close();
  } catch {
    /* audio blocked: stay silent */
  }
}
