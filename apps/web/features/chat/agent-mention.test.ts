import { describe, expect, it } from "vitest";

import { mentionSuggestions, parseAgentMention, taskTitle } from "./agent-mention";

const agents = [
  { id: "1", name: "Кодер" },
  { id: "2", name: "Кодер король" },
  { id: "3", name: "Researcher" },
];

describe("a message to one agent", () => {
  it("starts with @name or «name,» and the longest name wins", () => {
    expect(parseAgentMention("@Кодер король почини форму", agents)).toEqual({ agent: agents[1], text: "почини форму" });
    expect(parseAgentMention("@кодер почини форму", agents)).toEqual({ agent: agents[0], text: "почини форму" });
    expect(parseAgentMention("Researcher: найди три статьи", agents)).toEqual({ agent: agents[2], text: "найди три статьи" });
    expect(parseAgentMention("кодер король, сделай тесты\nи прогони их", agents)?.text).toBe("сделай тесты\nи прогони их");
  });

  it("leaves ordinary messages and empty mentions to the chat", () => {
    expect(parseAgentMention("Кодер король умеет писать тесты?", agents)).toBeNull();
    expect(parseAgentMention("@Кодер", agents)).toBeNull();
    expect(parseAgentMention("@Никто сделай", agents)).toBeNull();
    expect(parseAgentMention("Как дела?", agents)).toBeNull();
  });

  it("suggests agents while the name is being typed", () => {
    expect(mentionSuggestions("@ко", agents).map((a) => a.id)).toEqual(["1", "2"]);
    expect(mentionSuggestions("@", agents)).toHaveLength(3);
    expect(mentionSuggestions("@Кодер король почини", agents)).toEqual([]);
    expect(mentionSuggestions("привет", agents)).toEqual([]);
  });

  it("names the task after its first line", () => {
    expect(taskTitle("почини форму входа\nподробности")).toBe("почини форму входа");
    expect(taskTitle("слово ".repeat(20)).endsWith("…")).toBe(true);
  });
});
