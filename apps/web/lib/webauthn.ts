/**
 * Passkeys in the browser (WebAuthn), with the plain browser API — no library: the server
 * sends the options as JSON (binary values base64url, WebAuthn Level 3 "JSON" form), we turn
 * them into ArrayBuffers for navigator.credentials, and the browser's answer back into JSON.
 * Everything that touches `window` takes it as an argument, so it is testable in Node.
 */

/** What this browser can do. `conditional`: passkeys can be offered in the username field's
 * autofill (`autocomplete="username webauthn"`) without pressing a button first. */
export interface PasskeySupport {
  available: boolean;
  conditional: boolean;
}

interface PublicKeyCredentialStatic {
  isConditionalMediationAvailable?: () => Promise<boolean>;
  getClientCapabilities?: () => Promise<Record<string, boolean | undefined>>;
}

export interface WebAuthnEnv {
  isSecureContext?: boolean;
  PublicKeyCredential?: PublicKeyCredentialStatic;
  navigator?: { credentials?: { get?: unknown; create?: unknown } };
}

export const NO_PASSKEYS: PasskeySupport = { available: false, conditional: false };

/**
 * Passkeys need a secure context (HTTPS, or localhost), `PublicKeyCredential` and
 * `navigator.credentials`. Conditional mediation (autofill) is checked with the newer
 * `getClientCapabilities()` when present, otherwise `isConditionalMediationAvailable()`.
 */
export async function detectPasskeySupport(env: WebAuthnEnv | undefined = browserEnv()): Promise<PasskeySupport> {
  const pkc = env?.PublicKeyCredential;
  const credentials = env?.navigator?.credentials;
  if (!env || !env.isSecureContext || !pkc || typeof credentials?.get !== "function") return NO_PASSKEYS;
  let conditional = false;
  try {
    const capabilities = typeof pkc.getClientCapabilities === "function" ? await pkc.getClientCapabilities() : null;
    if (capabilities && typeof capabilities.conditionalGet === "boolean") {
      conditional = capabilities.conditionalGet;
    } else if (typeof pkc.isConditionalMediationAvailable === "function") {
      conditional = (await pkc.isConditionalMediationAvailable()) === true;
    }
  } catch {
    conditional = false;
  }
  return { available: true, conditional };
}

function browserEnv(): WebAuthnEnv | undefined {
  if (typeof window === "undefined") return undefined;
  return window as unknown as WebAuthnEnv;
}

// --- base64url ------------------------------------------------------------------------------

