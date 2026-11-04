/**
 * «@Кодер почини форму» or «Кодер, почини форму»: a message to one agent becomes its task
 * (owner's decision 2026-11-03 — one line, the agent named in the text). Pure: tested.
 */

export interface MentionAgent {
  id: string;
  name: string;
  /** The Orchestrator: its task starts through /runs (it is created on first use). */
  orchestrator?: boolean;
}

export interface Mention {
  agent: MentionAgent;
  /** The task itself, without the name. */
  text: string;
}

const norm = (s: string) => s.toLocaleLowerCase("ru").replace(/\s+/g, " ");

/** The agent the message starts with — the longest name wins («Кодер король» over «Кодер»). */
export function parseAgentMention(message: string, agents: MentionAgent[]): Mention | null {
  const text = message.trimStart();
  const at = text.startsWith("@");
  const body = at ? text.slice(1) : text;
  const lower = norm(body);
  const byLength = [...agents].sort((a, b) => b.name.length - a.name.length);
  for (const agent of byLength) {
    const name = norm(agent.name.trim());
    if (!name || !lower.startsWith(name)) continue;
    const after = body.slice(agent.name.trim().length);
    // «@Name task» needs only a space; without @ the name must be followed by «,» or «:»
    // (so an ordinary sentence that starts with a word like an agent's name stays a chat).
    const sep = at ? /^[\s,:—-]+/ : /^\s*[,:]\s*/;
    const match = sep.exec(after);
    if (!match) continue;
    const task = after.slice(match[0].length).trim();
    if (task) return { agent, text: task };
  }
  return null;
}

/** While the owner types «@Ко…»: the agents whose names start with it (none once one fits). */
export function mentionSuggestions(message: string, agents: MentionAgent[]): MentionAgent[] {
  if (!message.startsWith("@") || /\n/.test(message)) return [];
  const typed = norm(message.slice(1));
  if (agents.some((a) => typed.startsWith(`${norm(a.name.trim())} `))) return [];
  return agents.filter((a) => norm(a.name.trim()).startsWith(typed.trimStart())).slice(0, 6);
}

/** A task title from its text: the first line, cut at a word. */
export function taskTitle(text: string, max = 60): string {
  const line = text.split("\n").find((l) => l.trim())?.trim() ?? text.trim();
  if (line.length <= max) return line;
  const cut = line.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${space > max / 2 ? cut.slice(0, space) : cut}…`;
}
