import { afterEach, describe, expect, it, vi } from "vitest";

import { pushSupportState } from "./push";

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 Version/18.5 Mobile/15E148 Safari/604.1";
const MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.5 Safari/605.1.15";

function device({ ua, standalone, push }: { ua: string; standalone: boolean; push: boolean }) {
  vi.stubGlobal("navigator", push ? { userAgent: ua, serviceWorker: {} } : { userAgent: ua });
  vi.stubGlobal("window", {
    matchMedia: () => ({ matches: standalone }),
    ...(push ? { PushManager: class {} } : {}),
  });
  vi.stubGlobal("Notification", push ? class {} : undefined);
}

describe("pushSupportState", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("an iPhone in a Safari tab is told to add moloko to the Home Screen (Safari hides push there)", () => {
    device({ ua: IPHONE, standalone: false, push: false });
    expect(pushSupportState()).toBe("homescreen");
  });

  it("an iPhone opened from the Home Screen can turn push on", () => {
    device({ ua: IPHONE, standalone: true, push: true });
    expect(pushSupportState()).toBe("yes");
  });

  it("a desktop browser with push can turn it on; one without says it is not supported", () => {
    device({ ua: MAC, standalone: false, push: true });
    expect(pushSupportState()).toBe("yes");
    device({ ua: MAC, standalone: false, push: false });
    expect(pushSupportState()).toBe("no");
  });
});
