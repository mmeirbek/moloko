/**
 * Spec 18.4: every backend status has exactly one visual behaviour. The office only
 * *renders* the status it receives — it never decides or changes it.
 */
import type { ZoneName } from "./map";

export type AgentStatus = "idle" | "planning" | "working" | "waiting" | "reviewing" | "paused" | "completed" | "failed";

export type Pose = "rest" | "think" | "type" | "wait" | "read" | "frozen" | "cheer" | "slump";
export type Indicator = "none" | "thinking" | "hourglass" | "document" | "pause" | "check" | "alert";

export interface Behavior {
  /** where the character goes; "desk" = its own workstation */
  place: "desk" | ZoneName | "stay";
  pose: Pose;
  indicator: Indicator;
  /** animate the pose (paused agents are frozen) */
  animated: boolean;
}

export const BEHAVIOR: Record<AgentStatus, Behavior> = {
  idle: { place: "lounge", pose: "rest", indicator: "none", animated: true }, // resting
  planning: {
    place: "board",
    pose: "think",
    indicator: "thinking",
    animated: true,
  }, // looking at board
  working: { place: "desk", pose: "type", indicator: "none", animated: true }, // typing at computer
  waiting: {
    place: "waiting",
    pose: "wait",
    indicator: "hourglass",
    animated: true,
  }, // waiting pose
  reviewing: {
    place: "review",
    pose: "read",
    indicator: "document",
    animated: true,
  }, // studying documents
  paused: {
    place: "stay",
    pose: "frozen",
    indicator: "pause",
    animated: false,
  }, // frozen + indicator
  completed: {
    place: "desk",
    pose: "cheer",
    indicator: "check",
    animated: true,
  }, // completion gesture
  failed: { place: "desk", pose: "slump", indicator: "alert", animated: true }, // error indicator
};

export function behaviorFor(status: string): Behavior {
  return BEHAVIOR[status as AgentStatus] ?? BEHAVIOR.idle;
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
    case "working":
      return { place: "patrol", pose: "carry", indicator: "none", bubble: null, animated: true };
    case "waiting":
      return { place: "pasture", pose: "stand", indicator: "hourglass", bubble: null, animated: true };
    case "reviewing":
      return { place: "review", pose: "stand", indicator: "document", bubble: null, animated: true };
    case "completed":
      return { place: "pasture", pose: "cheer", indicator: "check", bubble: null, animated: true };
    case "failed":
      return { place: "pasture", pose: "sad", indicator: "alert", bubble: null, animated: true };
  }
}
