import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { login, resetDemo, watch } from "./helpers";

const OUT = join(__dirname, "..", "..", "..", "docs", "screenshots");
const FIXTURE = join(__dirname, "fixtures", "upload-leads.csv");
mkdirSync(OUT, { recursive: true });
const sizes = [{ tag: "desktop", width: 1440, height: 900 }, { tag: "mobile", width: 390, height: 844 }] as const;

for (const s of sizes) {
  test.describe(`${s.tag} CSV file upload`, () => {
    test.use({ viewport: { width: s.width, height: s.height } });

    test("a chosen CSV file is previewed in the browser, then the leads arrive", async ({ page }) => {
      const errors = watch(page);
      await login(page);
      await resetDemo(page);
      await page.goto("/leads");
      await expect(page.getByRole("grid", { name: "Leads" })).toBeVisible();

      await page.getByRole("button", { name: "Import CSV" }).first().click();
      const dialog = page.getByRole("dialog", { name: "Import leads" });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText("No file chosen")).toBeVisible();

      await dialog.getByLabel("Choose a CSV file").setInputFiles(FIXTURE);
      await expect(dialog.getByText("upload-leads.csv")).toBeVisible();
      await expect(dialog.getByText(/4 rows, 8 columns/)).toBeVisible();
      await expect(dialog.getByRole("table")).toContainText("nia.fixture@northwind-test.example");
      await expect(dialog.getByRole("table")).toContainText("Northwind Test, LLC"); // the quoted comma stays in one cell
      await expect(dialog.getByLabel("Or paste the CSV text")).toHaveValue(/tomas\.fixture@harbourlane-test\.example/);
      await page.waitForTimeout(600); // the dialog finishes its settle before the picture
      await page.screenshot({ path: join(OUT, `${s.tag}-17-import-file-chosen.png`) });

      await dialog.getByRole("button", { name: "Import", exact: true }).click();
      await expect(page.getByText(/Imported 4 of 4 rows/)).toBeVisible();
      await expect(dialog).toBeHidden();

      await page.getByLabel("Search").fill("fixture@");
      await expect(page.getByRole("grid", { name: "Leads" })).toContainText("Northwind Test, LLC");
      await expect(page.getByRole("grid", { name: "Leads" })).toContainText("Linden Works Test");
      expect(errors.filter((e) => !/favicon/.test(e)), errors.join("\n")).toEqual([]);
    });
  });
}

test("the file picker works with the keyboard and tells the person about a bad file", async ({ page }) => {
  await login(page);
  await page.goto("/leads");
  await page.getByRole("button", { name: "Import CSV" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Import leads" });
  const input = dialog.getByLabel("Choose a CSV file");
  await input.focus();
  await expect(input).toBeFocused(); // the real input takes focus, the label button shows the ring
  await input.setInputFiles({ name: "empty.csv", mimeType: "text/csv", buffer: Buffer.from("email,first_name\n") });
  await expect(dialog.getByRole("alert")).toContainText("no data rows");
  await input.setInputFiles({ name: "nomail.csv", mimeType: "text/csv", buffer: Buffer.from("name\nAnn\n") });
  await expect(dialog.getByText(/no email column/)).toBeVisible();
});
