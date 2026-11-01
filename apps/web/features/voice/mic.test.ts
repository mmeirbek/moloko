import { describe, expect, it } from "vitest";

import { extensionFor, pickType } from "./mic-button";

describe("voice recorder format", () => {
  it("prefers webm/opus, falls back to mp4 on Safari", () => {
    expect(pickType(() => true)).toBe("audio/webm;codecs=opus");
    expect(pickType((t) => t === "audio/mp4")).toBe("audio/mp4");
    expect(pickType(() => false)).toBeUndefined();
  });
  it("names the file by format", () => {
    expect(extensionFor("audio/mp4")).toBe("m4a");
    expect(extensionFor("audio/ogg;codecs=opus")).toBe("ogg");
    expect(extensionFor("audio/webm")).toBe("webm");
  });
});
