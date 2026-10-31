import { describe, expect, it } from "vitest";

import { parseFrame, readSse } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

describe("sse", () => {
  it("parses events split across chunks and skips heartbeats", async () => {
    const body = streamOf([
      'event: message.delta\ndata: {"text":"Hel',
      'lo"}\n\n: ping\n\nevent: message.completed\n',
      'data: {"message":{"id":"1"}}\n\n',
    ]);
    const events = [];
    for await (const e of readSse(body)) events.push(e);
    expect(events).toEqual([
      { event: "message.delta", data: { text: "Hello" } },
      { event: "message.completed", data: { message: { id: "1" } } },
    ]);
  });

  it("ignores malformed frames", () => {
    expect(parseFrame("event: x\ndata: {not json")).toBeNull();
    expect(parseFrame(": comment only")).toBeNull();
  });
});
