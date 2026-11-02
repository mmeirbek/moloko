import { describe, expect, it } from "vitest";

import {
  authenticationToJSON,
  base64urlToBuffer,
  bufferToBase64url,
  classifyCeremonyError,
  detectPasskeySupport,
  deviceName,
  registrationToJSON,
  toCreationOptions,
  toRequestOptions,
  type WebAuthnEnv,
} from "./webauthn";

const credentials = { get: () => Promise.resolve(null), create: () => Promise.resolve(null) };

function env(overrides: Partial<WebAuthnEnv> & { pkc?: WebAuthnEnv["PublicKeyCredential"] } = {}): WebAuthnEnv {
  const { pkc, ...rest } = overrides;
  return { isSecureContext: true, PublicKeyCredential: pkc ?? {}, navigator: { credentials }, ...rest };
}

describe("passkey support detection", () => {
  it("needs a browser at all", async () => {
    expect(await detectPasskeySupport(undefined)).toEqual({ available: false, conditional: false });
  });

  it("needs PublicKeyCredential, navigator.credentials and a secure context", async () => {
    expect(await detectPasskeySupport({ isSecureContext: true, navigator: { credentials } })).toEqual({
      available: false,
      conditional: false,
    });
    expect(await detectPasskeySupport(env({ navigator: {} }))).toEqual({ available: false, conditional: false });
    // e.g. the site opened over plain http on a LAN address
    expect(await detectPasskeySupport(env({ isSecureContext: false }))).toEqual({ available: false, conditional: false });
  });

  it("offers the button without autofill when conditional mediation is unknown", async () => {
    expect(await detectPasskeySupport(env())).toEqual({ available: true, conditional: false });
  });

  it("uses isConditionalMediationAvailable()", async () => {
    const yes = env({ pkc: { isConditionalMediationAvailable: () => Promise.resolve(true) } });
    const no = env({ pkc: { isConditionalMediationAvailable: () => Promise.resolve(false) } });
    expect(await detectPasskeySupport(yes)).toEqual({ available: true, conditional: true });
    expect(await detectPasskeySupport(no)).toEqual({ available: true, conditional: false });
  });

  it("prefers getClientCapabilities() when it answers", async () => {
    const pkc = {
      getClientCapabilities: () => Promise.resolve({ conditionalGet: false }),
      isConditionalMediationAvailable: () => Promise.resolve(true),
    };
    expect(await detectPasskeySupport(env({ pkc }))).toEqual({ available: true, conditional: false });
    const silent = {
      getClientCapabilities: () => Promise.resolve({}),
      isConditionalMediationAvailable: () => Promise.resolve(true),
    };
    expect(await detectPasskeySupport(env({ pkc: silent }))).toEqual({ available: true, conditional: true });
  });

  it("treats a failing check as no autofill (the button still works)", async () => {
    const pkc = { isConditionalMediationAvailable: () => Promise.reject(new Error("boom")) };
    expect(await detectPasskeySupport(env({ pkc }))).toEqual({ available: true, conditional: false });
  });
});

describe("base64url", () => {
  it("round-trips bytes without padding", () => {
    const bytes = new Uint8Array([0, 1, 2, 250, 251, 252, 253, 254, 255]);
    const text = bufferToBase64url(bytes);
    expect(text).toBe("AAEC-vv8_f7_");
    expect(new Uint8Array(base64urlToBuffer(text))).toEqual(bytes);
    expect(new Uint8Array(base64urlToBuffer("AQ"))).toEqual(new Uint8Array([1]));
  });
});

describe("options and answers", () => {
  it("turns creation options into buffers", () => {
    const options = toCreationOptions({
      rp: { id: "moloko.tail1234.ts.net", name: "moloko" },
      user: { id: "AQID", name: "owner", displayName: "Owner" },
      challenge: "BAUG",
      pubKeyCredParams: [{ type: "public-key", alg: -7 }],
      excludeCredentials: [{ id: "BwgJ", type: "public-key", transports: ["internal"] }],
      authenticatorSelection: { residentKey: "required", userVerification: "required" },
    });
    expect(new Uint8Array(options.challenge as ArrayBuffer)).toEqual(new Uint8Array([4, 5, 6]));
    expect(new Uint8Array(options.user.id as ArrayBuffer)).toEqual(new Uint8Array([1, 2, 3]));
    expect(options.user.name).toBe("owner");
    expect(options.excludeCredentials?.[0]?.transports).toEqual(["internal"]);
    expect(options.authenticatorSelection?.userVerification).toBe("required");
  });

  it("turns request options into buffers", () => {
    const options = toRequestOptions({ challenge: "BAUG", rpId: "moloko.tail1234.ts.net", allowCredentials: [], userVerification: "required" });
    expect(new Uint8Array(options.challenge as ArrayBuffer)).toEqual(new Uint8Array([4, 5, 6]));
    expect(options.allowCredentials).toEqual([]);
    expect(options.rpId).toBe("moloko.tail1234.ts.net");
  });

  it("serialises the device's answers", () => {
    const buf = (...b: number[]) => new Uint8Array(b).buffer;
    const reg = registrationToJSON({
      id: "AQ",
      rawId: buf(1),
      type: "public-key",
      authenticatorAttachment: "platform",
      response: { clientDataJSON: buf(2), attestationObject: buf(3), getTransports: () => ["internal", "hybrid"] },
      getClientExtensionResults: () => ({}),
    });
    expect(reg).toEqual({
      id: "AQ",
      rawId: "AQ",
      type: "public-key",
      authenticatorAttachment: "platform",
      clientExtensionResults: {},
      response: { clientDataJSON: "Ag", attestationObject: "Aw", transports: ["internal", "hybrid"] },
    });
    const auth = authenticationToJSON({
      id: "AQ",
      rawId: buf(1),
      type: "public-key",
      response: { clientDataJSON: buf(2), authenticatorData: buf(3), signature: buf(4), userHandle: null },
    });
    expect(auth.response).toEqual({ clientDataJSON: "Ag", authenticatorData: "Aw", signature: "BA", userHandle: null });
    expect(auth.authenticatorAttachment).toBeNull();
  });
});

describe("prompt failures", () => {
  it("are told apart by the DOMException name", () => {
    const named = (name: string) => Object.assign(new Error(name), { name });
    expect(classifyCeremonyError(named("NotAllowedError"))).toBe("cancelled");
    expect(classifyCeremonyError(named("AbortError"))).toBe("aborted");
    expect(classifyCeremonyError(named("InvalidStateError"))).toBe("exists");
    expect(classifyCeremonyError(named("SecurityError"))).toBe("wrongSite");
    expect(classifyCeremonyError(new Error("x"))).toBe("failed");
    expect(classifyCeremonyError("weird")).toBe("failed");
  });
});

describe("device name", () => {
  it("names the usual devices", () => {
    expect(deviceName("Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X)")).toBe("iPhone");
    expect(deviceName("Mozilla/5.0 (Macintosh; Intel Mac OS X 15_6)")).toBe("Mac");
    expect(deviceName("Mozilla/5.0 (Linux; Android 15; HUAWEI)")).toBe("Android");
    expect(deviceName("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("Windows");
    expect(deviceName("curl/8")).toBe("Passkey");
  });
});
