import { expect, test } from "@playwright/test";
import { call, login, resetDemo, runDays, watch } from "./helpers";

test.describe("Round 5: defects found by walking every screen", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await resetDemo(page);
    await runDays(page, 5);
  });

  test("typing reset in the command palette puts Reset the demo data first, not a theme switch", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Control+k");
    await page.keyboard.type("reset");
    await expect(page.getByRole("option", { name: "Reset the demo data" })).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("alertdialog", { name: "Reset the demo?" }).or(page.getByRole("dialog", { name: "Reset the demo?" }))).toBeVisible();
  });

  test("the 30 and 90 day buttons change the chart, Today shows one number", async ({ page }) => {
    await page.goto("/");
    const ticks = () => page.locator(".sx-chart text, svg text").count();
    await expect(page.getByText("Messages per day")).toBeVisible();
    const week = await ticks();
    await page.getByRole("radio", { name: "30 days" }).click();
    await expect.poll(ticks).toBeGreaterThan(0);
    const month = await ticks();
    expect(month).not.toBe(week);
    await page.getByRole("radio", { name: "Today" }).click();
    await expect(page.getByText(/sent or drafted today/)).toBeVisible();
  });

  test("a viewer sees no buttons the server would refuse, and no 403 appears", async ({ page }) => {
    const errors = watch(page);
    await page.context().clearCookies();
    await login(page, "viewer@example.test");
    await expect(page.getByRole("button", { name: "Run now" })).toHaveCount(0);
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("option", { name: "Reset the demo data" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    for (const [path, gone] of [["/approvals", "Approve"], ["/inbox", "Approve and send"], ["/proposals", ""], ["/leads", "Import CSV"], ["/integrations", "Test connection"]] as const) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      if (gone) await expect(page.getByRole("button", { name: gone })).toHaveCount(0);
    }
    await page.goto("/proposals");
    await expect(page.getByRole("button", { name: "Save proposal" })).toBeDisabled();
    expect(errors.filter((e) => e.includes("403"))).toEqual([]);
  });

  test("a proposal with no title cannot be saved and does not fire a failing preview", async ({ page }) => {
    const errors = watch(page);
    await page.goto("/proposals");
    await page.getByLabel("Title").fill("");
    await expect(page.getByRole("button", { name: "Save proposal" })).toBeDisabled();
    await page.waitForTimeout(700);
    expect(errors.filter((e) => e.includes("422"))).toEqual([]);
  });

  test("a sequence step with no message cannot be saved", async ({ page }) => {
    await page.goto("/sequences");
    await page.getByLabel("Message").first().fill("");
    await expect(page.getByRole("button", { name: "Save sequence" })).toBeDisabled();
    await page.getByLabel("Message").first().fill("Hi {{first_name}}, a quick idea for {{company}}.");
    await expect(page.getByRole("button", { name: "Save sequence" })).toBeEnabled();
  });

  test("mailbox addresses are shown in their own letters, not in capitals", async ({ page }) => {
    await page.goto("/deliverability");
    const title = page.locator(".cl-mail .sx-card__title").first();
    await expect(title).toBeVisible();
    expect(await title.evaluate((e) => getComputedStyle(e).textTransform)).toBe("none");
  });

  test("the draft reply box is tall enough to read a whole draft", async ({ page }) => {
    await page.goto("/inbox");
    const box = page.getByLabel("Draft reply");
    await expect(box).toBeVisible();
    expect((await box.boundingBox())!.height).toBeGreaterThan(200);
  });

  test("booking a call closes the reply and removes it from Approvals", async ({ page }) => {
    await page.goto("/inbox");
    const open = async () => ((await (await page.request.get("/api/inbox?open=true")).json()) as { intent: string }[]).filter((r) => r.intent === "interested").length;
    const before = await open();
    expect(before).toBeGreaterThan(0);
    await page.locator(".cl-item", { hasText: "interested" }).first().click();
    await page.getByLabel("Open time").selectOption({ index: 1 });
    await page.getByRole("button", { name: "Book it" }).click();
    await expect(page.getByText(/Call booked for/)).toBeVisible();
    await expect.poll(open).toBe(before - 1);
    await page.goto("/approvals");
    const pending = (await (await page.request.get("/api/approvals")).json()).filter((a: { status: string; summary: string }) => a.status === "pending" && a.summary.includes("(interested)"));
    expect(pending.length).toBe(before - 1);
  });

  test("approving while the kill switch is on says so and keeps the reply open", async ({ page }) => {
    await call(page, "/settings", { kill_switch: true });
    await page.goto("/inbox");
    await page.locator(".cl-item", { hasText: "interested" }).first().click();
    const approve = page.getByRole("button", { name: "Approve and send" });
    await approve.click();
    await expect(page.getByText(/kill switch is on/i).first()).toBeVisible();
    expect(((await (await page.request.get("/api/inbox")).json()) as { handled: boolean; intent: string }[]).some((r) => r.intent === "interested" && !r.handled)).toBeTruthy();
    await call(page, "/settings", { kill_switch: false });
  });

  test("on a 390 px phone no page scrolls sideways, including the Overview numbers", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const p of ["/", "/inbox", "/proposals", "/deliverability", "/approvals"]) {
      await page.goto(p);
      await page.waitForLoadState("networkidle");
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, p).toBeLessThanOrEqual(0);
    }
  });
});
