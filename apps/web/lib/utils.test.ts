import { describe, expect, it } from "vitest";

import { localeFromAcceptLanguage } from "@/i18n/config";
import en from "@/messages/en.json";
import ru from "@/messages/ru.json";

import { safeNextPath } from "./utils";

describe("safeNextPath", () => {
  it.each([
    [null, "/chat"],
    ["", "/chat"],
    ["/tasks", "/tasks"],
    ["/tasks?filter=active", "/tasks?filter=active"],
    ["https://evil.example", "/chat"],
    ["//evil.example", "/chat"],
    ["/\\evil.example", "/chat"],
    ["/login", "/chat"],
    ["/login?next=/x", "/chat"],
  ])("%s -> %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });
});

describe("localeFromAcceptLanguage", () => {
  it.each([
    [null, null],
    ["en-US,en;q=0.9", "en"],
    ["ru-RU,ru;q=0.9,en;q=0.8", "ru"],
    ["de-DE,de;q=0.9,en;q=0.5", "en"],
    ["fr-FR", null],
    ["en;q=0.2,ru;q=0.8", "ru"],
  ])("%s -> %s", (header, expected) => {
    expect(localeFromAcceptLanguage(header)).toBe(expected);
  });
});

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe("translations", () => {
  it("ru and en define exactly the same keys", () => {
    expect(keys(ru).sort()).toEqual(keys(en).sort());
  });
});
