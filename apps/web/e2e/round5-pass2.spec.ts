import { expect, test, type Page } from "@playwright/test";
import { call, login, resetDemo, runDays } from "./helpers";

/** Second walk through every screen as a first time owner (Round 5, pass 2). One test per defect found. */
test.describe("Round 5 pass 2", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await resetDemo(page);
    await runDays(page, 5);
  });

  /** Watches every counting number from the first paint, in the page itself, so a reload cannot lose the samples. */
  const WATCH = () => {
    const w = window as unknown as { __c: { final: string; now: string }[][]; __t?: number };
    w.__c = [];
    w.__t = window.setInterval(() => {
      w.__c.push([...document.querySelectorAll("span.sx-num")].filter((e) => e.querySelector(":scope > .sx-sr-only")).map((e) => ({ final: e.querySelector(":scope > .sx-sr-only")!.textContent ?? "", now: e.querySelector(":scope > [aria-hidden]")?.textContent ?? "" })));
    }, 30);
  };
  const decimals = (t: string) => (t.match(/\.(\d+)/)?.[1] ?? "").length;
  const collect = (page: Page) => page.evaluate(() => (window as unknown as { __c: { final: string; now: string }[][] }).__c);

  test("counting numbers never show decimals on the way to a whole number, after load and after a reset", async ({ page }) => {
    await page.addInitScript(WATCH);
    const bad: string[] = [];
    const check = (rows: { final: string; now: string }[][]) => rows.flat().forEach((c) => { if (decimals(c.now) > decimals(c.final)) bad.push(`${c.now} on the way to ${c.final}`); });
    await page.goto("/");
    await page.waitForTimeout(2200);
    const afterLoad = await collect(page);
    check(afterLoad);
    expect(afterLoad.flat().length).toBeGreaterThan(20); // the counters were really watched
    expect(new Set(afterLoad.map((s) => s.map((c) => c.now).join("|"))).size).toBeGreaterThan(5); // and they did move
    await page.evaluate(() => { (window as unknown as { __c: unknown[] }).__c.length = 0; });
    await page.keyboard.press("Control+k");
    await page.keyboard.type("reset");
    await page.keyboard.press("Enter");
    await page.getByRole("button", { name: "Reset", exact: true }).click();
    await page.waitForTimeout(2200);
    const afterReset = await collect(page);
    check(afterReset);
    expect(new Set(afterReset.map((s) => s.map((c) => c.now).join("|"))).size).toBeGreaterThan(5);
    expect(bad, bad.slice(0, 5).join("\n")).toEqual([]);
  });

  test("a reply that is blank cannot be approved from the Inbox", async ({ page }) => {
    await page.goto("/inbox");
    await page.locator(".cl-item", { hasText: "wrong person" }).first().click();
    const box = page.getByRole("textbox", { name: "Draft reply" });
    await box.fill("   ");
    const approve = page.getByRole("button", { name: "Approve and send" });
    await expect(approve).toHaveAttribute("aria-disabled", "true");
    await box.fill("Thanks, who is the right person to talk to?");
    await expect(approve).not.toHaveAttribute("aria-disabled", "true");
  });

  test("the Proposals lead list includes leads who replied, so the quick demo step works", async ({ page }) => {
    const replied = ((await (await page.request.get("/api/leads?limit=500&status=replied")).json()) as { rows: { name: string; company: string }[] }).rows;
    expect(replied.length).toBeGreaterThan(0);
    await page.goto("/proposals");
    await expect(page.locator("select.cl-select option").first()).toBeAttached();
    const options = await page.locator("select.cl-select option").allInnerTexts();
    const missing = replied.filter((r) => !options.some((o) => o.includes(r.name)));
    expect(missing, `missing from ${options.length} options`).toEqual([]);
  });

  test("integrations explain the tiers once and no sentence repeats itself", async ({ page }) => {
    await page.goto("/integrations");
    await expect(page.getByTestId("tier-legend")).toContainText("Tier C: recipe prompt only");
    const lines = await page.locator(".cl-item > .cl-mini").allInnerTexts();
    expect(lines.length).toBeGreaterThan(10);
    for (const line of lines) {
      const sentences = line.split(/(?<=[.!?])\s+/).map((s) => s.toLowerCase().replace(/[^a-z ]/g, "").trim()).filter(Boolean);
      expect(new Set(sentences).size, line).toBe(sentences.length);
      expect(line).not.toMatch(/recipe prompt only\. recipe prompt/i);
    }
  });

  test("Approvals reads in plain words and points to the draft", async ({ page }) => {
    await page.goto("/approvals");
    const first = page.locator(".cl-item").first();
    await expect(first).not.toContainText("_");
    await expect(first).not.toContainText("reply.send");
    await expect(first).toContainText("Send a reply");
    await first.getByRole("link", { name: "Read the draft in the Inbox" }).click();
    await expect(page).toHaveURL(/\/inbox$/);
  });

  test("G then a number goes to that page, and typing in a box is left alone", async ({ page }) => {
    await page.goto("/");
    await page.locator("body").click();
    await page.keyboard.press("g");
    await page.keyboard.press("2");
    await expect(page).toHaveURL(/\/pipeline$/);
    await page.keyboard.press("g");
    await page.keyboard.press("5");
    await expect(page).toHaveURL(/\/leads$/);
    await page.getByRole("textbox", { name: "Search" }).fill("g");
    await page.keyboard.type("3");
    await expect(page).toHaveURL(/\/leads$/);
  });

  test("signing in after being sent to the sign in page lands on the page that was asked for", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/inbox");
    await expect(page).toHaveURL(/\/login\?next=%2Finbox$/);
    await page.getByLabel("Email").fill("owner@example.test");
    await page.getByLabel("Password").fill("demo-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/inbox$/);
    // a next value that points off the site is ignored
    await page.context().clearCookies();
    await page.goto("/login?next=//evil.example.test");
    await page.getByLabel("Email").fill("owner@example.test");
    await page.getByLabel("Password").fill("demo-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    expect(new URL(page.url()).hostname).not.toContain("evil");
  });

  test("on a phone the owner can still pause everything and sign out without the palette", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const pause = page.getByRole("button", { name: "Pause all" });
    await expect(pause).toBeVisible();
    await pause.click();
    await page.getByRole("alertdialog").or(page.getByRole("dialog")).getByRole("button", { name: "Pause all" }).click();
    await expect(page.getByText("Kill switch is on.")).toBeVisible();
    await page.getByRole("button", { name: "Turn it off", exact: true }).click();
    await expect(page.getByText("Demo mode.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("while the kill switch is on the top button says it turns the switch off, and the copy says only what is true", async ({ page }) => {
    await call(page, "/settings", { kill_switch: true });
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Pause all" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Turn the kill switch off" })).toBeVisible();
    await expect(page.getByText("Nothing is sent and no reply can be approved.")).toBeVisible();
    await expect(page.getByText("Nothing is written or sent")).toHaveCount(0);
    await page.getByRole("button", { name: "Turn the kill switch off" }).click();
    await expect(page.getByText("Kill switch is on.")).toHaveCount(0);
  });

  test("an audit row opens with Enter and shows what was recorded", async ({ page }) => {
    await page.goto("/audit");
    await page.getByRole("grid", { name: "Audit log" }).focus();
    await page.keyboard.press("Enter");
    const sheet = page.getByRole("dialog");
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText(/Entry \d+/);
    await expect(sheet.getByLabel("Audit entry")).toContainText("When");
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
  });

  test("the pipeline shows every column on a laptop screen and long columns scroll inside themselves", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/pipeline");
    await expect(page.locator(".sx-kanban__col")).toHaveCount(7);
    const last = await page.locator(".sx-kanban__col").last().boundingBox();
    expect(last!.x + last!.width).toBeLessThanOrEqual(1440 + 1);
    const pageHeight = await page.evaluate(() => document.documentElement.scrollHeight);
    expect(pageHeight).toBeLessThan(2000);
    const tall = await page.locator(".sx-kanban__col").first().evaluate((el) => el.scrollHeight > el.clientHeight);
    expect(tall).toBeTruthy();
  });

  test("Leads has one key hint, and Search and Status line up", async ({ page }) => {
    await page.goto("/leads");
    await expect(page.getByText("Keys: j and k move")).toHaveCount(0);
    await page.waitForTimeout(600); // the page slides in; measure once it has settled
    const tops = await page.evaluate(() => [...document.querySelectorAll(".sx-filterbar .sx-field .sx-label")].map((l) => l.getBoundingClientRect().y));
    expect(tops.length).toBe(2);
    expect(Math.abs(tops[0]! - tops[1]!)).toBeLessThanOrEqual(1);
  });

  test("words with several underscores and blank time zones read as words", async ({ page }) => {
    await page.goto("/leads");
    await page.getByRole("button", { name: "Import CSV" }).click();
    await page.getByRole("textbox", { name: "Or paste the CSV text" }).fill("email,first_name\nzed@zed-co.example.test,Zed\n");
    await page.getByRole("button", { name: "Import", exact: true }).click();
    await expect(page.getByText(/1 no valid time zone/)).toBeVisible();
    await expect(page.getByText(/invalid timezone|invalid_timezone/)).toHaveCount(0);
    await page.goto("/inbox");
    await page.getByRole("radio", { name: "All" }).click();
    expect(await page.locator("main .cl-item").allInnerTexts().then((t) => t.join(" "))).not.toMatch(/[a-z]_[a-z]/);
  });

  test("a lead sheet explains the score in words, not a code dump", async ({ page }) => {
    await page.goto("/leads");
    await page.getByRole("textbox", { name: "Search" }).fill("zoe.vale1@");
    await page.locator("[role=row]", { hasText: "Zoe Vale" }).first().click();
    await page.keyboard.press("Enter");
    const sheet = page.getByRole("dialog");
    await expect(sheet).toContainText(/Scored \d+ out of 100/);
    await expect(sheet).not.toContainText("{");
  });
});

