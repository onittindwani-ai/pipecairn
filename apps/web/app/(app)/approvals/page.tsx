"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Badge, Button, Card, EmptyState, formatWhen, notify } from "@sendora/ui-kit";
import { ListSkeleton, LoadError, PageHead, plainWords } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { usePermissions } from "@/lib/hooks";
import type { ApprovalRow } from "@/lib/types";

const ACTION_WORDS: Record<string, string> = { "reply.send": "Send a reply" };

export default function ApprovalsPage() {
  const qc = useQueryClient();
  const { canWrite } = usePermissions();
  const q = useQuery({ queryKey: ["approvals"], queryFn: () => get<ApprovalRow[]>("/approvals") });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) => post<{ status: string; reason?: string }>(`/approvals/${id}/decide`, { approve }),
    onSuccess: (r) => { r.status === "sent" ? notify.success("Approved and sent.") : r.status === "drafted" ? notify.info("Approved. Draft mode is on, so it was saved, not sent.") : r.status === "stop" || r.status === "blocked" || r.status === "failed" ? notify.error("Not sent", `A safety check stopped it: ${(r.reason ?? "").replaceAll("_", " ")}.`) : r.status === "deferred" ? notify.info(`Not sent yet. It is waiting: ${(r.reason ?? "").replaceAll("_", " ")}.`) : notify.success(r.status === "rejected" ? "Rejected." : "Approved."); qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== "me" }); },
    onError: (e: Error) => notify.error("Could not decide", e.message),
  });
  if (q.isError) return <div className="cl-page"><PageHead title="Approvals" /><LoadError error={q.error} onRetry={() => q.refetch()} what="approvals" /></div>;
  if (!q.data) return <div className="cl-page"><PageHead title="Approvals" /><ListSkeleton /></div>;
  const pending = q.data.filter((a) => a.status === "pending"), done = q.data.filter((a) => a.status !== "pending");
  const tone = (r: string) => (r === "high" ? "danger" : r === "medium" ? "warning" : "neutral") as "danger" | "warning" | "neutral";
  return (
    <div className="cl-page">
      <PageHead title="Approvals" sub="Anything risky waits here for an owner or an approver. A draft that still has a fill in part cannot be approved." />
      <Card title={`Waiting (${pending.length})`}>
        {pending.length === 0 ? <EmptyState title="Nothing is waiting" body="Replies that need an answer will show up here and in the Inbox." /> : (
          <ul className="cl-list">{pending.map((a) => (
            <li key={a.id} className="cl-item" style={{ cursor: "default" }}>
              <span className="cl-item__top"><strong>{plainWords(a.summary)}</strong><Badge tone={tone(a.risk)}>{a.risk} risk</Badge></span>
              <span className="cl-mini">{ACTION_WORDS[a.action] ?? plainWords(a.action)} · requested by {a.requested_by} · {formatWhen(new Date(a.created_at))}{a.action === "reply.send" ? <> · <Link href="/inbox">Read the draft in the Inbox</Link></> : null}</span>
              {canWrite ? <span className="sx-row">
                <Button size="sm" variant="primary" onClick={async () => { await decide.mutateAsync({ id: a.id, approve: true }); }}>Approve</Button>
                <Button size="sm" variant="ghost" onClick={async () => { await decide.mutateAsync({ id: a.id, approve: false }); }}>Reject</Button>
              </span> : <span className="cl-mini">Read only: the viewer role cannot decide.</span>}
            </li>))}</ul>
        )}
      </Card>
      <Card title="Recently decided">
        <ul className="cl-list">{done.slice(0, 20).map((a) => <li key={a.id} className="cl-item" style={{ cursor: "default" }}><span className="cl-item__top"><span>{plainWords(a.summary)}</span><Badge tone={a.status === "approved" ? "success" : "neutral"}>{a.status}</Badge></span><span className="cl-mini">{a.decided_by ? `by ${a.decided_by}` : ""}</span></li>)}</ul>
        {done.length === 0 ? <span className="cl-mini">Nothing decided yet.</span> : null}
      </Card>
    </div>
  );
}
