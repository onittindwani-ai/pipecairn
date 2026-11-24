"use client";
import { useQuery } from "@tanstack/react-query";
import { Badge, TableSkeleton, formatWhen } from "@sendora/ui-kit";
import { StatusBadge, flagLabel } from "@/components/Parts";
import { get } from "@/lib/api";
import type { LeadDetail } from "@/lib/types";

export function LeadDetailBody({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["lead", id], queryFn: () => get<LeadDetail>(`/leads/${id}`) });
  if (!q.data) return <TableSkeleton rows={4} columns={2} />;
  const d = q.data;
  return (
    <div className="cl-stack">
      <div className="sx-row"><StatusBadge status={d.status} />{d.flags.map((f) => <Badge key={f} tone="warning">{flagLabel(f)}</Badge>)}</div>
      <div className="cl-mini">{d.title} at {d.company} · {d.timezone || "no time zone"}</div>
      <h3 style={{ margin: "13px 0 0" }}>{d.score === null ? "Not scored" : `Score ${d.score} of 100`}</h3>
      {Object.entries(d.score_breakdown).map(([k, v]) => {
        const max = ({ title: 30, size: 25, industry: 20, email: 15, source: 10 } as Record<string, number>)[k] ?? 30;
        return <div key={k} className="cl-stack" style={{ gap: 3 }}><div className="sx-row" style={{ justifyContent: "space-between" }}><span>{k}</span><span className="sx-num">{v} of {max}</span></div><div className="cl-bar"><span style={{ width: `${(v / max) * 100}%` }} /></div></div>;
      })}
      {d.score_explanation ? <p className="cl-mini">{d.score_explanation}</p> : null}
      <h3 style={{ margin: "13px 0 0" }}>Timeline</h3>
      <ul className="cl-list">{d.activities.map((a, i) => <li key={i} className="cl-item" style={{ cursor: "default" }}><span>{a.summary}</span><span className="cl-mini">{formatWhen(new Date(a.at))}</span></li>)}</ul>
    </div>
  );
}
