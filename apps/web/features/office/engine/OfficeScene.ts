/**
 * The Pixel Office scene (Phaser 4). It ONLY renders: agents come in through the bus
 * from the realtime store; the scene never changes agent state (spec 4.4, 18.7).
 * The Orchestrator is drawn as the moloko cow; time of day, season and pending approvals
 * also come from React (OfficeEnv) — the scene reads no clock or store of its own.
 *
 * The canvas has the screen's device resolution (createGame.ts); camera zoom = whole device
 * pixels per art pixel (zoom.ts), so the art stays pixel-perfect at every level.
 */
import * as Phaser from "phaser";

import { SeatAssigner } from "./assign";
import { behaviorFor, cowBehaviorFor, type Behavior, type CowBehavior, type Indicator } from "./behavior";
import type { CameraAction, OfficeAgent, OfficeBus, OfficeEnv } from "./bus";
import {
  BUBBLE_COLORS,
  bubbleRows,
  COW_FRAMES,
  COW_H,
  COW_POSES,
  COW_W,
  ENVELOPE,
  ENVELOPE_COLORS,
  paintCowSheet,
  paintRows,
  PET_COLORS,
  petFor,
  PETS,
} from "./cow";
import { isNight, skyFor } from "./daynight";
import { monitorSpot, paintMap, paintOffice, paintWindows, petSpot, PROP_ART, propPlacements } from "./decor";
import { DESKS, stepsTo, tileCenter, walkable, WORLD_H, WORLD_W, ZONES, type Spot } from "./map";
import { findPath, type Cell } from "./pathfinding";
import { BADGE_H, BADGE_W, BADGES, FRAME, FRAME_ORDER, paintBadge, paintSheet, paletteFor, POSE_FRAMES } from "./sprites";
import { autoLevel, fitZoom, nearestLevel, stepLevel, zoomLevels, zoomPercent } from "./zoom";

const SPEED = 56; // px per second
/** name tags keep this size on screen (CSS px), whatever the zoom */
const LABEL_FONT_PX = 10;
const LABEL_MAX_CHARS = 18;
/** below this size (CSS px per art px) name tags show only for the hovered or selected agent */
const LABELS_FROM_SCALE = 1;

const SHADOW_SMALL = [".xxxxxxxxxx.", "xxxxxxxxxxxx", ".xxxxxxxxxx."];
const SHADOW_COW = [".xxxxxxxxxxxxxxxxxx.", "xxxxxxxxxxxxxxxxxxxx", ".xxxxxxxxxxxxxxxxxx."];
const RING_SMALL = ["...xxxxxxxx...", ".xx........xx.", "x............x", ".xx........xx.", "...xxxxxxxx..."];
const RING_COW = [
  "....xxxxxxxxxxxxxx....",
  ".xxx..............xxx.",
  "x....................x",
  ".xxx..............xxx.",
  "....xxxxxxxxxxxxxx....",
];

interface Character {
  agent: OfficeAgent;
  sprite: Phaser.GameObjects.Sprite;
  shadow: Phaser.GameObjects.Image;
  badge: Phaser.GameObjects.Image;
  label: Phaser.GameObjects.Text;
  cell: Cell;
  path: Cell[];
  target: Spot | null;
  behavior: Behavior;
  leaving: boolean;
  desk: number | null;
  /** the Orchestrator = the cow */
  cow: CowBehavior | null;
  bubble: Phaser.GameObjects.Image | null;
  pet: Phaser.GameObjects.Image | null;
  patrol: { index: number; timer: Phaser.Time.TimerEvent | null } | null;
  clicks: number[];
  mooUntil: number;
  hovered: boolean;
}

const DAY_ENV: OfficeEnv = { hour: 12, locale: "ru", season: null, attention: false };

export class OfficeScene extends Phaser.Scene {
  private bus!: OfficeBus;
  private characters = new Map<string, Character>();
  private seats = new SeatAssigner({
    desk: DESKS.length,
    lounge: ZONES.lounge.length,
    board: ZONES.board.length,
    waiting: ZONES.waiting.length,
    review: ZONES.review.length,
    meeting: ZONES.meeting.length,
    pasture: ZONES.pasture.length,
    door: ZONES.door.length,
  });
  private env: OfficeEnv = DAY_ENV;
  private windows!: Phaser.Textures.CanvasTexture;
  private shade!: Phaser.GameObjects.Rectangle;
  private glows: Phaser.GameObjects.Image[] = [];
  private monitors: Phaser.GameObjects.Image[] = [];
  private selected: string | null = null;
  private ring!: Phaser.GameObjects.Image;
  private pinchStart: number | null = null;
  private dragging = false;
  private lastPublish = 0;
  private lastLabels = 0;
  private off: Array<() => void> = [];
  // camera
  private dpr = 1;
  private levels: number[] = [1];
  private fitLevel = 1;
  /** CSS scale the owner chose on this device; null = automatic */
  private chosen: number | null = null;
  private viewKey = "";

