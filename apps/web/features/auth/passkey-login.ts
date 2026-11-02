"use client";

import type { MeResponse, PasskeyOptionsOut } from "@moloko/shared-types";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/errors";
import { passkeyLoginOptions, passkeyLoginVerify } from "@/lib/api/passkeys";
import { detectPasskeySupport, getPasskey, PasskeyCeremonyError } from "@/lib/webauthn";

type Credential = Record<string, unknown>;

export interface PasskeyLoginState {
  /** The server has passkeys on and this browser can use them: show the button. */
  enabled: boolean;
  pending: boolean;
  error: unknown;
}

export interface PasskeyLoginDeps {
  options: () => Promise<PasskeyOptionsOut>;
  verify: (credential: Credential) => Promise<MeResponse>;
  get: (options: Credential, opts: { conditional?: boolean; signal?: AbortSignal }) => Promise<Credential>;
  /** Offer passkeys in the username field's autofill while the page is open. */
  conditional: boolean;
  onState: (state: PasskeyLoginState) => void;
  onSignedIn: (me: MeResponse) => void;
  now?: () => number;
}

/** Closed by the owner or stopped by us: nothing to explain. */
function quiet(error: unknown): boolean {
  return error instanceof PasskeyCeremonyError && (error.kind === "cancelled" || error.kind === "aborted");
}

/** Refresh the autofill prompt this long before its challenge expires on the server. */
const REFRESH_MARGIN_S = 20;

/**
 * Signing in with a passkey on the login page:
 *  - with conditional mediation, a prompt waits in the username field's autofill; it is
 *    renewed before its single-use challenge expires;
 *  - the button aborts that prompt and opens the device's dialog (Face ID / Touch ID) with
 *    the already fetched options, so the call stays inside the click (Safari needs that);
 *  - after a failed sign-in a fresh prompt is armed again (the old challenge is used up).
 */
export class PasskeyLogin {
  private stopped = false;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private controller: AbortController | null = null;
  private latest: { value: PasskeyOptionsOut; until: number } | null = null;
  private state: PasskeyLoginState = { enabled: false, pending: false, error: null };

  constructor(private readonly deps: PasskeyLoginDeps) {}

  start(): void {
    void this.arm();
  }

  stop(): void {
    this.stopped = true;
    clearTimeout(this.timer);
    this.controller?.abort();
  }

  clearError(): void {
    if (this.state.error) this.set({ error: null });
  }

  /** The «Sign in with Face ID / Touch ID» button. */
  async signIn(): Promise<void> {
    clearTimeout(this.timer);
    this.controller?.abort();
    this.set({ pending: true, error: null });
    const fresh = this.latest && this.latest.until > this.now() ? this.latest.value : null;
    const value = fresh ?? (await this.fetchOptions(true));
    if (!value || this.stopped) return this.set({ pending: false });
    this.latest = null;
    const controller = (this.controller = new AbortController());
    let credential: Credential;
    try {
      credential = await this.deps.get(value.options, { signal: controller.signal });
    } catch (error) {
      if (controller.signal.aborted || this.stopped) return;
      this.set({ pending: false, error: quiet(error) ? null : error });
      void this.arm();
      return;
    }
    await this.finish(credential);
  }

  private now(): number {
    return (this.deps.now ?? Date.now)();
  }

  private set(patch: Partial<PasskeyLoginState>): void {
    this.state = { ...this.state, ...patch };
    if (!this.stopped) this.deps.onState(this.state);
  }

  private async fetchOptions(showErrors = false): Promise<PasskeyOptionsOut | null> {
    try {
      const value = await this.deps.options();
      this.latest = { value, until: this.now() + Math.max(0, value.expires_in_seconds - REFRESH_MARGIN_S) * 1000 };
      this.set({ enabled: true });
      return value;
    } catch (error) {
      if (error instanceof ApiError && error.code === "passkeys_disabled") this.set({ enabled: false, error: null });
      else if (showErrors) this.set({ error });
      return null;
    }
  }

  private async arm(): Promise<void> {
    if (this.stopped) return;
    clearTimeout(this.timer);
    this.controller?.abort();
    this.controller = null;
    const value = await this.fetchOptions();
    if (!value || this.stopped) return;
    this.timer = setTimeout(() => void this.arm(), Math.max(10, value.expires_in_seconds - REFRESH_MARGIN_S) * 1000);
    if (!this.deps.conditional) return;
    const controller = (this.controller = new AbortController());
    let credential: Credential;
    try {
      credential = await this.deps.get(value.options, { conditional: true, signal: controller.signal });
    } catch (error) {
      // Aborted by us (button, renewal) or refused by the browser: the timer renews it.
      if (!controller.signal.aborted && !this.stopped && !quiet(error)) this.set({ error });
      return;
    }
    this.latest = null; // this challenge is being used now
    await this.finish(credential);
  }

  private async finish(credential: Credential): Promise<void> {
    clearTimeout(this.timer);
    this.set({ pending: true, error: null });
    try {
      const me = await this.deps.verify(credential);
      this.stop();
      this.deps.onSignedIn(me);
    } catch (error) {
      this.set({ pending: false, error });
      void this.arm();
    }
  }
}

/** React wiring for the login form; `signIn` is undefined until the button may be shown. */
export function usePasskeyLogin(onSignedIn: (me: MeResponse) => void) {
  const [state, setState] = useState<PasskeyLoginState>({ enabled: false, pending: false, error: null });
  const flow = useRef<PasskeyLogin | null>(null);
  const signedIn = useRef(onSignedIn);
  useEffect(() => {
    signedIn.current = onSignedIn;
  }, [onSignedIn]);

  useEffect(() => {
    let cancelled = false;
    void detectPasskeySupport().then((support) => {
      if (cancelled || !support.available) return;
      flow.current = new PasskeyLogin({
        options: passkeyLoginOptions,
        verify: passkeyLoginVerify,
        get: getPasskey,
        conditional: support.conditional,
        onState: setState,
        onSignedIn: (me) => signedIn.current(me),
      });
      flow.current.start();
    });
    return () => {
      cancelled = true;
      flow.current?.stop();
      flow.current = null;
    };
  }, []);

  return {
    ...state,
    signIn: () => void flow.current?.signIn(),
    clearError: () => flow.current?.clearError(),
  };
}
