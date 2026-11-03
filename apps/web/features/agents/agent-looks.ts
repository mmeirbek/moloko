/**
 * Every agent gets its own face (owner: «иконки для всех агентов, чтоб легко отличать, и более
 * мемные»): an animal, an accessory and an expression, drawn in code (agent-avatar.tsx — all
 * original art, listed in assets/MANIFEST.md). No two agents of the office look the same, and an
 * agent keeps its face when others are added: the oldest agents choose first. Pure: tested.
 */

export const ANIMALS = ["cow", "cat", "dog", "frog", "raccoon", "penguin", "fox", "bear", "owl", "panda", "pig", "bunny"] as const;
export const ACCESSORIES = ["shades", "cap", "headphones", "crown", "party", "bowtie", "glasses", "beanie"] as const;
export const EXPRESSIONS = ["happy", "smug", "side", "dot"] as const;
/** Soft backgrounds that read on light and graphite pages. */
export const BACKDROPS = ["#f9d6a5", "#bfe3c0", "#c8d8f7", "#f4c2d0", "#e2d3f5", "#f6e7a6", "#bfe7e6", "#f3c9b4"] as const;

export type Animal = (typeof ANIMALS)[number];
export type Accessory = (typeof ACCESSORIES)[number];
export type Expression = (typeof EXPRESSIONS)[number];

export interface Look {
  animal: Animal;
  accessory: Accessory;
  expression: Expression;
  backdrop: string;
}

const SLOTS = ANIMALS.length * ACCESSORIES.length * EXPRESSIONS.length;
/** The Orchestrator is the boss: the moloko cow with a crown. Nobody else gets it. */
export const BOSS_LOOK: Look = { animal: "cow", accessory: "crown", expression: "smug", backdrop: BACKDROPS[5] };

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function lookAt(slot: number, seed: number): Look {
  const animal = ANIMALS[slot % ANIMALS.length]!;
  const accessory = ACCESSORIES[Math.floor(slot / ANIMALS.length) % ACCESSORIES.length]!;
  const expression = EXPRESSIONS[Math.floor(slot / (ANIMALS.length * ACCESSORIES.length)) % EXPRESSIONS.length]!;
  return { animal, accessory, expression, backdrop: BACKDROPS[seed % BACKDROPS.length]! };
}

const isBoss = (l: Look) => l.animal === "cow" && l.accessory === "crown";

export interface LookAgent {
  id: string;
  created_at?: string | null;
  agent_type?: string | null;
}

/** id → look for the whole office. Animals are spread first (a new agent rarely shares one). */
export function assignLooks(agents: LookAgent[]): Map<string, Look> {
  const looks = new Map<string, Look>();
  const taken = new Set<number>();
  const animalsUsed = new Map<Animal, number>();
  const ordered = [...agents].sort(
    (a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? "") || a.id.localeCompare(b.id),
  );
  for (const agent of ordered) {
    if (agent.agent_type === "orchestrator") {
      looks.set(agent.id, BOSS_LOOK);
      continue;
    }
    const h = hash(agent.id);
    // Prefer the least used animal (ties broken by the agent's own hash), then a free slot of it.
    const fewest = Math.min(...ANIMALS.map((a) => animalsUsed.get(a) ?? 0));
    const candidates = ANIMALS.map((a, i) => ({ a, i })).filter(({ a }) => (animalsUsed.get(a) ?? 0) === fewest);
    const pick = candidates[h % candidates.length]!;
    let slot = -1;
    for (let k = 0; k < SLOTS / ANIMALS.length; k++) {
      const s = pick.i + ANIMALS.length * ((Math.floor(h / ANIMALS.length) + k) % (SLOTS / ANIMALS.length));
      if (!taken.has(s) && !isBoss(lookAt(s, h))) {
        slot = s;
        break;
      }
    }
    if (slot < 0) slot = h % SLOTS; // more agents than faces: a repeat is all that is left
    taken.add(slot);
    const look = lookAt(slot, h);
    animalsUsed.set(look.animal, (animalsUsed.get(look.animal) ?? 0) + 1);
    looks.set(agent.id, look);
  }
  return looks;
}

/** A face for an agent the office does not list (e.g. removed): from its id alone. */
export function lookOf(id: string): Look {
  const h = hash(id);
  const look = lookAt(h % SLOTS, h);
  return isBoss(look) ? { ...look, accessory: "party" } : look;
}
