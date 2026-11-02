/**
 * Spec 18.4: every backend status has exactly one visual behaviour. The office only
 * *renders* the status it receives — it never decides or changes it.
 *
 * Owner's rule (2026-11-02): an agent does not leave its desk until the task is fully done —
 * thinking, waiting and reviewing are poses at the desk, not trips across the office — and
 * between tasks it rests at its desk too. The lounge is only for agents without a free desk.
 */
import type { ZoneName } from "./map";

export type AgentStatus = "idle" | "planning" | "working" | "waiting" | "reviewing" | "paused" | "completed" | "failed";

export type Pose = "rest" | "think" | "type" | "wait" | "read" | "frozen" | "cheer" | "slump";
export type Indicator = "none" | "thinking" | "hourglass" | "document" | "pause" | "check" | "alert";
/** The progress bar over the head: "live" = busy with a task, "frozen" = paused (grey, still), "none" = hidden. */
export type HudMode = "live" | "frozen" | "none";

export interface Behavior {
  /** where the character goes; "desk" = its own workstation */
  place: "desk" | ZoneName | "stay";
  pose: Pose;
  indicator: Indicator;
  /** animate the pose (paused agents are frozen) */
  animated: boolean;
  /** progress over the head (engine/hud.ts); nothing while resting or done */
  hud: HudMode;
}

export const BEHAVIOR: Record<AgentStatus, Behavior> = {
  idle: { place: "desk", pose: "rest", indicator: "none", animated: true, hud: "none" }, // resting at its desk
  planning: {
    place: "desk",
    pose: "think",
    indicator: "thinking",
    animated: true,
    hud: "live",
  }, // thinking at its desk
  working: { place: "desk", pose: "type", indicator: "none", animated: true, hud: "live" }, // typing at computer
  waiting: {
    place: "desk",
    pose: "wait",
    indicator: "hourglass",
    animated: true,
    hud: "live",
  }, // waiting pose
  reviewing: {
    place: "desk",
    pose: "read",
    indicator: "document",
    animated: true,
    hud: "live",
  }, // studying documents
  paused: {
    place: "stay",
    pose: "frozen",
    indicator: "pause",
    animated: false,
    hud: "frozen",
  }, // frozen + indicator
  completed: {
    place: "desk",
    pose: "cheer",
    indicator: "check",
    animated: true,
    hud: "none",
  }, // completion gesture
  failed: { place: "desk", pose: "slump", indicator: "alert", animated: true, hud: "none" }, // error indicator
};

export function behaviorFor(status: string): Behavior {
  return BEHAVIOR[status as AgentStatus] ?? BEHAVIOR.idle;
}

/** Whether (and how) the progress bar shows over this status' head — the cow included. */
export function hudModeFor(status: string): HudMode {
  return behaviorFor(status).hud;
}

// --- the cow (the Orchestrator) -----------------------------------------------------------

export type CowPose = "stand" | "graze" | "carry" | "moo" | "sad" | "sleep" | "cheer" | "frozen";
export type Bubble = "moo" | "zzz" | null;

export interface CowBehavior {
  /** "patrol" = walk from agent to agent handing out work and collecting results */
  place: "pasture" | "board" | "review" | "patrol" | "stay";
  pose: CowPose;
  indicator: Indicator;
  bubble: Bubble;
  animated: boolean;
}

/**
 * The Orchestrator is drawn as the moloko cow. Same rule as everyone else: its look
 * comes only from the backend status, plus two facts the office is told — the owner's
 * night (22:00–06:00 local) and whether an approval is waiting. Pure: tested.
 */
export function cowBehaviorFor(status: string, { night = false, attention = false } = {}): CowBehavior {
  const s = (status in BEHAVIOR ? status : "idle") as AgentStatus;
  if (s === "paused") return { place: "stay", pose: "frozen", indicator: "pause", bubble: null, animated: false };
  if (attention) return { place: "pasture", pose: "moo", indicator: "none", bubble: "moo", animated: true };
  switch (s) {
    case "idle":
      return night
        ? { place: "pasture", pose: "sleep", indicator: "none", bubble: "zzz", animated: true }
        : { place: "pasture", pose: "graze", indicator: "none", bubble: null, animated: true };
    case "planning":
      return { place: "board", pose: "stand", indicator: "thinking", bubble: null, animated: true };
    case "working": // stays by the task board while its team works (no walking from desk to desk)
      return { place: "board", pose: "stand", indicator: "none", bubble: null, animated: true };
    case "waiting":
      return { place: "pasture", pose: "stand", indicator: "hourglass", bubble: null, animated: true };
    case "reviewing":
      return { place: "board", pose: "stand", indicator: "document", bubble: null, animated: true };
    case "completed":
      return { place: "pasture", pose: "cheer", indicator: "check", bubble: null, animated: true };
    case "failed":
      return { place: "pasture", pose: "sad", indicator: "alert", bubble: null, animated: true };
  }
}
