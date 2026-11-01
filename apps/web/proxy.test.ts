import { describe, expect, it } from "vitest";

import { buildCsp } from "./proxy";

describe("Content-Security-Policy", () => {
  it("allows only own scripts with the request's nonce, no eval in production", () => {
    const csp = buildCsp("abc", "moloko.tail.ts.net", false);
    expect(csp).toContain("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).toContain("connect-src 'self' ws://moloko.tail.ts.net wss://moloko.tail.ts.net");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
  });

  it("dev mode adds eval for React's debugging only", () => {
    expect(buildCsp("n", null, true)).toContain("'unsafe-eval'");
  });
});
