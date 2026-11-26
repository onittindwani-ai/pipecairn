import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { PAGES, call, login, resetDemo, runDays, watch } from "./helpers";

const OUT = join(__dirname, "..", "..", "..", "docs", "screenshots");
mkdirSync(OUT, { recursive: true });
const sizes = [{ tag: "desktop", width: 1440, height: 900 }, { tag: "mobile", width: 390, height: 844 }] as const;

for (const s of sizes) {
  test.describe(s.tag, () => {
    test.use({ viewport: { width: s.width, height: s.height } });

    test("screenshots of every state", async ({ page }) => {
      const errors = watch(page);
      const shot = (name: string) => page.screenshot({ path: join(OUT, `${s.tag}-${name}.png`) });
      await login(page);
      await resetDemo(page);

      // empty state: nothing has run yet, so the inbox is empty
      await page.goto("/inbox");
      await expect(page.getByText("Nothing needs you")).toBeVisible();
      await shot("06-empty-inbox");

      // run so every page has data
      await runDays(page, 7);
      await page.goto("/");
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1200); // count up and chart draw in
      await shot("01-overview-default");

      // button mid processing, then a toast
      await page.goto("/");
      const run = page.getByRole("button", { name: "Run now" });
      await run.click();
      await expect(run).toHaveAttribute("data-state", "processing");
      await shot("04-button-processing");
      await expect(page.getByText(/Ran every job/)).toBeVisible();
      await page.waitForTimeout(500);
      await shot("05-toast");

      // detail sheet
      await page.goto("/leads");
      await expect(page.getByRole("grid", { name: "Leads" })).toBeVisible();
      await page.getByLabel("Status").selectOption("replied");
      await page.waitForTimeout(600);
      await page.getByRole("grid", { name: "Leads" }).focus();
      await page.keyboard.press("j");
      await page.keyboard.press("Enter");
      await expect(page.getByRole("dialog")).toBeVisible();
      await page.waitForTimeout(1100);
      await shot("02-detail-lead");
      await page.keyboard.press("Escape");

      // warning: a mailbox was paused for bounces
      await page.goto("/deliverability");
      await expect(page.getByText("Paused").first()).toBeVisible();
      await page.getByText("Paused").first().scrollIntoViewIfNeeded();
      await page.waitForTimeout(900);
      await shot("03-warning-paused-mailbox");

      // more pages worth looking at
      for (const [path, name] of [["/pipeline", "09-pipeline"], ["/inbox", "10-inbox"], ["/sequences", "11-sequences"], ["/proposals", "12-proposals"], ["/integrations", "13-integrations"], ["/approvals", "14-approvals"], ["/audit", "15-audit"]] as const) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(700);
        await shot(name);
      }

      // error state: the overview call fails
      await page.route("**/api/overview", (r) => r.abort());
      await page.goto("/");
      await expect(page.getByText("Could not load the overview")).toBeVisible();
      await shot("07-error-overview");
      await page.unroute("**/api/overview");

      // dark theme
      await page.goto("/");
      await page.evaluate(() => { document.documentElement.dataset.theme = "dark"; });
      await page.waitForTimeout(1300);
      await shot("08-dark-overview");
      await page.goto("/inbox");
      await page.evaluate(() => { document.documentElement.dataset.theme = "dark"; });
      await page.waitForTimeout(500);
      await shot("16-dark-inbox");
      expect(errors.filter((e) => !/favicon|ERR_FAILED|net::|Failed to load resource/.test(e)), errors.join("\n")).toEqual([]);
    });
  });
}

test.describe("accessibility and behaviour", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await resetDemo(page);
    await runDays(page, 7);
  });

  test("axe finds no serious or critical problems on any page, light and dark", async ({ page }) => {
    for (const theme of ["light", "dark"]) {
      for (const path of PAGES) {
        await page.goto(path);
        await page.evaluate((t) => { document.documentElement.dataset.theme = t; }, theme);
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(1000);
        const res = await new AxeBuilder({ page }).analyze();
        const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(bad.map((v) => `${theme} ${path}: ${v.id} ${v.help} (${v.nodes.length})`), `${theme} ${path}`).toEqual([]);
      }
    }
  });

  test("keyboard only: command palette, table keys, dialogs close with escape", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.type("Go to Leads");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/leads/);
    await expect(page.getByRole("grid", { name: "Leads" })).toBeVisible();
    await page.getByRole("grid", { name: "Leads" }).focus();
    await page.keyboard.press("j");
    await page.keyboard.press("x");
    await expect(page.getByText(/selected/)).toBeVisible();
    await page.keyboard.press("Escape");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    // tab order reaches the main content from the top bar
    await page.goto("/pipeline");
    let inMain = false;
    for (let i = 0; i < 60 && !inMain; i++) {
      await page.keyboard.press("Tab");
      inMain = await page.evaluate(() => !!document.activeElement?.closest("main"));
    }
    expect(inMain, "Tab reaches the main content").toBe(true);
  });

  test("reduced motion removes page and chart animation", async ({ browser }) => {
    const ctx = await browser.newContext({ reducedMotion: "reduce", baseURL: "http://localhost:3000" });
    const page = await ctx.newPage();
    await login(page);
    await page.goto("/");
    await page.waitForTimeout(300);
    const names = await page.evaluate(() => [".cl-page", ".cl-funnel__fill"].map((s) => { const el = document.querySelector(s); return el ? getComputedStyle(el).animationName : "missing"; }));
    expect(names).toEqual(["none", "none"]);
    await ctx.close();
  });

  test("a table with 5,000 rows stays light and the page does not shift while loading", async ({ page }) => {
    const r = await call(page, "/demo/stress-leads", { n: 5000 });
    expect(r.ok()).toBeTruthy();
    await page.addInitScript(() => {
      (window as unknown as { __cls: number }).__cls = 0;
      new PerformanceObserver((l) => { for (const e of l.getEntries() as unknown as { hadRecentInput: boolean; value: number }[]) if (!e.hadRecentInput) (window as unknown as { __cls: number }).__cls += e.value; }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/leads");
    await expect(page.getByRole("grid", { name: "Leads" })).toBeVisible();
    await expect(page.getByText(/shown of 5/)).toBeVisible();
    const rows = await page.locator('[role="row"]').count();
    expect(rows).toBeLessThan(120);
    const t0 = Date.now();
    await page.getByRole("grid", { name: "Leads" }).focus();
    for (let i = 0; i < 30; i++) await page.keyboard.press("j");
    expect(Date.now() - t0).toBeLessThan(4000);
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => (window as unknown as { __cls: number }).__cls)).toBeLessThan(0.1);
    await resetDemo(page);
  });
});
