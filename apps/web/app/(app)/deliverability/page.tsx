"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CountUp, EmptyState, Field, Gauge, notify } from "@sendora/ui-kit";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import type { Mailbox } from "@/lib/types";

const Dns = ({ ok, name }: { ok: boolean; name: string }) => <span className={`cl-chip ${ok ? "cl-chip--ok" : "cl-chip--bad"}`}>{ok ? <Check size={13} aria-hidden /> : <X size={13} aria-hidden />}{name} {ok ? "set" : "missing"}</span>;

function AddMailbox({ onAdded }: { onAdded: () => void }) {
  const [address, setAddress] = useState("");
  const [cap, setCap] = useState("30");
  const add = useMutation({
    mutationFn: () => post("/mailboxes", { address: address.trim(), daily_cap: Math.max(1, Math.min(2000, Number(cap) || 30)) }),
    onSuccess: () => { notify.success("Mailbox added."); setAddress(""); onAdded(); },
    onError: (e: Error) => notify.error("Could not add the mailbox", e.message),
  });
  return (
    <Card title="Add a sending mailbox">
      <div className="cl-stack">
        <p className="cl-mini">Use the address of the account you set in SMTP_USER, or one that account may send as. Start with a low daily cap and raise it as the mailbox warms up.</p>
        <Field label="Mailbox address" type="email" value={address} onChange={setAddress} maxLength={254} />
        <Field label="Daily cap" type="number" min={1} value={cap} onChange={setCap} />
        <div><Button variant="primary" disabled={!address.includes("@")} disabledReason="Type the mailbox address first" onClick={async () => { await add.mutateAsync(); }}>Add mailbox</Button></div>
      </div>
    </Card>
  );
}

export default function DeliverabilityPage() {
  const qc = useQueryClient();
  const me = useMe();
  const q = useQuery({ queryKey: ["deliverability"], queryFn: () => get<Mailbox[]>("/deliverability") });
  const resume = useMutation({ mutationFn: (id: number) => post(`/deliverability/${id}/resume`), onSuccess: () => { notify.success("Mailbox resumed."); qc.invalidateQueries({ queryKey: ["deliverability"] }); }, onError: (e: Error) => notify.error("Could not resume", e.message) });
  if (q.isError) return <div className="cl-page"><PageHead title="Deliverability" /><LoadError error={q.error} onRetry={() => q.refetch()} what="mailboxes" /></div>;
  if (!q.data) return <div className="cl-page"><PageHead title="Deliverability" /><ListSkeleton /></div>;
  return (
    <div className="cl-page">
      <PageHead title="Deliverability" sub="Each sending mailbox has a daily cap. Use separate domains for cold email, never your main one. A mailbox that bounces too much is paused for you." />
      {me.data?.role === "owner" ? <AddMailbox onAdded={() => qc.invalidateQueries({ queryKey: ["deliverability"] })} /> : null}
      {q.data.length === 0 ? <Card><EmptyState title="No mailboxes yet" body="Nothing can be sent until a mailbox is added. The owner can add one above." /></Card> : (
        <div className="cl-cols cl-mail">
          {q.data.map((m) => {
            const pct = m.daily_cap ? m.sent_today / m.daily_cap : 0;
            return (
              <Card key={m.id} title={m.address}>
                <div className="cl-stack">
                  <div className="cl-hero">
                    <Gauge value={m.health / 100} size={110} label="health" display={String(m.health)} />
                    <div className="cl-stack" style={{ gap: 8 }}>
                      <div className="sx-row" style={{ justifyContent: "space-between" }}><span>Sent today</span><span className="sx-num"><CountUp value={m.sent_today} /> of {m.daily_cap}</span></div>
                      <div className={`cl-bar ${pct >= 1 ? "cl-bar--bad" : pct > 0.8 ? "cl-bar--warn" : ""}`} role="img" aria-label={`${Math.round(pct * 100)} percent of today's cap used`}><span style={{ width: `${Math.min(100, pct * 100)}%` }} /></div>
                      <div className="sx-row" style={{ justifyContent: "space-between" }}><span>Bounce rate</span><span className="sx-num">{(m.bounce_rate * 100).toFixed(1)}%</span></div>
                      <div className="cl-mini">{m.sent_total} sent in total, warm up {m.warmup_days} days</div>
                    </div>
                  </div>
                  <div className="sx-row"><Dns ok={m.spf_ok} name="SPF" /><Dns ok={m.dkim_ok} name="DKIM" /><Dns ok={m.dmarc_ok} name="DMARC" /></div>
                  {!m.is_active ? (
                    <div className="cl-stack" role="alert"><Badge tone="danger">Paused</Badge><span className="cl-mini">{m.paused_reason}</span>
                      {me.data?.role === "owner" ? <Button onClick={async () => { await resume.mutateAsync(m.id); }}>Resume after fixing the list</Button> : <span className="cl-mini">Only the owner can resume it.</span>}</div>
                  ) : pct >= 1 ? <Badge tone="warning">Cap reached, waiting for tomorrow</Badge> : <Badge tone="success">Sending</Badge>}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
