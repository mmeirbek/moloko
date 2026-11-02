import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import en from "@/messages/en.json";
import ru from "@/messages/ru.json";

import { OFFSITE_ERROR_CODES, OFFSITE_WARNINGS, type Offsite, offsiteState } from "./offsite-state";

const repoFile = (path: string) => readFileSync(new URL(`../../../../${path}`, import.meta.url), "utf8");

const off = { enabled: false } as Offsite;
const on = (extra: Partial<Offsite> = {}) =>
  ({
    enabled: true,
    kind: "s3",
    last_copy: { at: "2026-11-02T03:05:00Z", snapshot: "2466100c" },
    ...extra,
  }) as Offsite;

describe("off-site copies state", () => {
  it("is off, protected, or a problem", () => {
    expect(offsiteState(off, ["offsite_off"]).state).toBe("off");
    expect(offsiteState(on(), ["same_disk"])).toEqual({ state: "protected", problems: [] });
    expect(offsiteState(on({ last_copy: null }), ["offsite_no_copy_yet"]).state).toBe("problem");
    expect(offsiteState(on(), ["offsite_drill_failed", "low_disk"])).toEqual({
      state: "problem",
      problems: ["offsite_drill_failed"],
    });
  });

  it("knows every off-site warning the backend sends", () => {
    const sent = new Set(repoFile("apps/api/app/services/storage.py").match(/"offsite_[a-z_]+"/g));
    sent.delete('"offsite_off"'); // shown as the "off" state, not as a warning
    expect([...sent].map((w) => w.slice(1, -1)).sort()).toEqual([...OFFSITE_WARNINGS].sort());
  });

  it("knows every error code offsite.sh writes", () => {
    const script = repoFile("infrastructure/backup/offsite.sh");
    const written = new Set<string>();
    for (const pattern of [/echo ([a-z_]+) ;;/g, /REASON_CODE=([a-z_]+)/g, /(?:attempt|drill_fail) ([a-z_]+) "/g]) {
      for (const match of script.matchAll(pattern)) written.add(match[1]!);
    }
    expect(written.size).toBeGreaterThan(8);
    for (const code of written) expect(OFFSITE_ERROR_CODES).toContain(code);
  });

  it("has a text for every state, warning and error code in both languages", () => {
    for (const messages of [ru, en]) {
      const texts = messages.backups.offsite;
      for (const state of ["protected", "problem", "off"] as const) expect(texts.state[state]).toBeTruthy();
      for (const warning of OFFSITE_WARNINGS) expect(texts.warnings[warning]).toBeTruthy();
      for (const code of OFFSITE_ERROR_CODES) expect(texts.errors[code]).toBeTruthy();
    }
  });
});
