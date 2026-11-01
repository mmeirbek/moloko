import * as Phaser from "phaser";

import type { OfficeBus } from "./bus";
import { OfficeScene } from "./OfficeScene";

/** Pixel-perfect game (spec 18.6): 640×360 world, no smoothing, integer camera zoom. */
export function createOfficeGame(parent: HTMLElement, bus: OfficeBus): Phaser.Game {
  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    backgroundColor: "#0c1024",
    pixelArt: true,
    roundPixels: true,
    antialias: false,
    banner: false,
    audio: { noAudio: true },
    // The page scrolls over the office; zoom is Ctrl/⌘ + wheel (OfficeScene), buttons or pinch.
    input: { activePointers: 3, mouse: { preventDefaultWheel: false } },
    scale: {
      mode: Phaser.Scale.RESIZE,
      width: Math.max(1, parent.clientWidth),
      height: Math.max(1, parent.clientHeight),
    },
    callbacks: {
      preBoot: (g) => g.registry.set("bus", bus),
    },
    scene: [OfficeScene],
  });
  return game;
}
