"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, DataTable, EmptyState, Sheet, TableSkeleton, formatWhen, notify, type Column } from "@sendora/ui-kit";
import { LoadError, PageHead } from "@/components/Parts";
import { get } from "@/lib/api";
import type { AuditRow } from "@/lib/types";

export default function AuditPage() {
  const q = useQuery({ queryKey: ["audit"], queryFn: () => get<AuditRow[]>("/audit?limit=500") });
  const [open, setOpen] = useState<AuditRow | null>(null);
  const verify = useMutation({
    mutationFn: () => get<{ ok: boolean; first_bad_id: number | null }>("/audit/verify"),
    onSuccess: (r) => (r.ok ? notify.success("The audit log is intact. No entry was changed or removed.") : notify.error("The audit log was changed", `The first bad entry is number ${r.first_bad_id}.`)),
  });
  const columns: Column<AuditRow>[] = [
    { key: "id", header: "No.", width: "70px", align: "right", sortValue: (r) => r.id },
    { key: "at", header: "When", width: "130px", render: (r) => formatWhen(new Date(r.at)), sortValue: (r) => r.at },
    { key: "actor", header: "Who", width: "1fr", sortValue: (r) => r.actor },
    { key: "action", header: "What", width: "1.4fr", render: (r) => <Badge>{r.action}</Badge>, sortValue: (r) => r.action },
    { key: "target", header: "About", width: "1.2fr", render: (r) => r.target ?? "" },
  ];
  return (
    <div className="cl-page">
      <PageHead title="Audit log" sub="Every approval, suppression, send and setting change, in order. Each entry is chained to the one before, so a change or a deletion shows up." actions={<Button onClick={async () => { await verify.mutateAsync(); }}>Verify the chain</Button>} />
      {q.isError ? <LoadError error={q.error} onRetry={() => q.refetch()} what="the audit log" /> : !q.data ? <TableSkeleton rows={8} columns={5} /> : q.data.length === 0 ? <Card><EmptyState title="Nothing logged yet" body="Actions show up here as they happen." /></Card> : <DataTable label="Audit log" rows={q.data} rowKey={(r) => String(r.id)} columns={columns} height={560} onRowOpen={setOpen} />}
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)} title={open ? `Entry ${open.id}` : ""} description={open ? `${open.actor} did ${open.action}${open.target ? ` on ${open.target}` : ""}` : undefined}>
        {open ? (
          <dl className="cl-stack" aria-label="Audit entry">
            <div><dt className="cl-mini">When</dt><dd style={{ margin: 0 }}>{new Date(open.at).toUTCString()}</dd></div>
            {Object.entries(open.detail ?? {}).map(([k, v]) => <div key={k}><dt className="cl-mini">{k.replaceAll("_", " ")}</dt><dd style={{ margin: 0, overflowWrap: "anywhere" }}>{typeof v === "string" ? v : JSON.stringify(v)}</dd></div>)}
            {Object.keys(open.detail ?? {}).length === 0 ? <span className="cl-mini">No more detail was recorded for this entry.</span> : null}
          </dl>
        ) : null}
      </Sheet>
    </div>
  );
}
