"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, ConfirmDialog, DataTable, Dialog, EmptyState, Field, FilterBar, Sheet, TableSkeleton, formatWhen, middleTruncate, notify, type Column } from "@sendora/ui-kit";
import { CsvFileInput } from "@/components/CsvFileInput";
import { LeadDetailBody } from "@/components/LeadDetail";
import { LoadError, PageHead, StatusBadge, Textarea, flagLabel } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { usePermissions } from "@/lib/hooks";
import type { LeadDetail, LeadList, LeadRow } from "@/lib/types";

const SAMPLE = "email,first_name,last_name,title,company,domain,timezone,source\nava@example-co.example.test,Ava,Alder,Owner,Example Co,example-co.example.test,America/New_York,csv_list\n";

export default function LeadsPage() {
  const qc = useQueryClient();
  const { canWrite, isOwner } = usePermissions();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<LeadRow | null>(null);
  const [imp, setImp] = useState(false);
  const [csv, setCsv] = useState(SAMPLE);
  const [toSuppress, setToSuppress] = useState<{ rows: LeadRow[]; clear: () => void } | null>(null);
  const q = useQuery({ queryKey: ["leads", search, status], queryFn: () => get<LeadList>(`/leads?limit=5000&q=${encodeURIComponent(search)}&status=${status}`) });
  const importer = useMutation({
    mutationFn: () => post<{ rows: number; created: number; duplicates: number; flagged: Record<string, number>; ignored_columns: string[] }>("/leads/import", { csv }),
    onSuccess: (r) => { const f = Object.entries(r.flagged).map(([k, v]) => `${v} ${flagLabel(k)}`).join(", "); notify.success(`Imported ${r.created} of ${r.rows} rows. ${r.duplicates} duplicates skipped${f ? `. Flagged: ${f}` : ""}.${r.ignored_columns.length ? ` Columns not used: ${r.ignored_columns.join(", ")}.` : ""}`); setImp(false); qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== "me" }); },
    onError: (e: Error) => notify.error("Import failed", e.message),
  });
  const suppress = useMutation({
    mutationFn: (ids: number[]) => post<{ suppressed: number }>("/leads/suppress", { ids }),
    onSuccess: (r) => { notify.success(`${r.suppressed} lead(s) will never be contacted again.`); qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== "me" }); },
    onError: (e: Error) => notify.error("Could not suppress", e.message),
  });
  const columns: Column<LeadRow>[] = [
    { key: "name", header: "Name", width: "1.3fr", sortValue: (r) => r.name },
    { key: "company", header: "Company", width: "1.3fr", sortValue: (r) => r.company },
    { key: "email", header: "Email", width: "1.7fr", render: (r) => <span title={r.email}>{middleTruncate(r.email, 30)}</span> },
    { key: "status", header: "Status", width: "120px", render: (r) => <StatusBadge status={r.status} />, sortValue: (r) => r.status },
    { key: "flags", header: "Flags", width: "150px", render: (r) => (r.flags.length ? <Badge tone="warning">{flagLabel(r.flags[0]!)}{r.flags.length > 1 ? ` +${r.flags.length - 1}` : ""}</Badge> : <span className="cl-mini">none</span>) },
    { key: "score", header: "Score", width: "80px", align: "right", sortValue: (r) => r.score ?? -1, render: (r) => (r.score ?? "-") },
  ];
  return (
    <div className="cl-page">
      <PageHead title="Leads" sub="Everyone who has been imported or has filled in a form. Duplicates are merged and risky addresses are flagged on the way in." actions={isOwner ? <Button variant="primary" feedback={false} onClick={() => setImp(true)}><Upload size={14} aria-hidden />Import CSV</Button> : undefined} />
      <FilterBar>
        <Field label="Search" value={search} onChange={setSearch} placeholder="Name, company or email" clearable />
        <label className="sx-field"><span className="sx-label">Status</span><select className="cl-select" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{["new", "scored", "enrolled", "replied", "meeting", "proposal", "won", "lost", "suppressed", "dead"].map((s) => <option key={s}>{s}</option>)}</select></label>
      </FilterBar>
      {q.isError ? <LoadError error={q.error} onRetry={() => q.refetch()} what="leads" /> : !q.data ? <TableSkeleton rows={8} columns={5} /> : q.data.rows.length === 0 ? (
        <Card><EmptyState title="No leads match" body={search || status ? "Clear the search or the status filter." : "Import a CSV to start."} actionLabel={isOwner ? "Import CSV" : undefined} onAction={isOwner ? () => setImp(true) : undefined} /></Card>
      ) : (
        <DataTable label="Leads" rows={q.data.rows} rowKey={(r) => String(r.id)} columns={columns} height={560} selectable onRowOpen={setOpen} rowActions={(r) => <Button size="sm" feedback={false} onClick={() => setOpen(r)}>Open</Button>} bulkActions={canWrite ? (rows, clear) => <Button variant="danger" feedback={false} onClick={() => setToSuppress({ rows, clear })}>Never contact</Button> : undefined} />
      )}
      <div className="cl-mini">{q.data && q.data.count !== q.data.total ? `${q.data.count} shown of ${q.data.total}.` : ""}</div>
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)} title={open?.name ?? ""} description={open ? `${open.company}, ${open.email}` : undefined}>{open ? <LeadDetailBody id={open.id} /> : null}</Sheet>
      <ConfirmDialog open={toSuppress !== null} onOpenChange={(o) => !o && setToSuppress(null)} title={`Never contact ${toSuppress?.rows.length ?? 0} lead(s) again?`} description="Their addresses go on the suppression list and every follow up stops. This cannot be undone here." confirmLabel="Never contact" destructive
        onConfirm={async () => { await suppress.mutateAsync(toSuppress!.rows.map((r) => r.id)); toSuppress!.clear(); }} />
      <Dialog open={imp} onOpenChange={setImp} title="Import leads" description="Choose a CSV file or paste the text. It needs an email column. Other columns: first_name, last_name, title, company, domain, timezone, phone, source, sms_consent."
        actions={<Button variant="primary" disabled={!csv.trim()} disabledReason="Paste some CSV first" onClick={async () => { await importer.mutateAsync(); }}>Import</Button>}>
        <CsvFileInput onText={setCsv} />
        <Textarea label="Or paste the CSV text" value={csv} onChange={(e) => setCsv(e.target.value)} style={{ minHeight: 120, fontFamily: "var(--sx-font-mono)" }} hint="Texts are only sent to people marked sms_consent with a phone like +14155550100." />
      </Dialog>
    </div>
  );
}
