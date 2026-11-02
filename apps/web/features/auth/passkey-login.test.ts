import type { MeResponse, PasskeyOptionsOut } from "@moloko/shared-types";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { PasskeyCeremonyError } from "@/lib/webauthn";

import { PasskeyLogin, type PasskeyLoginDeps, type PasskeyLoginState } from "./passkey-login";

const ME = { user: { username: "owner" } } as unknown as MeResponse;

function opts(n: number): PasskeyOptionsOut {
  return { options: { challenge: `c${n}` }, expires_in_seconds: 300 };
}

function setup(over: Partial<PasskeyLoginDeps> = {}) {
  let n = 0;
  const states: PasskeyLoginState[] = [];
  const signedIn: MeResponse[] = [];
  const deps: PasskeyLoginDeps = {
    options: vi.fn(async () => opts(++n)),
    verify: vi.fn(async () => ME),
    get: vi.fn(() => new Promise<Record<string, unknown>>(() => {})), // waits forever
    conditional: false,
    onState: (s) => states.push(s),
    onSignedIn: (me) => signedIn.push(me),
    ...over,
  };
  const flow = new PasskeyLogin(deps);
  return { flow, deps, states, signedIn, last: () => states.at(-1) };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => vi.useRealTimers());

describe("passkey sign-in on the login page", () => {
  it("stays hidden when the server has passkeys off", async () => {
    const { flow, last } = setup({
      options: vi.fn(async () => {
        throw new ApiError({ status: 404, code: "passkeys_disabled", message: "off" });
      }),
    });
    flow.start();
    await tick();
    expect(last()?.enabled).toBe(false);
    flow.stop();
  });

  it("the button uses the options fetched in advance (no request inside the click)", async () => {
    const get = vi.fn(async () => ({ id: "cred" }));
    const { flow, deps, signedIn } = setup({ get });
    flow.start();
    await tick();
    expect(deps.options).toHaveBeenCalledTimes(1);
    await flow.signIn();
    expect(deps.options).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith({ challenge: "c1" }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(deps.verify).toHaveBeenCalledWith({ id: "cred" });
    expect(signedIn).toEqual([ME]);
  });

  it("autofill: waits in the username field and signs in when a passkey is picked", async () => {
    let pick: (v: Record<string, unknown>) => void = () => {};
    const get = vi.fn(
      (_o: Record<string, unknown>, { conditional }: { conditional?: boolean }) =>
        new Promise<Record<string, unknown>>((resolve) => {
          if (conditional) pick = resolve;
        }),
    );
    const { flow, signedIn } = setup({ get, conditional: true });
    flow.start();
    await tick();
    expect(get).toHaveBeenCalledWith({ challenge: "c1" }, expect.objectContaining({ conditional: true }));
    pick({ id: "cred" });
    await tick();
    expect(signedIn).toEqual([ME]);
  });

  it("the button aborts the autofill prompt first", async () => {
    const signals: AbortSignal[] = [];
    const get = vi.fn((_o: Record<string, unknown>, { signal }: { signal?: AbortSignal }) => {
      if (signal) signals.push(signal);
      return signals.length === 1 ? new Promise<Record<string, unknown>>(() => {}) : Promise.resolve({ id: "cred" });
    });
    const { flow, signedIn } = setup({ get, conditional: true });
    flow.start();
    await tick();
    await flow.signIn();
    expect(signals[0]?.aborted).toBe(true);
    expect(signedIn).toEqual([ME]);
  });

  it("renews the autofill prompt before its challenge expires", async () => {
    vi.useFakeTimers();
    const { flow, deps } = setup({ conditional: true });
    flow.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(deps.options).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(280_000);
    expect(deps.options).toHaveBeenCalledTimes(2);
    flow.stop();
  });

  it("shows a server refusal and arms a fresh prompt (the old challenge is used up)", async () => {
    const refusal = new ApiError({ status: 401, code: "passkey_rejected", message: "no" });
    const { flow, deps, last, signedIn } = setup({
      get: vi.fn(async () => ({ id: "cred" })),
      verify: vi.fn(async () => {
        throw refusal;
      }),
    });
    flow.start();
    await tick();
    await flow.signIn();
    await tick();
    expect(last()?.error).toBe(refusal);
    expect(last()?.pending).toBe(false);
    expect(deps.options).toHaveBeenCalledTimes(2);
    expect(signedIn).toEqual([]);
    flow.stop();
  });

  it("says nothing when the owner closes the device's dialog", async () => {
    const { flow, last } = setup({
      get: vi.fn(async () => {
        throw new PasskeyCeremonyError("cancelled");
      }),
    });
    flow.start();
    await tick();
    await flow.signIn();
    expect(last()?.error).toBeNull();
    expect(last()?.pending).toBe(false);
    flow.stop();
  });
});
