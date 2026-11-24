"use client";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { AreaChart, Badge, Card, CountUp, DateRange, EmptyState, Gauge, Stat, formatCurrency, type DateRangeValue } from "@sendora/ui-kit";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get } from "@/lib/api";
import type { Mailbox, Overview } from "@/lib/types";

const STAGE_LABEL: Record<string, string> = { new: "New", contacted: "Contacted", replied: "Replied", meeting: "Meeting", proposal: "Proposal", won: "Won", lost: "Lost" };

export default function OverviewPage() {
  const q = useQuery({ queryKey: ["overview"], queryFn: () => get<Overview>("/overview") });
  const mb = useQuery({ queryKey: ["deliverability"], queryFn: () => get<Mailbox[]>("/deliverability") });
  const [range, setRange] = useState<DateRangeValue>("7d");
  if (q.isError) return <div className="cl-page"><PageHead title="Overview" /><LoadError error={q.error} onRetry={() => q.refetch()} what="the overview" /></div>;
  if (!q.data) return <div className="cl-page"><PageHead title="Overview" /><ListSkeleton rows={4} /></div>;
  const o = q.data, s = o.speed_to_lead;
  const maxFunnel = Math.max(1, ...o.funnel.map((f) => f.count));
  const paused = (mb.data ?? []).filter((m) => !m.is_active);
  const days = { today: 1, "7d": 7, "30d": 30, "90d": 90 }[range];
  const shown = o.daily.slice(-days);
  const total = shown.reduce((n, d) => n + d.sent, 0);
  return (
    <div className="cl-page">
      <PageHead title="Overview" sub="Who was answered fast, what is waiting on you, and whether anything is about to go wrong." actions={<DateRange value={range} onChange={setRange} />} />
      <div className="cl-top">
        <Card title="Speed to lead" lift>
          <div className="cl-hero">
            <div className="cl-ring-wrap"><Gauge value={s.share} size={144} label="under 5 min" display={`${Math.round(s.share * 100)}%`} /></div>
            <div className="cl-stack">
              <div><span className="cl-big"><CountUp value={s.median_minutes ?? 0} format={(n) => n.toFixed(1)} /></span> <span className="cl-mini">median minutes to the first message</span></div>
              <div className="cl-mini">{s.touched} of {s.inbound_leads} inbound leads were answered, {s.within_target} of them within {s.target_minutes} minutes. {s.waiting > 0 ? `${s.waiting} are waiting (quiet hours in their time zone, or no mailbox with room).` : "None are waiting."}</div>
            </div>
          </div>
        </Card>
        <div className="cl-stats2">
          <Card><Stat label="Messages sent" value={o.sent} note={o.drafted ? `${o.drafted} more saved as drafts` : "since the start"} /></Card>
          <Card><Stat label="Replies" value={o.replies} note={`${(o.reply_rate * 100).toFixed(1)}% of sent`} /></Card>
          <Card><Stat label="Worth a conversation" value={o.positive_replies} note="interested or asking" /></Card>
          <Card><Stat label="Open pipeline" value={Math.round(o.pipeline_cents / 100)} format={(n) => formatCurrency(n)} note={`${formatCurrency(o.won_cents / 100)} won`} /></Card>
        </div>
      </div>
      <div className="cl-cols">
        <Card title="Where deals are">
          <div className="cl-funnel" role="list" aria-label="Deals by stage">
            {o.funnel.map((f) => (
              <div key={f.stage} className="cl-funnel__row" role="listitem">
                <span>{STAGE_LABEL[f.stage]}</span>
                <div className="cl-funnel__bar"><div className="cl-funnel__fill" style={{ width: `${(f.count / maxFunnel) * 100}%` }} /></div>
                <span className="sx-num" style={{ textAlign: "right" }}>{f.count}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Messages per day">
          {!o.daily.some((d) => d.sent) ? <EmptyState title="No messages yet" body="Run the jobs from the top bar and the first messages will show up here." /> : days === 1 ? <div className="cl-stack"><span className="cl-big">{total}</span><span className="cl-mini">sent or drafted today ({shown[0]?.d})</span></div> : <AreaChart data={shown} xKey="d" series={[{ key: "sent", label: "Sent or drafted" }]} height={200} />}
        </Card>
      </div>
      <Card title="Needs a person">
        <div className="cl-stack">
          <div className="sx-row" style={{ justifyContent: "space-between" }}><span>Replies waiting for a decision</span><Link href="/inbox"><Badge tone={o.open_replies ? "accent" : "neutral"}>{o.open_replies} open</Badge></Link></div>
          <div className="sx-row" style={{ justifyContent: "space-between" }}><span>Approvals in the queue</span><Link href="/approvals"><Badge tone={o.pending_approvals ? "accent" : "neutral"}>{o.pending_approvals} pending</Badge></Link></div>
          <div className="sx-row" style={{ justifyContent: "space-between" }}><span>Follow ups scheduled</span><Badge>{o.scheduled}</Badge></div>
          {paused.map((m) => (
            <div key={m.id} className="sx-row" role="alert"><AlertTriangle aria-hidden size={18} /><div><strong>{m.address} is paused</strong><div className="cl-mini">{m.paused_reason} <Link href="/deliverability">See Deliverability</Link></div></div><Badge tone="danger">paused</Badge></div>
          ))}
        </div>
      </Card>
      <div className="cl-mini">Demo clock: {new Date(o.now).toUTCString()}</div>
    </div>
  );
}
