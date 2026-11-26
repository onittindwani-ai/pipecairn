"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, TableSkeleton, formatWhen, notify } from "@sendora/ui-kit";
import { StatusBadge, flagLabel } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { usePermissions } from "@/lib/hooks";
import type { LeadDetail } from "@/lib/types";

export function LeadDetailBody({ id }: { id: number }) {
  const qc = useQueryClient();
  const { canWrite } = usePermissions();
  const q = useQuery({ queryKey: ["lead", id], queryFn: () => get<LeadDetail>(`/leads/${id}`) });
  const notSent = useMutation({
    mutationFn: (messageId: number) => post<{ result: "retry" | "paused" | "stopped" }>(`/messages/${messageId}/not-sent`),
    onSuccess: (r) => {
      if (r.result === "retry") notify.success("It will be sent again at the next run.");
      else if (r.result === "paused") notify.info("Marked as not sent. This person asked to wait, so it is sent when the wait is over.");
      else notify.info("Marked as not sent. This person has been stopped since, so nothing will be sent.");
      qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== "me" });
    },
    onError: (e: Error) => notify.error("Could not do that", e.message),
  });
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
      {d.messages.filter((m) => m.status === "unconfirmed").map((m) => (
        <div key={m.id} className="cl-stack" role="note" style={{ borderTop: "1px solid var(--sx-line)", paddingTop: 13 }}>
          <strong>A message may not have been sent</strong>
          <span className="cl-mini">The connection broke while &quot;{m.subject || "(no subject)"}&quot; was being sent, so there is no way to know whether it left. It will not be sent again by itself. Look in the Sent folder of the mailbox.</span>
          {canWrite ? <span className="sx-row"><Button size="sm" variant="ghost" onClick={async () => { await notSent.mutateAsync(m.id); }}>It is not in the Sent folder, send it again</Button></span> : null}
        </div>
      ))}
      <h3 style={{ margin: "13px 0 0" }}>Timeline</h3>
      <ul className="cl-list">{d.activities.map((a, i) => <li key={i} className="cl-item" style={{ cursor: "default" }}><span>{a.summary}</span><span className="cl-mini">{formatWhen(new Date(a.at))}</span></li>)}</ul>
    </div>
  );
}
