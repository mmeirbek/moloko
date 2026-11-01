/**
 * The Pixel Office scene (Phaser 4). It ONLY renders: agents come in through the bus
 * from the realtime store; the scene never changes agent state (spec 4.4, 18.7).
 * The Orchestrator is drawn as the moloko cow; time of day, season and pending approvals
 * also come from React (OfficeEnv) — the scene reads no clock or store of its own.
 */
import * as Phaser from "phaser";

import { SeatAssigner } from "./assign";
import { behaviorFor, cowBehaviorFor, type Behavior, type CowBehavior } from "./behavior";
import type { OfficeAgent, OfficeBus, OfficeEnv } from "./bus";
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
import { COLS, DESKS, LAYOUT, ROWS, TILE, tileCenter, walkable, WORLD_H, WORLD_W, ZONES, type Spot } from "./map";
import { findPath, type Cell } from "./pathfinding";
import { FRAME, FRAME_ORDER, ICONS, paintIcon, paintSheet, paletteFor, POSE_FRAMES } from "./sprites";

const SPEED = 56; // px per second
const MIN_ZOOM = 1;
const MAX_ZOOM = 6;

const C = {
  wall: 0x1a2247,
  wallTop: 0x262f57,
  window: 0x4aa8e8,
  floorA: 0xb8875a,
  floorB: 0xae7e52,
  rug: 0x3f6fae,
  rugEdge: 0x5f8fd0,
  desk: 0x8a5a3b,
  deskTop: 0xa06a45,
  bezel: 0x1b1b2e,
  screenOff: 0x2d3766,
  screenOn: 0x5fb3ec,
  board: 0xf6efdc,
  boardFrame: 0x6b4a2f,
  shelf: 0x6b4a2f,
  sofa: 0x5f7fd6,
  sofaDark: 0x46609f,
  table: 0xa06a45,
  bench: 0x8a5a3b,
  leaf: 0x5bbf4a,
  pot: 0xa0522d,
};

interface Character {
  agent: OfficeAgent;
  sprite: Phaser.GameObjects.Sprite;
  icon: Phaser.GameObjects.Image;
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
  private windows!: Phaser.GameObjects.Graphics;
  private shade!: Phaser.GameObjects.Rectangle;
  private glows: Phaser.GameObjects.Rectangle[] = [];
  private monitors: Phaser.GameObjects.Rectangle[] = [];
  private selected: string | null = null;
  private ring!: Phaser.GameObjects.Ellipse;
  private pinchStart: number | null = null;
  private dragging = false;
  private lastPublish = 0;
  private off: Array<() => void> = [];

  constructor() {
    super("office");
  }

