import { expect, test as setup } from "@playwright/test";

import { api, csrf, OWNER } from "./helpers";

/** Sign in once, add the offline mock provider (ENABLE_MOCK_PROVIDER=true), save the session. */
setup("owner signs in and has a model", async ({ request }) => {
  const token = await csrf(request);
  const login = await request.post("/api/v1/auth/login", { data: OWNER, headers: { "X-CSRF-Token": token } });
  expect(login.ok(), await login.text()).toBeTruthy();
  const providers = await api<{ kind: string; id: string }[]>(request, "GET", "/providers");
  let mock = providers.find((p) => p.kind === "mock");
  if (!mock) mock = await api(request, "POST", "/providers", { kind: "mock", name: "Mock" });
  await api(request, "POST", `/providers/${mock!.id}/sync-models`);
  await request.storageState({ path: ".auth/owner.json" });
});