  constructor() {
    super("office");
  }

  create(): void {
    this.bus = this.game.registry.get("bus") as OfficeBus;
    this.dpr = (this.game.registry.get("dpr") as number | undefined) ?? 1;
    const remembered = this.game.registry.get("zoom") as number | null | undefined;
    this.chosen = typeof remembered === "number" && remembered > 0 ? remembered : null;

    this.makeTextures();
    this.add.image(0, 0, "office:base").setOrigin(0, 0).setDepth(-1000);
    this.windows = this.textures.createCanvas("office:windows", WORLD_W, WORLD_H)!;
    this.add.image(0, 0, "office:windows").setOrigin(0, 0).setDepth(-999);
    this.placeProps();
    this.shade = this.add.rectangle(0, 0, WORLD_W, WORLD_H, 0x0c1024, 0).setOrigin(0, 0).setDepth(20_000);
    this.applyEnv(DAY_ENV);
    this.ring = this.add.image(0, 0, "ring:small").setVisible(false).setDepth(-1);

    this.cameras.main.setRoundPixels(true);
    this.layoutCamera(false);
    this.scale.on(Phaser.Scale.Events.RESIZE, () => this.layoutCamera(true));
    this.setupInput();

    this.off.push(this.bus.on("agents", (agents) => this.syncAgents(agents)));
    this.off.push(this.bus.on("camera", (action) => this.onCamera(action)));
    this.off.push(this.bus.on("select", (id) => this.select(id, true)));
    this.off.push(this.bus.on("message", ({ from, to }) => this.flyEnvelope(from, to)));
    this.off.push(this.bus.on("env", (env) => this.applyEnv(env)));
    // game.destroy() emits DESTROY, not SHUTDOWN: unsubscribe on whichever comes first.
    const unsubscribe = () => this.off.splice(0).forEach((f) => f());
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, unsubscribe);
    this.events.once(Phaser.Scenes.Events.DESTROY, unsubscribe);
    this.bus.emit("ready", undefined);
  }

  // --- textures and the static office ---------------------------------------------------------

  private canvasTexture(key: string, w: number, h: number, paint: (ctx: CanvasRenderingContext2D) => void): void {
    if (this.textures.exists(key)) return;
    const tex = this.textures.createCanvas(key, w, h)!;
    paint(tex.context);
    tex.refresh();
  }

  private makeTextures(): void {
    this.canvasTexture("office:base", WORLD_W, WORLD_H, paintOffice);
    for (const [name, art] of Object.entries(PROP_ART)) this.canvasTexture(`prop:${name}`, art.w, art.h, art.paint);
    for (const indicator of Object.keys(BADGES) as Exclude<Indicator, "none">[]) {
      this.canvasTexture(`badge:${indicator}`, BADGE_W, BADGE_H, (ctx) => paintBadge(ctx, indicator));
    }
    const shadow = { x: "rgba(12,16,36,0.3)" };
    const ring = { x: "#f5ecd6" };
    const art: [string, string[], Record<string, string>][] = [
      ["shadow:small", SHADOW_SMALL, shadow],
      ["shadow:cow", SHADOW_COW, shadow],
      ["ring:small", RING_SMALL, ring],
      ["ring:cow", RING_COW, ring],
      ["bubble:moo:ru", bubbleRows("МУ!"), BUBBLE_COLORS],
      ["bubble:moo:en", bubbleRows("MOO!"), BUBBLE_COLORS],
      ["bubble:zzz", bubbleRows("Zz"), BUBBLE_COLORS],
      ["envelope", ENVELOPE, ENVELOPE_COLORS],
      ...Object.entries(PETS).map(([name, rows]): [string, string[], Record<string, string>] => [`pet:${name}`, rows, PET_COLORS]),
    ];
    for (const [key, rows, colors] of art) {
      this.canvasTexture(key, rows[0]!.length, rows.length, (ctx) =>
        key.startsWith("shadow") || key.startsWith("ring") ? paintMap(ctx, rows, colors) : paintRows(ctx, rows, colors),
      );
    }
  }

  private placeProps(): void {
    for (const prop of propPlacements()) {
      this.add.image(prop.x, prop.y, `prop:${prop.art}`).setOrigin(0, 0).setDepth(prop.depth);
    }
    for (const desk of DESKS) {
      const spot = monitorSpot(desk);
      this.monitors.push(this.add.image(spot.x, spot.y, "prop:monitor-off").setOrigin(0, 0).setDepth(spot.depth));
      // at night a lit screen glows through the dark (drawn above the night shade)
      this.glows.push(
        this.add
          .image(spot.x - 6, spot.y - 1, "prop:monitor-glow")
          .setOrigin(0, 0)
          .setDepth(20_001)
          .setVisible(false),
      );
    }
  }

  /** One sheet per outfit (the hat is baked into every frame). */
  private ensureCowTexture(): string {
    const key = `cow:${this.env.season ?? "plain"}`;
    if (this.textures.exists(key)) return key;
    const tex = this.textures.createCanvas(key, COW_W * COW_FRAMES.length, COW_H)!;
    paintCowSheet(tex.context, this.env.season);
    tex.refresh();
    COW_FRAMES.forEach((name, i) => tex.add(name, 0, i * COW_W, 0, COW_W, COW_H));
    for (const [pose, frames] of Object.entries(COW_POSES)) {
      this.anims.create({
        key: `${key}:${pose}`,
        frames: frames.map((frame) => ({ key, frame })),
        frameRate: pose === "walk" || pose === "carry" ? 6 : pose === "graze" ? 3 : 2,
        repeat: -1,
      });
    }
    return key;
  }

  private ensureAgentTexture(agent: OfficeAgent): string {
    const key = `agent:${agent.id}`;
    if (this.textures.exists(key)) return key;
    const tex = this.textures.createCanvas(key, FRAME * FRAME_ORDER.length, FRAME)!;
    paintSheet(tex.context, paletteFor(agent.id, agent.kind));
    tex.refresh();
    FRAME_ORDER.forEach((name, i) => tex.add(name, 0, i * FRAME, 0, FRAME, FRAME));
    for (const [pose, frames] of Object.entries(POSE_FRAMES)) {
      this.anims.create({
        key: `${key}:${pose}`,
        frames: frames.map((frame) => ({ key, frame })),
        frameRate: pose === "walk" ? 6 : pose === "type" ? 5 : 2,
        repeat: -1,
      });
    }
    return key;
  }

  // --- agents ---------------------------------------------------------------------------

  syncAgents(agents: OfficeAgent[]): void {
    const seen = new Set<string>();
    for (const agent of agents) {
      seen.add(agent.id);
      const existing = this.characters.get(agent.id);
      if (existing) {
        const changed = existing.agent.status !== agent.status;
        existing.agent = agent;
        existing.label.setText(shortName(agent.name));
        if (changed || existing.leaving) {
          existing.leaving = false;
          this.route(existing);
        }
      } else {
        this.spawn(agent);
      }
    }
    for (const [id, character] of this.characters) {
      if (!seen.has(id) && !character.leaving) this.leave(character);
    }
    this.refreshMonitors();
  }

  private spawn(agent: OfficeAgent): void {
    const isCow = agent.kind === "orchestrator";
    const key = isCow ? this.ensureCowTexture() : this.ensureAgentTexture(agent);
    const door = ZONES.door[this.seats.seat("door", agent.id)]!;
    const { x, y } = tileCenter(door.col, door.row);
    const sprite = this.add
      .sprite(x, y, key, "stand")
      .setOrigin(0.5, isCow ? (COW_H - 1.5) / COW_H : 0.85)
      .setInteractive({ useHandCursor: true });
    const character: Character = {
      agent,
      sprite,
      shadow: this.add.image(x, y, isCow ? "shadow:cow" : "shadow:small"),
      badge: this.add.image(x, y, "badge:check").setOrigin(0.5, 1).setVisible(false),
      label: this.makeLabel(x, y, agent.name),
      cell: { col: door.col, row: door.row },
      path: [],
      target: null,
      behavior: behaviorFor(agent.status),
      leaving: false,
      desk: null,
      cow: isCow ? cowBehaviorFor(agent.status, this.cowFacts()) : null,
      bubble: isCow ? this.add.image(x, y - 24, "bubble:zzz").setOrigin(0, 1).setVisible(false) : null,
      pet: null,
      patrol: null,
      clicks: [],
      mooUntil: 0,
      hovered: false,
    };
    sprite.on("pointerdown", (p: Phaser.Input.Pointer) => {
      p.event.stopPropagation();
      this.bus.emit("selected", agent.id);
      this.select(agent.id);
      if (isCow) this.countCowClick(agent.id);
    });
    sprite.on("pointerover", () => {
      character.hovered = true;
      this.layoutLabels();
    });
    sprite.on("pointerout", () => {
      character.hovered = false;
      this.layoutLabels();
    });
    if (agent.kind === "autonomous") {
      // persistent agents keep their own desk, with their pet on it
      character.desk = this.seats.seat("desk", agent.id);
      const spot = petSpot(DESKS[character.desk]!);
      character.pet = this.add
        .image(spot.x, spot.y, `pet:${petFor(agent.id)}`)
        .setOrigin(0, 1)
        .setDepth(monitorSpot(DESKS[character.desk]!).depth);
      this.tweens.add({
        targets: character.pet,
        y: character.pet.y - 1,
        duration: 260,
        yoyo: true,
        repeat: -1,
        repeatDelay: 1800 + ((petFor(agent.id).length * 377) % 1500),
      });
    }
    this.characters.set(agent.id, character);
    this.route(character);
  }

  private makeLabel(x: number, y: number, name: string): Phaser.GameObjects.Text {
    return this.add
      .text(x, y, shortName(name), {
        fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
        fontSize: `${LABEL_FONT_PX}px`,
        fontStyle: "bold",
        color: "#f5ecd6",
        backgroundColor: "rgba(16,20,43,0.82)",
        padding: { x: 3, y: 1 },
        resolution: this.dpr,
      })
      .setOrigin(0.5, 0)
      .setScale(this.dpr / this.cameras.main.zoom)
      .setVisible(false);
  }

  private leave(character: Character): void {
    character.leaving = true;
    character.badge.setVisible(false);
    character.bubble?.setVisible(false);
    this.stopPatrol(character);
    const door = ZONES.door[this.seats.seat("door", character.agent.id)]!;
    this.walkTo(character, door);
  }

  private spotFor(character: Character, behavior: Behavior): Spot | null {
    const id = character.agent.id;
    if (behavior.place === "stay") return null;
    if (behavior.place === "desk") {
      character.desk ??= this.seats.seat("desk", id);
      return DESKS[character.desk]!.seat;
    }
    const zone = ZONES[behavior.place];
    return zone[this.seats.seat(behavior.place, id)] ?? zone[0]!;
  }

  private cowFacts(): { night: boolean; attention: boolean } {
    return { night: isNight(this.env.hour), attention: this.env.attention };
  }

  private route(character: Character): void {
    if (character.cow !== null) {
      this.routeCow(character);
      return;
    }
    const behavior = behaviorFor(character.agent.status);
    character.behavior = behavior;
    // free spots in other zones (desks stay reserved for the agent's lifetime)
    for (const zone of ["lounge", "board", "waiting", "review", "meeting", "pasture"] as const) {
      if (behavior.place !== zone) this.seats.release(zone, character.agent.id);
    }
    const spot = this.spotFor(character, behavior);
    if (spot === null) {
      character.path = [];
      this.applyPose(character);
      return;
    }
    character.target = spot;
    this.walkTo(character, spot);
  }

  private walkTo(character: Character, spot: Spot): void {
    const goal = { col: spot.col, row: spot.row };
    const path = findPath(character.cell, goal, stepsTo(goal));
    character.path = path ? path.slice(1) : [];
    character.badge.setVisible(false);
    if (character.path.length === 0) {
      this.arrive(character);
      return;
    }
    character.bubble?.setVisible(false);
    character.sprite.play(this.animKey(character, character.cow?.place === "patrol" ? "carry" : "walk"), true);
  }

  private animKey(character: Character, pose: string): string {
    return character.cow !== null
      ? `cow:${this.env.season ?? "plain"}:${pose}`
      : `agent:${character.agent.id}:${pose}`;
  }

  // --- the cow ------------------------------------------------------------------------------

  private routeCow(character: Character): void {
    const cow = cowBehaviorFor(character.agent.status, this.cowFacts());
    character.cow = cow;
    character.behavior = { place: "stay", pose: "rest", indicator: cow.indicator, animated: cow.animated };
    this.stopPatrol(character);
    for (const zone of ["board", "review"] as const) {
      if (cow.place !== zone) this.seats.release(zone, character.agent.id);
    }
    if (cow.place === "stay") {
      character.path = [];
      this.applyPose(character);
      return;
    }
    if (cow.place === "patrol") {
      character.patrol = { index: 0, timer: null };
      this.patrolNext(character);
      return;
    }
    const spot =
      cow.place === "pasture"
        ? ZONES.pasture[0]!
        : (ZONES[cow.place][this.seats.seat(cow.place, character.agent.id)] ?? ZONES[cow.place][0]!);
    character.target = spot;
    this.walkTo(character, spot);
  }

  /** Working: visit the other characters one by one (hand out work, collect results). */
  private patrolNext(cow: Character): void {
    if (!cow.patrol || cow.leaving) return;
    const others = [...this.characters.values()].filter((c) => c !== cow && !c.leaving);
    let goal: Cell | null = null;
    if (others.length > 0) {
      const visit = others[cow.patrol.index % others.length]!;
      cow.patrol.index++;
      const around: Cell[] = [
        { col: visit.cell.col + 1, row: visit.cell.row },
        { col: visit.cell.col - 1, row: visit.cell.row },
        { col: visit.cell.col, row: visit.cell.row + 1 },
        { col: visit.cell.col + 2, row: visit.cell.row },
        { col: visit.cell.col, row: visit.cell.row - 1 },
      ];
      goal = around.find((cell) => walkable(cell.col, cell.row)) ?? null;
    }
    if (!goal) {
      const spots = [ZONES.pasture[0]!, ZONES.board[2]!, ZONES.meeting[2]!];
      goal = spots[cow.patrol.index++ % spots.length]!;
    }
    cow.target = { ...goal, facing: "down" };
    this.walkTo(cow, cow.target);
  }

  private stopPatrol(character: Character): void {
    character.patrol?.timer?.remove(false);
    character.patrol = null;
  }

  private countCowClick(id: string): void {
    const cow = this.characters.get(id);
    if (!cow) return;
    const now = this.time.now;
    cow.clicks = [...cow.clicks.filter((at) => now - at < 2500), now];
    if (cow.clicks.length < 5) return;
    cow.clicks = [];
    cow.mooUntil = now + 1600;
    this.bus.emit("moo", undefined);
    this.applyPose(cow);
    this.time.delayedCall(1650, () => {
      if (cow.sprite.active && cow.path.length === 0) this.applyPose(cow);
    });
  }

  // --- time of day ----------------------------------------------------------------------------

  private applyEnv(env: OfficeEnv): void {
    const before = this.env;
    this.env = env;
    const sky = skyFor(env.hour);
    this.shade.setFillStyle(sky.tint, sky.tintAlpha);
    paintWindows(this.windows.context, sky, env.hour);
    this.windows.refresh();
    this.refreshMonitors();
    const outfitChanged = before.season !== env.season;
    for (const c of this.characters.values()) {
      if (c.cow === null || c.leaving) continue;
      if (outfitChanged) c.sprite.setTexture(this.ensureCowTexture(), "stand");
      const next = cowBehaviorFor(c.agent.status, this.cowFacts());
      const moved = next.place !== c.cow.place;
      if (moved || outfitChanged || next.pose !== c.cow.pose || next.bubble !== c.cow.bubble) {
        if (moved) this.route(c);
        else {
          c.cow = next;
          c.behavior = { ...c.behavior, indicator: next.indicator, animated: next.animated };
          if (c.path.length === 0) this.applyPose(c);
          else c.sprite.play(this.animKey(c, next.place === "patrol" ? "carry" : "walk"), true);
        }
      }
    }
  }

  private arrive(character: Character): void {
    if (character.leaving) {
      character.sprite.destroy();
      character.shadow.destroy();
      character.badge.destroy();
      character.label.destroy();
      character.bubble?.destroy();
      if (character.pet) {
        this.tweens.killTweensOf(character.pet);
        character.pet.destroy();
      }
      this.seats.releaseAll(character.agent.id);
      this.characters.delete(character.agent.id);
      if (this.selected === character.agent.id) this.select(null);
      this.refreshMonitors();
      return;
    }
    this.applyPose(character);
    if (character.patrol) {
      const cow = character;
      character.patrol.timer = this.time.delayedCall(1600, () => this.patrolNext(cow));
    }
  }

  private applyPose(character: Character): void {
    if (character.cow !== null) {
      this.applyCowPose(character);
      return;
    }
    const { pose, indicator, animated } = character.behavior;
    const key = `agent:${character.agent.id}:${pose}`;
    if (animated) character.sprite.play(key, true);
    else character.sprite.stop();
    character.sprite.setAlpha(pose === "frozen" ? 0.65 : 1);
    character.sprite.setFlipX(false);
    this.showBadge(character, indicator);
    this.refreshMonitors();
  }

  private showBadge(character: Character, indicator: Indicator): void {
    if (indicator === "none") character.badge.setVisible(false);
    else character.badge.setTexture(`badge:${indicator}`).setVisible(true);
  }

  private applyCowPose(character: Character): void {
    const cow = character.cow!;
    const mooing = character.mooUntil > this.time.now;
    // at the end of a patrol leg the cow stands for a moment, handing papers over
    const pose = mooing ? "moo" : cow.place === "patrol" ? "stand" : cow.pose;
    if (cow.animated || mooing) character.sprite.play(this.animKey(character, pose), true);
    else character.sprite.stop();
    character.sprite.setAlpha(pose === "frozen" ? 0.65 : 1);
    this.showBadge(character, mooing ? "none" : cow.indicator);
    const bubble = mooing ? "moo" : cow.bubble;
    if (bubble && character.bubble) {
      const key = bubble === "zzz" ? "bubble:zzz" : `bubble:moo:${this.env.locale.startsWith("en") ? "en" : "ru"}`;
      character.bubble.setTexture(key).setVisible(true);
    } else character.bubble?.setVisible(false);
  }

  private refreshMonitors(): void {
    const lit = new Set<number>();
    for (const c of this.characters.values()) {
      if (c.desk !== null && !c.leaving && c.path.length === 0 && c.agent.status === "working") lit.add(c.desk);
    }
    const dark = skyFor(this.env.hour).tintAlpha > 0.1;
    this.monitors.forEach((m, i) => m.setTexture(lit.has(i) ? "prop:monitor-on" : "prop:monitor-off"));
    this.glows.forEach((glow, i) => glow.setVisible(dark && lit.has(i)));
  }

  private flyEnvelope(from: string, to: string): void {
    const a = this.characters.get(from);
    const b = this.characters.get(to);
    if (!a || !b) return;
    const start = { x: a.sprite.x, y: a.sprite.y - 14 };
    const env = this.add.image(start.x, start.y, "envelope").setDepth(30_000);
    const distance = Phaser.Math.Distance.Between(a.sprite.x, a.sprite.y, b.sprite.x, b.sprite.y);
    const height = Math.min(40, 10 + distance / 6);
    this.tweens.addCounter({
      from: 0,
      to: 1,
      duration: Math.min(1600, 600 + distance * 3),
      ease: "Sine.easeInOut",
      onUpdate: (tween) => {
        const t = tween.getValue() ?? 0;
        const x = start.x + (b.sprite.x - start.x) * t;
        const y = start.y + (b.sprite.y - 14 - start.y) * t - Math.sin(Math.PI * t) * height;
        env.setPosition(Math.round(x), Math.round(y));
      },
      onComplete: () => {
        // a little pop when it lands
        this.tweens.add({ targets: env, scale: 2, alpha: 0, duration: 220, onComplete: () => env.destroy() });
      },
    });
  }

  /** Highlight an agent; `reveal` (from the list under the map) also brings it into view. */
  select(id: string | null, reveal = false): void {
    this.selected = id;
    const character = id !== null ? this.characters.get(id) : undefined;
    this.ring.setVisible(character !== undefined);
    this.ring.setTexture(character?.cow ? "ring:cow" : "ring:small");
    for (const c of this.characters.values()) {
      const mine = c.agent.id === id;
      c.label.setBackgroundColor(mine ? "#f5ecd6" : "rgba(16,20,43,0.82)").setColor(mine ? "#10142b" : "#f5ecd6");
    }
    if (character && reveal) {
      const view = this.cameras.main.worldView;
      const { x, y } = character.sprite;
      if (!Phaser.Geom.Rectangle.Contains(view, x, y - 8)) {
        this.cameras.main.centerOn(x, y - 8);
        this.clampCamera();
      }
    }
    this.layoutLabels();
  }

  // --- loop -------------------------------------------------------------------------------

  update(time: number, delta: number): void {
    for (const c of this.characters.values()) {
      const next = c.path[0];
      if (next) {
        const goal = tileCenter(next.col, next.row);
        const dx = goal.x - c.sprite.x;
        const dy = goal.y - c.sprite.y;
        const dist = Math.hypot(dx, dy);
        const step = (SPEED * delta) / 1000;
        if (dist <= step) {
          c.sprite.setPosition(goal.x, goal.y);
          c.cell = next;
          c.path.shift();
          if (c.path.length === 0) this.arrive(c);
        } else {
          c.sprite.setPosition(c.sprite.x + (dx / dist) * step, c.sprite.y + (dy / dist) * step);
          if (Math.abs(dx) > 0.5) c.sprite.setFlipX(dx < 0);
        }
      }
      if (!c.sprite.active) continue;
      const x = Math.round(c.sprite.x);
      const y = Math.round(c.sprite.y);
      c.sprite.setDepth(c.sprite.y);
      c.shadow.setPosition(x, y + 2).setDepth(c.sprite.y - 0.5);
      const headX = c.cow ? x + (c.sprite.flipX ? -6 : 6) : x;
      c.badge.setPosition(headX, y - (c.cow ? 15 : 14)).setDepth(21_000 + c.sprite.y);
      c.label.setPosition(x, y + 4).setDepth(25_000 + c.sprite.y);
      c.bubble?.setPosition(x + 4, y - 17).setDepth(30_000);
      if (this.selected === c.agent.id) this.ring.setPosition(x, y + 2).setDepth(c.sprite.y - 0.4);
    }
    this.handlePinch();
    this.clampCamera();
    if (time - this.lastLabels > 160) {
      this.lastLabels = time;
      this.layoutLabels();
    }
    if (time - this.lastPublish > 300) {
      this.lastPublish = time;
      this.publishState();
    }
  }

  /**
   * Name tags: always for the hovered and the selected agent; for everyone else when the
   * office is big enough to read them, skipping tags that would overlap a more important one.
   */
  private layoutLabels(): void {
    const all = this.cameras.main.zoom / this.dpr >= LABELS_FROM_SCALE;
    const rank = (c: Character) =>
      (c.agent.id === this.selected ? 100 : 0) +
      (c.hovered ? 50 : 0) +
      (c.cow ? 5 : 0) +
      (c.agent.status === "idle" ? 0 : 10);
    const order = [...this.characters.values()]
      .filter((c) => !c.leaving && c.sprite.active)
      .sort((a, b) => rank(b) - rank(a) || a.sprite.y - b.sprite.y);
    const placed: { x1: number; y1: number; x2: number; y2: number }[] = [];
    for (const c of order) {
      const label = c.label;
      const w = label.displayWidth;
      const h = label.displayHeight;
      const box = { x1: label.x - w / 2, y1: label.y, x2: label.x + w / 2, y2: label.y + h };
      const free = placed.every((p) => box.x2 <= p.x1 || box.x1 >= p.x2 || box.y2 <= p.y1 || box.y1 >= p.y2);
      const show = c.agent.id === this.selected || c.hovered || (all && free);
      label.setVisible(show);
      if (show) placed.push(box);
    }
  }

  /** Read-only snapshot for tests and assistive tech: what is drawn where (CSS px). */
  private publishState(): void {
    const cam = this.cameras.main;
    const toCss = cam.zoom / this.dpr;
    const state = [...this.characters.values()]
      .filter((c) => !c.leaving)
      .map((c) => ({
        id: c.agent.id,
        status: c.agent.status,
        kind: c.agent.kind,
        pose: c.cow
          ? c.path.length
            ? c.cow.place === "patrol"
              ? "carry"
              : "walk"
            : c.cow.pose
          : c.path.length
            ? "walk"
            : c.behavior.pose,
        bubble: c.cow && c.bubble?.visible ? c.cow.bubble : undefined,
        pet: c.pet ? petFor(c.agent.id) : undefined,
        x: Math.round((c.sprite.x - cam.worldView.x) * toCss),
        y: Math.round((c.sprite.y - 6 - cam.worldView.y) * toCss),
      }));
    this.game.canvas.dataset.agents = JSON.stringify(state);
  }

  // --- camera -----------------------------------------------------------------------------

  /** The world point at the centre of the view (Camera.midPoint is only refreshed at render). */
  private viewCenter(): { x: number; y: number } {
    const cam = this.cameras.main;
    return { x: cam.scrollX + cam.width / 2, y: cam.scrollY + cam.height / 2 };
  }

  /** (Re)compute the zoom levels for the view's size and apply the chosen or automatic one. */
  private layoutCamera(keepCenter: boolean): void {
    const cam = this.cameras.main;
    const dpr = (this.game.registry.get("dpr") as number | undefined) ?? 1;
    const w = this.scale.width;
    const h = this.scale.height;
    const key = `${w}x${h}@${dpr}`;
    if (keepCenter && key === this.viewKey) return;
    this.viewKey = key;
    const center = keepCenter ? this.viewCenter() : { x: WORLD_W / 2, y: WORLD_H / 2 };
    cam.setSize(w, h);
    this.dpr = dpr;
    this.fitLevel = fitZoom(w, h, WORLD_W, WORLD_H);
    this.levels = zoomLevels(dpr, this.fitLevel);
    const level =
      this.chosen !== null
        ? nearestLevel(this.levels, this.chosen, dpr)
        : autoLevel(this.levels, this.fitLevel, dpr);
    cam.setZoom(level);
    cam.centerOn(center.x, center.y);
    this.clampCamera();
    this.afterZoom();
  }

  /** Zoom to a level; `anchor` (game px) keeps the point under the finger / cursor in place. */
  private zoomTo(level: number, anchor?: { x: number; y: number }): void {
    const cam = this.cameras.main;
    const before = cam.zoom;
    if (level === before) return;
    const center = this.viewCenter();
    let next = center;
    if (anchor) {
      const ax = anchor.x - cam.width / 2;
      const ay = anchor.y - cam.height / 2;
      next = { x: center.x + ax / before - ax / level, y: center.y + ay / before - ay / level };
    }
    cam.setZoom(level);
    cam.centerOn(next.x, next.y);
    this.clampCamera();
  }

  /** One step in or out (buttons, keys, Ctrl/⌘ + wheel, pinch): the owner's choice is remembered. */
  private zoomStep(direction: 1 | -1, anchor?: { x: number; y: number }): void {
    const level = stepLevel(this.levels, this.cameras.main.zoom, direction);
    this.chosen = level / this.dpr;
    this.zoomTo(level, anchor);
    this.afterZoom();
  }

  private onCamera(action: CameraAction): void {
    const cam = this.cameras.main;
    if (action === "in" || action === "out") return this.zoomStep(action === "in" ? 1 : -1);
    if (action === "fit") {
      this.chosen = null;
      cam.setZoom(this.fitLevel);
      cam.centerOn(WORLD_W / 2, WORLD_H / 2);
      this.clampCamera();
      this.afterZoom();
      return;
    }
    // keyboard panning: about 64 CSS px per press
    const step = Math.max(8, (64 * this.dpr) / cam.zoom);
    const dx = action === "left" ? -step : action === "right" ? step : 0;
    const dy = action === "up" ? -step : action === "down" ? step : 0;
    const center = this.viewCenter();
    cam.centerOn(center.x + dx, center.y + dy);
    this.clampCamera();
  }

  /** Tell React, resize the name tags, show the grab cursor when the office can be dragged. */
  private afterZoom(): void {
    const cam = this.cameras.main;
    const zoom = cam.zoom;
    for (const c of this.characters.values()) c.label.setScale(this.dpr / zoom);
    const pannable = cam.width / zoom < WORLD_W - 0.5 || cam.height / zoom < WORLD_H - 0.5;
    this.input.setDefaultCursor(pannable ? "grab" : "default");
    this.bus.emit("zoom", {
      percent: zoomPercent(zoom, this.dpr),
      canZoomIn: zoom < this.levels.at(-1)!,
      canZoomOut: zoom > this.levels[0]!,
      fitted: zoom <= this.fitLevel,
      chosen: this.chosen,
    });
    this.layoutLabels();
  }

  /** Keep the office in view; centre it when it is smaller than the view. */
  private clampCamera(): void {
    const cam = this.cameras.main;
    const viewW = cam.width / cam.zoom;
    const viewH = cam.height / cam.zoom;
    const mid = this.viewCenter();
    const cx = viewW >= WORLD_W ? WORLD_W / 2 : Phaser.Math.Clamp(mid.x, viewW / 2, WORLD_W - viewW / 2);
    const cy = viewH >= WORLD_H ? WORLD_H / 2 : Phaser.Math.Clamp(mid.y, viewH / 2, WORLD_H - viewH / 2);
    if (Math.abs(cx - mid.x) > 0.01 || Math.abs(cy - mid.y) > 0.01) cam.centerOn(cx, cy);
  }

  private setupInput(): void {
    this.input.addPointer(1);
    this.input.on("pointerdown", (p: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]) => {
      this.dragging = over.length === 0;
      if (over.length === 0 && !this.input.pointer2.isDown) {
        this.bus.emit("selected", null);
        this.select(null);
      }
      if (this.dragging && this.input.manager.defaultCursor === "grab") this.input.setDefaultCursor("grabbing");
    });
    this.input.on("pointerup", () => {
      this.dragging = false;
      if (this.input.manager.defaultCursor === "grabbing") this.input.setDefaultCursor("grab");
    });
    this.input.on("pointermove", (p: Phaser.Input.Pointer) => {
      if (!p.isDown || !this.dragging || this.input.pointer2.isDown) return;
      const cam = this.cameras.main;
      cam.scrollX -= (p.x - p.prevPosition.x) / cam.zoom;
      cam.scrollY -= (p.y - p.prevPosition.y) / cam.zoom;
    });
    // A plain wheel scrolls the page past the office; Ctrl/⌘ + wheel (a trackpad pinch sends
    // ctrlKey too) zooms one step at a time around the cursor. Own non-passive listener.
    const canvas = this.game.canvas;
    let lastZoom = 0;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      if (e.timeStamp - lastZoom < 180) return; // a pinch is dozens of tiny events
      lastZoom = e.timeStamp;
      const rect = canvas.getBoundingClientRect();
      const scale = canvas.width / Math.max(1, rect.width);
      this.zoomStep(e.deltaY > 0 ? -1 : 1, { x: (e.clientX - rect.left) * scale, y: (e.clientY - rect.top) * scale });
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    this.off.push(() => canvas.removeEventListener("wheel", onWheel));
  }

  /** Two fingers: pinch to zoom around the point between them (whole steps). */
  private handlePinch(): void {
    const a = this.input.pointer1;
    const b = this.input.pointer2;
    if (!a.isDown || !b.isDown) {
      this.pinchStart = null;
      return;
    }
    const distance = Phaser.Math.Distance.Between(a.x, a.y, b.x, b.y);
    if (this.pinchStart === null) {
      this.pinchStart = distance;
      this.dragging = false;
      return;
    }
    const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    if (distance / this.pinchStart > 1.3) {
      this.zoomStep(1, mid);
      this.pinchStart = distance;
    } else if (distance / this.pinchStart < 0.77) {
      this.zoomStep(-1, mid);
      this.pinchStart = distance;
    }
  }
}

function shortName(name: string): string {
  return name.length > LABEL_MAX_CHARS ? `${name.slice(0, LABEL_MAX_CHARS - 1)}…` : name;
}