  create(): void {
    this.bus = this.game.registry.get("bus") as OfficeBus;
    this.drawStatic();
    this.makeIconTextures();
    this.windows = this.add.graphics().setDepth(-999);
    this.shade = this.add.rectangle(0, 0, WORLD_W, WORLD_H, 0x0c1024, 0).setOrigin(0, 0).setDepth(20_000);
    this.applyEnv(DAY_ENV);
    this.ring = this.add.ellipse(0, 0, 14, 5, 0xf6efdc, 0.55).setVisible(false).setDepth(-1);

    const cam = this.cameras.main;
    cam.setRoundPixels(true);
    this.fit();
    this.scale.on("resize", () => this.fit());
    this.setupInput();

    this.off.push(this.bus.on("agents", (agents) => this.syncAgents(agents)));
    this.off.push(
      this.bus.on("camera", (action) => (action === "fit" ? this.fit() : this.zoomBy(action === "in" ? 1 : -1))),
    );
    this.off.push(this.bus.on("select", (id) => this.select(id)));
    this.off.push(this.bus.on("message", ({ from, to }) => this.flyEnvelope(from, to)));
    this.off.push(this.bus.on("env", (env) => this.applyEnv(env)));
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.off.forEach((f) => f()));
    this.bus.emit("ready", undefined);
  }

  // --- static map -------------------------------------------------------------------------

  private drawStatic(): void {
    const g = this.add.graphics().setDepth(-1000);
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const ch = LAYOUT[r]![c]!;
        const x = c * TILE;
        const y = r * TILE;
        if (ch === "#" || ch === "B" || ch === "K") {
          g.fillStyle(C.wall).fillRect(x, y, TILE, TILE);
          g.fillStyle(C.wallTop).fillRect(x, y + TILE - 3, TILE, 3);
          continue;
        }
        g.fillStyle((r + c) % 2 ? C.floorA : C.floorB).fillRect(x, y, TILE, TILE);
        if (ch === "G" || ch === "H") {
          g.fillStyle((r + c) % 2 ? 0x5bbf4a : 0x55b545).fillRect(x, y, TILE, TILE);
          g.fillStyle(0x4a9e3a)
            .fillRect(x + ((c * 7) % 12), y + ((r * 5) % 11), 1, 2)
            .fillRect(x + ((c * 3 + 5) % 13), y + ((r * 7 + 3) % 12), 1, 2);
          if ((r * 3 + c) % 4 === 0) g.fillStyle(0xffffff).fillRect(x + 6, y + 9, 1, 1); // daisies
          if ((r + c * 5) % 6 === 0) g.fillStyle(0xf0c93c).fillRect(x + 11, y + 4, 1, 1);
        }
        if (ch === "R") {
          g.fillStyle(C.rug).fillRect(x, y, TILE, TILE);
          g.fillStyle(C.rugEdge).fillRect(x, y, TILE, 1);
        }
      }
    }
    // furniture (drawn per tile with small details)
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const ch = LAYOUT[r]![c]!;
        const x = c * TILE;
        const y = r * TILE;
        switch (ch) {
          case "D":
            g.fillStyle(C.desk).fillRect(x, y + 4, TILE, 12);
            g.fillStyle(C.deskTop).fillRect(x, y + 4, TILE, 4);
            break;
          case "B":
            g.fillStyle(C.boardFrame).fillRect(x, y + 1, TILE, 13);
            g.fillStyle(C.board).fillRect(x + 1, y + 2, TILE - 2, 11);
            g.fillStyle(0x4aa8e8).fillRect(x + 3, y + 4, ((c * 7) % 8) + 3, 1);
            g.fillStyle(0xe8734a).fillRect(x + 3, y + 7, ((c * 5) % 9) + 2, 1);
            g.fillStyle(0x5bbf4a).fillRect(x + 3, y + 10, ((c * 3) % 7) + 3, 1);
            break;
          case "K":
            g.fillStyle(C.shelf).fillRect(x, y, TILE, TILE);
            for (let i = 0; i < 4; i++) {
              const colors = [0xe8734a, 0x4aa8e8, 0xe8c34a, 0x9b6bd6];
              g.fillStyle(colors[(c + i) % 4]!).fillRect(x + 1 + i * 4, y + 2, 3, 5);
              g.fillStyle(colors[(c + i + 2) % 4]!).fillRect(x + 1 + i * 4, y + 9, 3, 5);
            }
            break;
          case "S":
            g.fillStyle(C.sofaDark).fillRect(x, y + 2, TILE, 14);
            g.fillStyle(C.sofa).fillRect(x, y + 6, TILE, 8);
            break;
          case "T":
            g.fillStyle(C.table).fillRect(x, y, TILE, TILE);
            g.fillStyle(0xb8774f).fillRect(x, y, TILE, 2);
            break;
          case "b":
            g.fillStyle(C.bench).fillRect(x, y + 6, TILE, 6);
            g.fillStyle(0x6b4a2f)
              .fillRect(x + 2, y + 12, 2, 4)
              .fillRect(x + 12, y + 12, 2, 4);
            break;
          case "H":
            g.fillStyle(0xd9b24a).fillRect(x + 1, y + 4, 14, 11);
            g.fillStyle(0xf0c93c).fillRect(x + 1, y + 4, 14, 2);
            g.fillStyle(0xb08a30)
              .fillRect(x + 1, y + 9, 14, 1)
              .fillRect(x + 5, y + 4, 1, 11)
              .fillRect(x + 10, y + 4, 1, 11);
            break;
          case "P":
            g.fillStyle(C.pot).fillRect(x + 4, y + 9, 8, 7);
            g.fillStyle(C.leaf).fillCircle(x + 8, y + 6, 6);
            g.fillStyle(0x4a9e3a)
              .fillCircle(x + 5, y + 8, 3)
              .fillCircle(x + 11, y + 7, 3);
            break;
        }
      }
    }
    // monitors (dynamic: lit while their desk's agent works)
    for (const desk of DESKS) {
      const x = desk.monitor.col * TILE;
      const y = desk.monitor.row * TILE;
      this.add
        .rectangle(x + 9, y + 3, 12, 9, C.bezel)
        .setOrigin(0, 0)
        .setDepth(-900);
      this.monitors.push(
        this.add
          .rectangle(x + 10, y + 4, 10, 6, C.screenOff)
          .setOrigin(0, 0)
          .setDepth(-899),
      );
      // at night a lit screen glows through the dark (drawn above the night shade)
      this.glows.push(
        this.add
          .rectangle(x + 10, y + 4, 10, 6, C.screenOn, 0.55)
          .setOrigin(0, 0)
          .setDepth(20_001)
          .setVisible(false),
      );
    }
  }

  private makeIconTextures(): void {
    for (const [name, rows] of Object.entries(ICONS)) {
      const key = `icon:${name}`;
      if (this.textures.exists(key)) continue;
      const tex = this.textures.createCanvas(key, 8, 8)!;
      paintIcon(tex.context, rows, 0);
      tex.refresh();
    }
    const art: [string, string[], Record<string, string>][] = [
      ["bubble:moo:ru", bubbleRows("МУ!"), BUBBLE_COLORS],
      ["bubble:moo:en", bubbleRows("MOO!"), BUBBLE_COLORS],
      ["bubble:zzz", bubbleRows("Zz"), BUBBLE_COLORS],
      ["envelope", ENVELOPE, ENVELOPE_COLORS],
      ...Object.entries(PETS).map(([name, rows]): [string, string[], Record<string, string>] => [`pet:${name}`, rows, PET_COLORS]),
    ];
    for (const [key, rows, colors] of art) {
      if (this.textures.exists(key)) continue;
      const tex = this.textures.createCanvas(key, rows[0]!.length, rows.length)!;
      paintRows(tex.context, rows, colors);
      tex.refresh();
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
        existing.label.setText(agent.name);
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
    sprite.on("pointerdown", (p: Phaser.Input.Pointer) => {
      p.event.stopPropagation();
      this.bus.emit("selected", agent.id);
      this.select(agent.id);
      if (isCow) this.countCowClick(agent.id);
    });
    const icon = this.add.image(x, y - 16, "icon:check").setVisible(false);
    const label = this.add
      .text(x, y + 4, agent.name, {
        fontFamily: "ui-monospace, monospace",
        fontSize: "6px",
        color: "#f6efdc",
        stroke: "#0c1024",
        strokeThickness: 2,
        resolution: 6,
      })
      .setOrigin(0.5, 0)
      .setVisible(false);
    sprite.on("pointerover", () => label.setVisible(true));
    sprite.on("pointerout", () => label.setVisible(this.selected === agent.id));
    const character: Character = {
      agent,
      sprite,
      icon,
      label,
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
    };
    if (agent.kind === "autonomous") {
      // persistent agents keep their own desk, with their pet on it
      character.desk = this.seats.seat("desk", agent.id);
      const desk = DESKS[character.desk]!;
      character.pet = this.add
        .image((desk.monitor.col + 1) * TILE + 5, desk.monitor.row * TILE + 5, `pet:${petFor(agent.id)}`)
        .setOrigin(0, 1)
        .setDepth(-880);
      this.tweens.add({
        targets: character.pet,
        y: character.pet.y - 1,
        duration: 260,
        yoyo: true,
        repeat: -1,
        repeatDelay: 1800 + (petFor(agent.id).length * 377) % 1500,
      });
    }
    this.characters.set(agent.id, character);
    this.route(character);
  }

  private leave(character: Character): void {
    character.leaving = true;
    character.icon.setVisible(false);
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
    const path = findPath(character.cell, { col: spot.col, row: spot.row }, walkable);
    character.path = path ? path.slice(1) : [];
    character.icon.setVisible(false);
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
        : ZONES[cow.place][this.seats.seat(cow.place, character.agent.id)] ?? ZONES[cow.place][0]!;
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
    this.drawWindows(env.hour);
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

  /** Windows in the top wall look out onto the meadow from the logo; so does the gate. */
  private drawWindows(hour: number): void {
    const sky = skyFor(hour);
    const g = this.windows.clear();
    const view = (x: number, y: number, w: number, h: number, seed: number) => {
      g.fillStyle(sky.sky[0]).fillRect(x, y, w, Math.ceil(h / 2));
      g.fillStyle(sky.sky[1]).fillRect(x, y + Math.ceil(h / 2), w, Math.floor(h / 2));
      if (sky.stars) {
        g.fillStyle(0xffffff)
          .fillRect(x + ((seed * 3) % (w - 1)), y + 1, 1, 1)
          .fillRect(x + ((seed * 7 + 4) % (w - 1)), y + 2, 1, 1);
      }
      if (seed % 3 === 1 && (sky.sun || sky.moon)) {
        g.fillStyle(sky.sun ? 0xffd34a : 0xf6efdc).fillRect(x + w - 4, y + 1, 2, 2);
      }
      // rolling hills
      g.fillStyle(sky.hill).fillRect(x, y + h - 2, w, 2);
      g.fillRect(x + ((seed * 5) % Math.max(1, w - 5)), y + h - 3, 5, 1);
      if (seed % 4 === 0) {
        // a tiny cow grazing outside
        g.fillStyle(0xffffff).fillRect(x + 2, y + h - 4, 3, 2);
        g.fillStyle(0x1b1b2e).fillRect(x + 3, y + h - 4, 1, 1);
      }
    };
    for (let c = 2; c < COLS; c += 5) {
      if (LAYOUT[0]![c] !== "#") continue;
      g.fillStyle(0xf6efdc).fillRect(c * TILE + 1, 3, TILE - 2, 9); // frame
      view(c * TILE + 2, 4, TILE - 4, 7, c);
    }
    // the meadow gate next to the pasture (right wall)
    const gx = (COLS - 1) * TILE + 3;
    const gy = 11 * TILE + 2;
    g.fillStyle(0x8a5a3b).fillRect(gx - 2, gy - 2, 13, TILE * 3);
    view(gx, gy, 9, TILE * 3 - 6, 4);
    g.fillStyle(0xf6efdc)
      .fillRect(gx, gy + TILE * 2 - 4, 9, 1)
      .fillRect(gx + 2, gy + TILE * 2 - 6, 1, 6)
      .fillRect(gx + 6, gy + TILE * 2 - 6, 1, 6); // fence
  }

  private arrive(character: Character): void {
    if (character.leaving) {
      character.sprite.destroy();
      character.icon.destroy();
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
    if (indicator === "none") character.icon.setVisible(false);
    else character.icon.setTexture(`icon:${indicator}`).setVisible(true);
    this.refreshMonitors();
  }

  private applyCowPose(character: Character): void {
    const cow = character.cow!;
    const mooing = character.mooUntil > this.time.now;
    // at the end of a patrol leg the cow stands for a moment, handing papers over
    const pose = mooing ? "moo" : cow.place === "patrol" ? "stand" : cow.pose;
    if (cow.animated || mooing) character.sprite.play(this.animKey(character, pose), true);
    else character.sprite.stop();
    character.sprite.setAlpha(pose === "frozen" ? 0.65 : 1);
    if (cow.indicator === "none" || mooing) character.icon.setVisible(false);
    else character.icon.setTexture(`icon:${cow.indicator}`).setVisible(true);
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
    this.monitors.forEach((m, i) => m.setFillStyle(lit.has(i) ? C.screenOn : C.screenOff));
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

  select(id: string | null): void {
    this.selected = id;
    this.ring.setVisible(id !== null && this.characters.has(id));
    this.ring.setSize(id !== null && this.characters.get(id)?.cow ? 22 : 14, 5);
    for (const [agentId, c] of this.characters) c.label.setVisible(agentId === id);
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
      c.sprite.setDepth(c.sprite.y);
      c.icon
        .setPosition(Math.round(c.sprite.x + (c.cow ? 6 : 0)), Math.round(c.sprite.y - (c.cow ? 21 : 19)))
        .setDepth(c.sprite.y + 1);
      c.label.setPosition(Math.round(c.sprite.x), Math.round(c.sprite.y + 3)).setDepth(c.sprite.y + 2);
      c.bubble?.setPosition(Math.round(c.sprite.x + 4), Math.round(c.sprite.y - 17)).setDepth(30_000);
      if (this.selected === c.agent.id) this.ring.setPosition(c.sprite.x, c.sprite.y + 1);
    }
    this.handlePinch();
    this.clampCamera();
    if (time - this.lastPublish > 300) {
      this.lastPublish = time;
      this.publishState();
    }
  }

  /** Read-only snapshot for tests and assistive tech: what is drawn where (CSS px). */
  private publishState(): void {
    const cam = this.cameras.main;
    const state = [...this.characters.values()]
      .filter((c) => !c.leaving)
      .map((c) => ({
        id: c.agent.id,
        status: c.agent.status,
        kind: c.agent.kind,
        pose: c.cow ? (c.path.length ? (c.cow.place === "patrol" ? "carry" : "walk") : c.cow.pose) : c.path.length ? "walk" : c.behavior.pose,
        bubble: c.cow && c.bubble?.visible ? c.cow.bubble : undefined,
        pet: c.pet ? petFor(c.agent.id) : undefined,
        x: Math.round((c.sprite.x - cam.worldView.x) * cam.zoom),
        y: Math.round((c.sprite.y - 6 - cam.worldView.y) * cam.zoom),
      }));
    this.game.canvas.dataset.agents = JSON.stringify(state);
  }

  // --- camera -----------------------------------------------------------------------------

  /**
   * Largest integer zoom (pixel-perfect, spec 18.6) that shows the whole office, centred.
   * Narrow screens stay at zoom 1 and pan by drag.
   */
  private fit(): void {
    const cam = this.cameras.main;
    const zoom = Math.floor(Math.min(this.scale.width / WORLD_W, this.scale.height / WORLD_H));
    cam.setZoom(Phaser.Math.Clamp(zoom, MIN_ZOOM, MAX_ZOOM));
    cam.centerOn(WORLD_W / 2, WORLD_H / 2);
    this.clampCamera();
  }

  /** Keep the office in view; centre it when it is smaller than the view. */
  private clampCamera(): void {
    const cam = this.cameras.main;
    const viewW = cam.width / cam.zoom;
    const viewH = cam.height / cam.zoom;
    // The view's centre in world units (Camera.midPoint is only refreshed at render time).
    const mid = {
      x: cam.scrollX + cam.width / 2,
      y: cam.scrollY + cam.height / 2,
    };
    const cx = viewW >= WORLD_W ? WORLD_W / 2 : Phaser.Math.Clamp(mid.x, viewW / 2, WORLD_W - viewW / 2);
    const cy = viewH >= WORLD_H ? WORLD_H / 2 : Phaser.Math.Clamp(mid.y, viewH / 2, WORLD_H - viewH / 2);
    if (Math.abs(cx - mid.x) > 0.01 || Math.abs(cy - mid.y) > 0.01) cam.centerOn(cx, cy);
  }

  private zoomBy(step: number): void {
    const cam = this.cameras.main;
    const center = {
      x: cam.scrollX + cam.width / 2,
      y: cam.scrollY + cam.height / 2,
    };
    cam.setZoom(Phaser.Math.Clamp(Math.round(cam.zoom) + step, MIN_ZOOM, MAX_ZOOM)); // integer zoom: pixel-perfect
    cam.centerOn(center.x, center.y);
    this.clampCamera();
  }

  private setupInput(): void {
    this.input.addPointer(1);
    this.input.on("pointerdown", (p: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]) => {
      this.dragging = over.length === 0;
      if (over.length === 0 && !this.input.pointer2.isDown) {
        this.bus.emit("selected", null);
        this.select(null);
      }
    });
    this.input.on("pointerup", () => {
      this.dragging = false;
    });
    this.input.on("pointermove", (p: Phaser.Input.Pointer) => {
      if (!p.isDown || !this.dragging || this.input.pointer2.isDown) return;
      const cam = this.cameras.main;
      cam.scrollX -= (p.x - p.prevPosition.x) / cam.zoom;
      cam.scrollY -= (p.y - p.prevPosition.y) / cam.zoom;
    });
    this.input.on("wheel", (_p: unknown, _o: unknown, _dx: number, dy: number) => this.zoomBy(dy > 0 ? -1 : 1));
  }

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
    if (distance / this.pinchStart > 1.3) {
      this.zoomBy(1);
      this.pinchStart = distance;
    } else if (distance / this.pinchStart < 0.77) {
      this.zoomBy(-1);
      this.pinchStart = distance;
    }
  }
}