export function base64urlToBuffer(value: string): ArrayBuffer {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob(base64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}

export function bufferToBase64url(value: ArrayBuffer | ArrayBufferView): string {
  const bytes = value instanceof ArrayBuffer ? new Uint8Array(value) : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  let raw = "";
  for (const byte of bytes) raw += String.fromCharCode(byte);
  return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// --- options (server JSON → browser) -----------------------------------------------------------

type Json = Record<string, unknown>;
interface DescriptorJSON {
  id: string;
  type: string;
  transports?: string[];
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] {
  if (!Array.isArray(list)) return [];
  return (list as DescriptorJSON[]).map((d) => ({
    id: base64urlToBuffer(d.id),
    type: "public-key",
    ...(d.transports ? { transports: d.transports as AuthenticatorTransport[] } : {}),
  }));
}

/** PublicKeyCredentialCreationOptionsJSON → options for navigator.credentials.create(). */
export function toCreationOptions(json: Json): PublicKeyCredentialCreationOptions {
  const user = json.user as { id: string; name: string; displayName: string };
  return {
    ...(json as unknown as PublicKeyCredentialCreationOptions),
    challenge: base64urlToBuffer(json.challenge as string),
    user: { ...user, id: base64urlToBuffer(user.id) },
    excludeCredentials: descriptors(json.excludeCredentials),
  };
}

/** PublicKeyCredentialRequestOptionsJSON → options for navigator.credentials.get(). */
export function toRequestOptions(json: Json): PublicKeyCredentialRequestOptions {
  return {
    ...(json as unknown as PublicKeyCredentialRequestOptions),
    challenge: base64urlToBuffer(json.challenge as string),
    allowCredentials: descriptors(json.allowCredentials),
  };
}

// --- answers (browser → server JSON) ------------------------------------------------------------

interface AttestationLike {
  clientDataJSON: ArrayBuffer;
  attestationObject: ArrayBuffer;
  getTransports?: () => string[];
}

interface AssertionLike {
  clientDataJSON: ArrayBuffer;
  authenticatorData: ArrayBuffer;
  signature: ArrayBuffer;
  userHandle: ArrayBuffer | null;
}

interface CredentialLike<R> {
  id: string;
  rawId: ArrayBuffer;
  type: string;
  authenticatorAttachment?: string | null;
  response: R;
  getClientExtensionResults?: () => unknown;
}

/** The result of navigator.credentials.create() as RegistrationResponseJSON. */
export function registrationToJSON(credential: CredentialLike<AttestationLike>): Json {
  const response = credential.response;
  return {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment ?? null,
    clientExtensionResults: credential.getClientExtensionResults?.() ?? {},
    response: {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      attestationObject: bufferToBase64url(response.attestationObject),
      transports: typeof response.getTransports === "function" ? response.getTransports() : [],
    },
  };
}

/** The result of navigator.credentials.get() as AuthenticationResponseJSON. */
export function authenticationToJSON(credential: CredentialLike<AssertionLike>): Json {
  const response = credential.response;
  return {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment ?? null,
    clientExtensionResults: credential.getClientExtensionResults?.() ?? {},
    response: {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      authenticatorData: bufferToBase64url(response.authenticatorData),
      signature: bufferToBase64url(response.signature),
      userHandle: response.userHandle ? bufferToBase64url(response.userHandle) : null,
    },
  };
}

// --- ceremonies -------------------------------------------------------------------------------------

/**
 * Why a passkey prompt ended without a passkey:
 *  - cancelled: the owner closed it (or it timed out) — the browser does not say which;
 *  - aborted: we stopped it ourselves (e.g. the autofill prompt for the button);
 *  - exists: this device already holds a passkey for moloko (excludeCredentials);
 *  - wrongSite: the page is not on the domain the server expects (WEBAUTHN_RP_ID);
 *  - failed: anything else.
 */
export type CeremonyFailure = "cancelled" | "aborted" | "exists" | "wrongSite" | "failed";

export class PasskeyCeremonyError extends Error {
  readonly kind: CeremonyFailure;
  constructor(kind: CeremonyFailure, cause?: unknown) {
    super(`passkey ${kind}`);
    this.name = "PasskeyCeremonyError";
    this.kind = kind;
    this.cause = cause;
  }
}

export function classifyCeremonyError(error: unknown): CeremonyFailure {
  const name = typeof error === "object" && error !== null && "name" in error ? String((error as { name: unknown }).name) : "";
  switch (name) {
    case "NotAllowedError":
      return "cancelled";
    case "AbortError":
      return "aborted";
    case "InvalidStateError":
      return "exists";
    case "SecurityError":
      return "wrongSite";
    default:
      return "failed";
  }
}

async function run<T>(ceremony: () => Promise<T | null>): Promise<T> {
  let result: T | null;
  try {
    result = await ceremony();
  } catch (error) {
    throw new PasskeyCeremonyError(classifyCeremonyError(error), error);
  }
  if (!result) throw new PasskeyCeremonyError("cancelled");
  return result;
}

/** Ask the device to create a passkey (Face ID / Touch ID); returns RegistrationResponseJSON. */
export async function createPasskey(options: Json): Promise<Json> {
  const credential = await run(() => navigator.credentials.create({ publicKey: toCreationOptions(options) }));
  return registrationToJSON(credential as unknown as CredentialLike<AttestationLike>);
}

/**
 * Ask the device for a passkey; returns AuthenticationResponseJSON. `conditional`: offer it in
 * the username field's autofill instead of a dialog (waits until the owner picks one or
 * `signal` aborts).
 */
export async function getPasskey(options: Json, { conditional = false, signal }: { conditional?: boolean; signal?: AbortSignal } = {}): Promise<Json> {
  const credential = await run(() =>
    navigator.credentials.get({
      publicKey: toRequestOptions(options),
      signal,
      ...(conditional ? { mediation: "conditional" as CredentialMediationRequirement } : {}),
    }),
  );
  return authenticationToJSON(credential as unknown as CredentialLike<AssertionLike>);
}

/** A short name for the device that creates the passkey (the owner can change it). */
export function deviceName(userAgent: string): string {
  if (/iPhone/.test(userAgent)) return "iPhone";
  if (/iPad/.test(userAgent)) return "iPad";
  if (/Android/.test(userAgent)) return "Android";
  if (/Mac OS X|Macintosh/.test(userAgent)) return "Mac";
  if (/Windows/.test(userAgent)) return "Windows";
  if (/Linux/.test(userAgent)) return "Linux";
  return "Passkey";
}
