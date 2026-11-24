import { expect, test } from "@playwright/test";
import { call, login, resetDemo, watch } from "./helpers";

test("the whole demo path: leads in, messages out, replies read, a reply approved, a deal moved, a proposal made, the log verified", async ({ page }) => {
  const errors = watch(page);
  await login(page);
  await resetDemo(page);

  // 1. Overview starts quiet, then Run now sends messages and shows a toast
  await page.goto("/");
  await expect(page.getByText("Messages sent")).toBeVisible();
  const run = page.getByRole("button", { name: "Run now" });
  await run.click();
  await expect(page.getByText(/Ran every job\. Sent \d+/)).toBeVisible();
  await expect.poll(async () => Number((await (await page.request.get("/api/overview")).json()).sent)).toBeGreaterThan(20);

  // 2. Move the clock and run again until the scripted replies arrive
  for (let i = 0; i < 6; i++) { await call(page, "/demo/advance", { hours: 30 }); await call(page, "/demo/tick"); }

  // 3. Inbox shows replies read for us. Open an interested one and approve the draft
  await page.goto("/inbox");
  await expect(page.getByRole("list", { name: "Replies" })).toBeVisible();
  const interested = page.locator(".cl-item", { hasText: "interested" }).first();
  await interested.click();
  await expect(page.getByLabel("Draft reply")).toContainText("a few times for a short call");
  await page.getByRole("button", { name: "Approve and send" }).click();
  await expect(page.getByText("Reply sent.")).toBeVisible();

  // 4. Unsubscribe replies were handled without a person
  await page.getByRole("radio", { name: "All" }).click();
  await expect(page.locator(".cl-item", { hasText: "unsubscribe" }).first()).toBeVisible();

  // 5. Pipeline: move a card with the mouse and see the undo toast
  await page.goto("/pipeline");
  const card = page.locator(".sx-kanban__card").first();
  await expect(card).toBeVisible();
  const from = await card.boundingBox();
  const target = await page.getByRole("region", { name: "Contacted" }).boundingBox();
  const before = await page.getByRole("region", { name: "Contacted" }).locator(".sx-kanban__card").count();
  await page.mouse.move(from!.x + 20, from!.y + 20);
  await page.mouse.down();
  await page.mouse.move(from!.x + 40, from!.y + 40, { steps: 5 });
  await page.mouse.move(target!.x + target!.width / 2, target!.y + 120, { steps: 15 });
  await page.mouse.up();
  await expect(page.getByText(/Moved to/)).toBeVisible();
  expect(await page.getByRole("region", { name: "Contacted" }).locator(".sx-kanban__card").count()).toBeGreaterThanOrEqual(before);

  // 6. Proposal: preview builds, save, PDF opens, prepare for signature shows steps
  await page.goto("/proposals");
  await expect(page.getByLabel("Proposal preview")).toContainText("What we heard on the call");
  await page.getByLabel("Call notes").fill("Loses leads after hours\nWants texts too");
  await expect(page.getByLabel("Proposal preview")).toContainText("Loses leads after hours");
  await page.getByRole("button", { name: "Save proposal" }).click();
  await expect(page.getByText(/Proposal saved/)).toBeVisible();
  const pdfLink = page.getByRole("link", { name: "PDF" }).first();
  const href = await pdfLink.getAttribute("href");
  const pdf = await page.request.get(href!);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
  await page.getByRole("button", { name: "Prepare for signature" }).first().click();
  await expect(page.getByText("Ready to sign, once you finish the open items")).toBeVisible();
  await expect(page.getByText("Nothing was sent to anyone.")).toBeVisible();
  await page.keyboard.press("Escape");

  // 7. Audit chain verifies
  await page.goto("/audit");
  await page.getByRole("button", { name: "Verify the chain" }).click();
  await expect(page.getByText(/audit log is intact/)).toBeVisible();

  expect(errors.filter((e) => !/favicon/.test(e)), errors.join("\n")).toEqual([]);
});

test("the kill switch stops the next run and says so", async ({ page }) => {
  await login(page);
  await resetDemo(page);
  await page.getByRole("button", { name: "Pause all" }).click();
  await page.getByRole("button", { name: "Pause all" }).last().click();
  await expect(page.getByText("Kill switch is on.")).toBeVisible();
  const r = await (await call(page, "/demo/tick")).json();
  expect(r.send.halted).toBe(true);
  await page.getByRole("button", { name: "Turn it off" }).click();
  await expect(page.getByText("Kill switch is on.")).toHaveCount(0);
});
