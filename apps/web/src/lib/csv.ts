/** A small CSV reader for the import preview. The server does the real parsing and checking. */

export type CsvSummary = { columns: string[]; rows: number; preview: string[][]; hasEmail: boolean };

export function parseCsv(text: string): string[][] {
  const src = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i]!;
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      rows.push(row); row = [];
    } else cell += ch;
  }
  if (cell !== "" || row.length > 0) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim() !== ""));
}

/** The names the server accepts for the email column (the server does the same matching: case, spaces, hyphens and a few common spellings do not matter). */
const EMAIL_HEADERS = new Set(["email", "e_mail", "email_address", "mail"]);
export const isEmailHeader = (name: string) => EMAIL_HEADERS.has(name.replace(/^\ufeff/, "").trim().toLowerCase().replace(/[\s\-.]+/g, "_").replace(/^_+|_+$/g, ""));

export function summariseCsv(text: string, previewRows = 5): CsvSummary {
  const all = parseCsv(text);
  const columns = (all[0] ?? []).map((c) => c.trim());
  return {
    columns,
    rows: Math.max(0, all.length - 1),
    preview: all.slice(1, 1 + previewRows),
    hasEmail: columns.some(isEmailHeader),
  };
}
