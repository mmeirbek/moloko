import type { MeResponse, PasskeyListOut, PasskeyOptionsOut, PasskeyOut } from "@moloko/shared-types";

import { api } from "./client";

/** Passkeys: sign in with Face ID / Touch ID. Adding and deleting one needs the password. */
export const passkeyKeys = { list: ["auth", "passkeys"] as const };

export function listPasskeys(signal?: AbortSignal): Promise<PasskeyListOut> {
  return api.request<PasskeyListOut>("/auth/passkeys", { signal });
}

/** Step 1 of adding a passkey: checks the password, returns the options for create(). */
export function passkeyRegisterOptions(password: string): Promise<PasskeyOptionsOut> {
  return api.request<PasskeyOptionsOut>("/auth/passkeys/register/options", { method: "POST", body: { password } });
}

/** Step 2: the device's answer → the saved passkey. */
export function passkeyRegisterVerify(credential: Record<string, unknown>, name: string): Promise<PasskeyOut> {
  return api.request<PasskeyOut>("/auth/passkeys/register/verify", { method: "POST", body: { credential, name } });
}

export function renamePasskey(id: string, name: string): Promise<PasskeyOut> {
  return api.request<PasskeyOut>(`/auth/passkeys/${id}`, { method: "PATCH", body: { name } });
}

export function deletePasskey(id: string, password: string): Promise<void> {
  return api.request<void>(`/auth/passkeys/${id}`, { method: "DELETE", body: { password } });
}

/** Public: options for signing in (no username; the device offers its passkeys). */
export function passkeyLoginOptions(): Promise<PasskeyOptionsOut> {
  return api.request<PasskeyOptionsOut>("/auth/passkeys/login/options", { method: "POST" });
}

/** Public: signs in exactly like the password login (session cookie, new CSRF token). */
export function passkeyLoginVerify(credential: Record<string, unknown>): Promise<MeResponse> {
  return api.request<MeResponse>("/auth/passkeys/login/verify", { method: "POST", body: { credential } });
}
