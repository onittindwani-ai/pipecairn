"use client";
import { FileUp } from "lucide-react";
import { useId, useState } from "react";
import { summariseCsv, type CsvSummary } from "@/lib/csv";

const MAX_BYTES = 5 * 1024 * 1024;

type Picked = { name: string; summary: CsvSummary };

/** A real file input, shown as a button. The file is read in the browser, nothing leaves until the person presses Import. */
export function CsvFileInput({ onText }: { onText: (text: string) => void }) {
  const id = useId();
  const [picked, setPicked] = useState<Picked | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    if (file.size > MAX_BYTES) { setPicked(null); setError("That file is over 5 MB. Split it into smaller files."); return; }
    try {
      const text = await file.text();
      const summary = summariseCsv(text);
      if (summary.rows === 0) { setPicked(null); setError("That file has no data rows. It needs a header row and at least one lead."); return; }
      setPicked({ name: file.name, summary });
      onText(text);
    } catch {
      setPicked(null);
      setError("Could not read that file. Save it as CSV and try again.");
    }
  }

  const s = picked?.summary;
  return (
    <div className="sx-field cl-file">
      <span className="sx-label">CSV file</span>
      <div className="cl-file__row">
        <input id={id} type="file" accept=".csv,text/csv,text/plain" className="cl-file__input" onChange={onChange} />
        <label htmlFor={id} className="sx-btn cl-file__btn"><FileUp size={14} aria-hidden />Choose a CSV file</label>
        <span className="cl-file__name">{picked ? picked.name : "No file chosen"}</span>
      </div>
      <div role="status" aria-live="polite">
        {error ? <span className="sx-field__error" role="alert">{error}</span> : null}
        {s ? (
          <>
            <p className="cl-file__sum">{s.rows} {s.rows === 1 ? "row" : "rows"}, {s.columns.length} columns. {s.hasEmail ? "Showing the first rows below, and the text box holds the whole file." : "There is no email column, so the import will fail."}</p>
            <div className="cl-file__scroll" tabIndex={0} aria-label="Preview of the first rows">
              <table className="cl-file__table">
                <caption className="cl-file__cap">First {s.preview.length} of {s.rows}</caption>
                <thead><tr>{s.columns.map((c, i) => <th key={i} scope="col">{c}</th>)}</tr></thead>
                <tbody>{s.preview.map((r, i) => <tr key={i}>{s.columns.map((_, j) => <td key={j}>{r[j] ?? ""}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
