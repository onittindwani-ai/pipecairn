import { expect, test } from "@playwright/test";
import { login, resetDemo, runDays, watch } from "./helpers";

test("a pipeline card opens the lead with Enter and with its Open button", async ({ page }) => {
  const errors = watch(page);
  await login(page);
  await resetDemo(page);
  await runDays(page, 3);
  await page.goto("/pipeline");
  const card = page.getByRole("group", { name: /,/ }).first();
  await expect(card).toBeVisible();
  await card.focus();
  await page.keyboard.press("Enter");
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByText("Timeline")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await card.hover();
  await card.getByRole("button", { name: /open/i }).click();
  await expect(page.getByRole("dialog").getByText("Timeline")).toBeVisible();
  expect(errors).toEqual([]);
});
