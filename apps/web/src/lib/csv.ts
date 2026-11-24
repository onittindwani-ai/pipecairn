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

export function summariseCsv(text: string, previewRows = 5): CsvSummary {
  const all = parseCsv(text);
  const columns = (all[0] ?? []).map((c) => c.trim());
  return {
    columns,
    rows: Math.max(0, all.length - 1),
    preview: all.slice(1, 1 + previewRows),
    hasEmail: columns.some((c) => c.toLowerCase() === "email"),
  };
}
