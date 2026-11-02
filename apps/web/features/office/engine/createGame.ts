import * as Phaser from "phaser";

import type { OfficeBus } from "./bus";
import { OfficeScene } from "./OfficeScene";
import { clampDpr } from "./zoom";

export interface OfficeOptions {
  /** the zoom the owner chose on this device (CSS px per art px), or null for automatic */
  zoom: number | null;
}

/**
 * Pixel-perfect game (spec 18.6): 640×360 world, no smoothing, whole-number camera zoom.
 * The canvas has the screen's real resolution (CSS size × devicePixelRatio, shown at the
 * CSS size), so one art pixel is always a whole number of device pixels — crisp on
 * retina screens and on 125 % / 150 % display scaling too.
 */
export function createOfficeGame(parent: HTMLElement, bus: OfficeBus, options: OfficeOptions): Phaser.Game {
  const dpr = clampDpr(window.devicePixelRatio);
  const css = { w: Math.max(1, parent.clientWidth), h: Math.max(1, parent.clientHeight) };
  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    backgroundColor: "#0c1024",
    pixelArt: true,
    roundPixels: true,
    antialias: false,
    banner: false,
    audio: { noAudio: true },
    // The page scrolls over the office; zoom is Ctrl/⌘ + wheel (OfficeScene), buttons, keys or pinch.
    input: { activePointers: 3, mouse: { preventDefaultWheel: false } },
    scale: {
      mode: Phaser.Scale.NONE,
      width: Math.round(css.w * dpr),
      height: Math.round(css.h * dpr),
      zoom: 1 / dpr,
    },
    callbacks: {
      preBoot: (g) => {
        g.registry.set("bus", bus);
        g.registry.set("dpr", dpr);
        g.registry.set("zoom", options.zoom);
      },
    },
    scene: [OfficeScene],
  });

  // Follow the container's size and the screen's pixel ratio (browser zoom, another monitor).
  let last = "";
  const fitToParent = () => {
    if (!game.canvas) return;
    const ratio = clampDpr(window.devicePixelRatio);
    const w = Math.max(1, parent.clientWidth);
    const h = Math.max(1, parent.clientHeight);
    const key = `${w}x${h}@${ratio}`;
    if (key === last) return;
    last = key;
    game.registry.set("dpr", ratio);
    game.scale.zoom = 1 / ratio;
    game.scale.resize(Math.round(w * ratio), Math.round(h * ratio));
    game.canvas.style.width = `${w}px`;
    game.canvas.style.height = `${h}px`;
    game.canvas.style.display = "block";
    game.scale.refresh();
  };
  game.events.once(Phaser.Core.Events.READY, fitToParent);
  const observer = new ResizeObserver(fitToParent);
  observer.observe(parent);
  let media: MediaQueryList | null = null;
  const watchRatio = () => {
    media?.removeEventListener("change", onRatio);
    media = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
    media.addEventListener("change", onRatio);
  };
  const onRatio = () => {
    fitToParent();
    watchRatio();
  };
  watchRatio();
  game.events.once(Phaser.Core.Events.DESTROY, () => {
    observer.disconnect();
    media?.removeEventListener("change", onRatio);
  });
  return game;
}