test("Proposals says so when its lists cannot load, instead of saying there is nothing", async ({ page }) => {
  await login(page);
  await page.route("**/api/proposals", (r) => (r.request().method() === "GET" ? r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "x", message: "boom" } }) }) : r.continue()));
  await page.goto("/proposals");
  await expect(page.getByText("Could not load saved proposals")).toBeVisible();
  await expect(page.getByText("No saved proposals")).toHaveCount(0);
});

test("a viewer cannot add or remove sequence steps that could never be saved", async ({ page }) => {
  await login(page, "viewer@example.test");
  await page.goto("/sequences");
  await expect(page.getByRole("button", { name: "Add a step" })).toHaveAttribute("aria-disabled", "true");
  await expect(page.getByRole("button", { name: "Remove step" }).first()).toHaveAttribute("aria-disabled", "true");
});

test("a sequence that uses a field that does not exist cannot be saved, and says which", async ({ page }) => {
  await login(page);
  await resetDemo(page);
  await page.goto("/sequences");
  const save = page.getByRole("button", { name: "Save sequence" });
  await expect(save).not.toHaveAttribute("aria-disabled", "true");
  await page.getByLabel("Message").nth(1).fill("Hi {{nope}}, hello");
  await expect(save).toHaveAttribute("aria-disabled", "true");
  await save.hover();
  await expect(page.getByText(/Step \d uses a field that does not exist: \{\{nope\}\}/)).toBeVisible();
  await page.getByLabel("Message").nth(1).fill("Hi {{first_name}}, hello");
  await expect(save).not.toHaveAttribute("aria-disabled", "true");
});
