"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDown } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CopyButton, Dialog, EmptyState, Field, formatCurrency, notify } from "@sendora/ui-kit";
import { LoadError, PageHead, Textarea } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { usePermissions } from "@/lib/hooks";
import type { LeadList, ProposalRow } from "@/lib/types";

/** Small markdown reader for the proposal text: headings, bullets, paragraphs. React escapes everything. */
function Doc({ md }: { md: string }) {
  const out: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = (k: number) => { if (list.length) { out.push(<ul key={`u${k}`}>{list.map((x, i) => <li key={i}>{x}</li>)}</ul>); list = []; } };
  md.split("\n").forEach((line, i) => {
    if (line.startsWith("- ")) { list.push(line.slice(2)); return; }
    flush(i);
    if (line.startsWith("# ")) out.push(<h1 key={i}>{line.slice(2)}</h1>);
    else if (line.startsWith("## ")) out.push(<h2 key={i}>{line.slice(3)}</h2>);
    else if (line.trim()) out.push(<p key={i}>{line}</p>);
  });
  flush(9999);
  return <div className="cl-doc" aria-label="Proposal preview">{out}</div>;
}

function useDebounced<T>(v: T, ms = 400): T { const [d, setD] = useState(v); useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]); return d; }

export default function ProposalsPage() {
  const qc = useQueryClient();
  const { canWrite } = usePermissions();
  const leads = useQuery({ queryKey: ["leads-pick"], queryFn: () => get<LeadList>("/leads?limit=1000&status=enrolled,replied,meeting,proposal") });
  const saved = useQuery({ queryKey: ["proposals"], queryFn: () => get<ProposalRow[]>("/proposals") });
  const [leadId, setLeadId] = useState<number | null>(null);
  const [title, setTitle] = useState("Faster replies for your enquiries");
  const [price, setPrice] = useState("4500");
  const [scope, setScope] = useState("Set up the reply system\nConnect your inbox and calendar\nTrain your team for one hour");
  const [notes, setNotes] = useState("");
  const [handoff, setHandoff] = useState<{ instructions: string; items: string[] } | null>(null);
  useEffect(() => { try { const n = localStorage.getItem("cl-proposal-notes"); if (n) setNotes(n); } catch { /* ignore */ } }, []);
  useEffect(() => { try { localStorage.setItem("cl-proposal-notes", notes); } catch { /* ignore */ } }, [notes]);
  const lead = leadId ?? leads.data?.rows[0]?.id ?? null;
  const body = { lead_id: lead, title, scope: scope.split("\n").map((s) => s.trim()).filter(Boolean), price_cents: Math.round((Number(price) || 0) * 100), call_notes: notes };
  const dBody = useDebounced(JSON.stringify(body));
  const preview = useQuery({ queryKey: ["proposal-preview", dBody], queryFn: () => post<{ body_md: string }>("/proposals/preview", JSON.parse(dBody)), enabled: JSON.parse(dBody).lead_id !== null && JSON.parse(dBody).title.trim().length > 0 && JSON.parse(dBody).price_cents > 0 });
  const save = useMutation({
    mutationFn: () => post<ProposalRow>("/proposals", body),
    onSuccess: () => { notify.success("Proposal saved. The deal moved to Proposal."); qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" }); },
    onError: (e: Error) => notify.error("Could not save", e.message),
  });
  const contract = useMutation({
    mutationFn: async (pid: number) => { const c = await post<{ id: number; open_items: string[] }>(`/proposals/${pid}/contract`); const h = await post<{ instructions: string }>(`/contracts/${c.id}/handoff`); return { c, h }; },
    onSuccess: ({ c, h }) => { setHandoff({ instructions: h.instructions, items: c.open_items }); },
    onError: (e: Error) => notify.error("Could not prepare the contract", e.message),
  });
  const priceError = Number(price) > 0 ? null : "Enter a price above zero, for example 4500";
  return (
    <div className="cl-page">
      <PageHead title="Proposals" sub="Write what you heard, choose the scope, set the price. The document builds as you type. You write every promise and price yourself." />
      <div className="cl-two cl-two--rev">
        <Card title="Details">
          <div className="cl-stack">
            <label className="sx-field"><span className="sx-label">Lead</span><select className="cl-select" value={lead ?? ""} onChange={(e) => setLeadId(Number(e.target.value))}>{leads.data?.rows.map((l) => <option key={l.id} value={l.id}>{l.name} ({l.company})</option>)}</select></label>
            <Field label="Title" value={title} onChange={setTitle} maxLength={200} validate={(v) => (v.trim() ? null : "Give the proposal a title")} />
            <Field label="Price in dollars" inputMode="decimal" value={price} onChange={setPrice} validate={() => priceError} hint={`Shown as ${formatCurrency(Number(price) || 0)}`} />
            <Textarea label="Scope, one item per line" value={scope} onChange={(e) => setScope(e.target.value)} />
            <Textarea label="Call notes" value={notes} onChange={(e) => setNotes(e.target.value)} hint="One point per line. Saved in this browser while you type." />
            <div className="sx-row">
              <Button variant="primary" disabled={!lead || !!priceError || !title.trim() || !canWrite} disabledReason={canWrite ? "Choose a lead, give it a title and set a price" : "The viewer role cannot save proposals"} onClick={async () => { await save.mutateAsync(); }}>Save proposal</Button>
            </div>
          </div>
        </Card>
        <div className="cl-stack">
          {leads.isError ? <LoadError error={leads.error} onRetry={() => leads.refetch()} what="the lead list" /> : preview.data ? <Doc md={preview.data.body_md} /> : <Card><EmptyState title="Nothing to preview" body={lead ? "Fill in the details." : "Import leads and run the jobs first, then choose a lead."} /></Card>}
        </div>
      </div>
      <Card title="Saved proposals">
        {saved.isError ? <LoadError error={saved.error} onRetry={() => saved.refetch()} what="saved proposals" /> : saved.data?.length ? (
          <ul className="cl-list">{saved.data.map((p) => (
            <li key={p.id} className="cl-item" style={{ cursor: "default" }}>
              <span className="cl-item__top"><strong>{p.title}</strong><Badge tone="accent">{formatCurrency(p.price_cents / 100)}</Badge></span>
              <span className="sx-row">
                <a className="sx-btn sx-btn--sm" href={`/api/proposals/${p.id}/pdf`} target="_blank" rel="noreferrer"><FileDown size={14} aria-hidden />PDF</a>
                {canWrite ? <Button size="sm" onClick={async () => { await contract.mutateAsync(p.id); }}>Prepare for signature</Button> : null}
              </span>
            </li>))}</ul>
        ) : <EmptyState title="No saved proposals" body="Save one from the form and it appears here with its PDF." />}
      </Card>
      <Dialog open={handoff !== null} onOpenChange={(o) => !o && setHandoff(null)} title="Ready to sign, once you finish the open items" description="This only prepares a folder on the server. Nothing was sent to anyone."
        actions={handoff ? <CopyButton value={handoff.instructions} label="Copy the steps" /> : undefined}>
        {handoff ? <div className="cl-stack"><strong>Open items before you send</strong><ul>{handoff.items.map((i, k) => <li key={k}>{i}</li>)}</ul><pre className="cl-pre cl-mini">{handoff.instructions}</pre></div> : null}
      </Dialog>
    </div>
  );
}
