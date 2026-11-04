import type { AgentCreate } from "@moloko/shared-types";

/**
 * Every agent is an exotic animal (owner: «агенты — животные по своим иконкам; экзотические,
 * необычные виды — не просто тигр, а амурский тигр»), plus an accessory and an expression,
 * drawn in code (agent-avatar.tsx — all original art, listed in assets/MANIFEST.md). The
 * species is the agent's own (`agent.animal`: chosen by the owner or at random by the server);
 * the accessory and the expression are spread so that no two agents of the office look the
 * same, and an agent keeps its face when others are added: the oldest agents choose first.
 * Pure: tested.
 */

/** The same list as the server's (app/agents/looks.py): the generated API type checks each name,
 *  and a test checks that none is missing. */
export const ANIMALS = [
  "amur_tiger",
  "snow_leopard",
  "pallas_cat",
  "fennec_fox",
  "red_panda",
  "capybara",
  "axolotl",
  "quokka",
  "okapi",
  "tarsier",
  "ring_tailed_lemur",
  "malayan_tapir",
  "sea_otter",
  "atlantic_puffin",
  "three_toed_sloth",
  "platypus",
  "barn_owl",
  "saiga",
  "mandrill",
  "emperor_tamarin",
] as const satisfies readonly NonNullable<AgentCreate["animal"]>[];
export const ACCESSORIES = ["none", "shades", "cap", "headphones", "party", "bowtie", "glasses", "beanie"] as const;
export const EXPRESSIONS = ["happy", "smug", "side", "dot"] as const;
/** Soft backgrounds that read on light and graphite pages. */
export const BACKDROPS = ["#f9d6a5", "#bfe3c0", "#c8d8f7", "#f4c2d0", "#e2d3f5", "#f6e7a6", "#bfe7e6", "#f3c9b4"] as const;

export type Species = (typeof ANIMALS)[number];
/** The moloko cow is the Orchestrator's alone. */
export type Animal = Species | "cow";
export type Accessory = (typeof ACCESSORIES)[number] | "crown";
export type Expression = (typeof EXPRESSIONS)[number];

export interface Look {
  animal: Animal;
  accessory: Accessory;
  expression: Expression;
  backdrop: string;
}

const STYLES = ACCESSORIES.length * EXPRESSIONS.length; // accessory × expression per species
/** The Orchestrator is the boss: the moloko cow with a crown. Nobody else gets it. */
export const BOSS_LOOK: Look = { animal: "cow", accessory: "crown", expression: "smug", backdrop: BACKDROPS[5] };

export const isSpecies = (value: unknown): value is Species => ANIMALS.includes(value as Species);

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function styled(animal: Species, style: number, seed: number): Look {
  return {
    animal,
    accessory: ACCESSORIES[style % ACCESSORIES.length]!,
    expression: EXPRESSIONS[Math.floor(style / ACCESSORIES.length) % EXPRESSIONS.length]!,
    backdrop: BACKDROPS[seed % BACKDROPS.length]!,
  };
}

export interface LookAgent {
  id: string;
  created_at?: string | null;
  agent_type?: string | null;
  animal?: string | null;
}

/** id → look for the whole office. Without a stored species the least used one is taken. */
export function assignLooks(agents: LookAgent[]): Map<string, Look> {
  const looks = new Map<string, Look>();
  const taken = new Set<string>();
  const used = new Map<Species, number>();
  for (const a of agents) if (isSpecies(a.animal)) used.set(a.animal, (used.get(a.animal) ?? 0) + 1);
  const ordered = [...agents].sort(
    (a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? "") || a.id.localeCompare(b.id),
  );
  for (const agent of ordered) {
    if (agent.agent_type === "orchestrator") {
      looks.set(agent.id, BOSS_LOOK);
      continue;
    }
    const h = hash(agent.id);
    let animal: Species;
    if (isSpecies(agent.animal)) animal = agent.animal;
    else {
      const fewest = Math.min(...ANIMALS.map((a) => used.get(a) ?? 0));
      const candidates = ANIMALS.filter((a) => (used.get(a) ?? 0) === fewest);
      animal = candidates[h % candidates.length]!;
      used.set(animal, (used.get(animal) ?? 0) + 1);
    }
    // A free accessory × expression of that species (several agents may share one).
    let style = h % STYLES;
    for (let k = 0; k < STYLES; k++) {
      const s = (h + k) % STYLES;
      if (!taken.has(`${animal}/${s}`)) {
        style = s;
        break;
      }
    }
    taken.add(`${animal}/${style}`);
    looks.set(agent.id, styled(animal, style, h));
  }
  return looks;
}

/** A face for an agent the office does not list (e.g. removed): from what is known of it. */
export function lookOf(id: string, animal?: string | null): Look {
  const h = hash(id);
  return styled(isSpecies(animal) ? animal : ANIMALS[h % ANIMALS.length]!, h % STYLES, h);
}

/** How an agent feels right now, from its status (the face shows it). */
export type Mood = "calm" | "busy" | "thinking" | "waiting" | "happy" | "sad" | "sleepy";

export function moodOf(status: string | null | undefined): Mood {
  switch (status) {
    case "working":
    case "reviewing":
    case "running": // a task's status
      return "busy";
    case "planning":
      return "thinking";
    case "waiting":
    case "waiting_approval":
    case "waiting_input":
      return "waiting";
    case "completed":
      return "happy";
    case "failed":
      return "sad";
    case "paused":
      return "sleepy";
    default:
      return "calm";
  }
}
