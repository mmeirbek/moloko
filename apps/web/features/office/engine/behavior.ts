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
