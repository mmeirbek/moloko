/**
 * The Pixel Office scene (Phaser 3). It ONLY renders: agents come in through the bus
 * from the realtime store; the scene never changes agent state (spec 4.4, 18.7).
 */
import * as Phaser from "phaser";

import { SeatAssigner } from "./assign";
import { behaviorFor, type Behavior } from "./behavior";
import type { OfficeAgent, OfficeBus } from "./bus";
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
}

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
    door: ZONES.door.length,
  });
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
          if (r === 0 && c % 5 === 2) g.fillStyle(C.window).fillRect(x + 2, y + 4, TILE - 4, 7);
          continue;
        }
        g.fillStyle((r + c) % 2 ? C.floorA : C.floorB).fillRect(x, y, TILE, TILE);
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
    const key = this.ensureAgentTexture(agent);
    const door = ZONES.door[this.seats.seat("door", agent.id)]!;
    const { x, y } = tileCenter(door.col, door.row);
    const sprite = this.add.sprite(x, y, key, "stand").setOrigin(0.5, 0.85).setInteractive({ useHandCursor: true });
    sprite.on("pointerdown", (p: Phaser.Input.Pointer) => {
      p.event.stopPropagation();
      this.bus.emit("selected", agent.id);
      this.select(agent.id);
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
    };
    this.characters.set(agent.id, character);
    this.route(character);
  }

  private leave(character: Character): void {
    character.leaving = true;
    character.icon.setVisible(false);
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

  private route(character: Character): void {
    const behavior = behaviorFor(character.agent.status);
    character.behavior = behavior;
    // free spots in other zones (desks stay reserved for the agent's lifetime)
    for (const zone of ["lounge", "board", "waiting", "review", "meeting"] as const) {
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
    character.sprite.play(`agent:${character.agent.id}:walk`, true);
  }

  private arrive(character: Character): void {
    if (character.leaving) {
      character.sprite.destroy();
      character.icon.destroy();
      character.label.destroy();
      this.seats.releaseAll(character.agent.id);
      this.characters.delete(character.agent.id);
      if (this.selected === character.agent.id) this.select(null);
      this.refreshMonitors();
      return;
    }
    this.applyPose(character);
  }

  private applyPose(character: Character): void {
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

  private refreshMonitors(): void {
    const lit = new Set<number>();
    for (const c of this.characters.values()) {
      if (c.desk !== null && !c.leaving && c.path.length === 0 && c.agent.status === "working") lit.add(c.desk);
    }
    this.monitors.forEach((m, i) => m.setFillStyle(lit.has(i) ? C.screenOn : C.screenOff));
  }

  private flyEnvelope(from: string, to: string): void {
    const a = this.characters.get(from);
    const b = this.characters.get(to);
    if (!a || !b) return;
    const env = this.add.image(a.sprite.x, a.sprite.y - 12, "icon:envelope").setDepth(10_000);
    this.tweens.add({
      targets: env,
      x: b.sprite.x,
      y: b.sprite.y - 12,
      duration: 900,
      ease: "Sine.easeInOut",
      onComplete: () => env.destroy(),
    });
  }

  select(id: string | null): void {
    this.selected = id;
    this.ring.setVisible(id !== null && this.characters.has(id));
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
      c.icon.setPosition(Math.round(c.sprite.x), Math.round(c.sprite.y - 19)).setDepth(c.sprite.y + 1);
      c.label.setPosition(Math.round(c.sprite.x), Math.round(c.sprite.y + 3)).setDepth(c.sprite.y + 2);
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
        pose: c.path.length ? "walk" : c.behavior.pose,
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
