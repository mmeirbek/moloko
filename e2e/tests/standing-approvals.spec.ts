import { expect, test } from "@playwright/test";

import { api, newAgent, OWNER, unique, watchErrors } from "./helpers";

type Task = { id: string; status: string };

test("approve and don't ask again: the agent goes on without asking, until the owner takes it back", async ({ page, request }) => {
  const errors = watchErrors(page);
  const models = await api<{ id: string }[]>(request, "GET", "/models");
  const agent = await newAgent(request, {
    name: unique("Writer"),
    model_config_id: models[0]!.id,
    autonomy_level: "supervised", // every write asks
    allowed_tools: ["fs_write"],
  });
  const script = `[[mock:tools]][["fs_write",{"path":"a.txt","content":"A"}],["fs_write",{"path":"b.txt","content":"B"}]][[/mock:tools]]`;
  const started = await api<{ task: Task }>(request, "POST", `/agents/${agent.id}/run`, { title: "Two files", description: script });
  const statusOf = async () => (await api<{ task: Task }>(request, "GET", `/tasks/${started.task.id}`)).task.status;
  await expect.poll(statusOf, { timeout: 60_000 }).toBe("waiting_approval");

  await page.goto("/approvals");
  const card = page.locator("article[data-approval-id]").first();
  await expect(card).toContainText("агент сможет записывать файлы в своей папке без вопросов");
  await card.getByRole("button", { name: "Одобрить и больше не спрашивать" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(`${agent.name} сможет записывать файлы в своей папке без вашего одобрения`);
  await dialog.getByRole("button", { name: "Одобрить и больше не спрашивать" }).click();

  // The second write did not ask.
  await expect.poll(statusOf, { timeout: 60_000 }).toBe("completed");

  // The agent page lists it; «Убрать» makes it ask again.
  await page.goto(`/office/agents/${agent.id}`);
  const box = page.getByTestId("standing-approvals");
  await expect(box).toContainText("Разрешено без вопросов");
  await expect(box).toContainText("записывать файлы в своей папке");
  await box.getByRole("button", { name: "Убрать" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Убрать" }).click();
  await expect(box).toBeHidden();
  expect(errors).toEqual([]);
});

test("full access for all agents: one switch with the password, then no agent asks", async ({ page, request }) => {
  const errors = watchErrors(page);
  const models = await api<{ id: string }[]>(request, "GET", "/models");
  try {
    await page.goto("/settings#agents");
    const card = page.getByTestId("full-access-all");
    await expect(card).toContainText("агенты спрашивают разрешения");
    await card.getByRole("button", { name: "Включить для всех…" }).click();
    const dialog = page.getByTestId("full-access-dialog");
    await dialog.getByLabel("Ваш пароль moloko").fill(OWNER.password);
    await dialog.getByRole("button", { name: "Включить для всех" }).click();
    await expect(card).toContainText("Агенты больше не спрашивают разрешений");

    // A supervised agent added afterwards writes without asking.
    const agent = await newAgent(request, {
      name: unique("Writer"),
      model_config_id: models[0]!.id,
      autonomy_level: "supervised",
      allowed_tools: ["fs_write"],
    });
    expect(agent).toMatchObject({ full_access: true });
    const script = `[[mock:tools]][["fs_write",{"path":"a.txt","content":"A"}]][[/mock:tools]]`;
    const started = await api<{ task: Task }>(request, "POST", `/agents/${agent.id}/run`, { title: "One file", description: script });
    await expect
      .poll(async () => (await api<{ task: Task }>(request, "GET", `/tasks/${started.task.id}`)).task.status, { timeout: 60_000 })
      .toBe("completed");

    await card.getByRole("button", { name: "Выключить для всех" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Выключить для всех" }).click();
    await expect(card).toContainText("агенты спрашивают разрешения");
  } finally {
    // Never leave it on for the other tests (they expect approvals).
    await api(request, "PUT", "/agents/full-access", { enabled: false });
  }
  expect(errors).toEqual([]);
});
