"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CopyButton, EmptyState, SegmentedControl, SplitView, formatWhen, notify } from "@sendora/ui-kit";
import { IntentBadge, ListSkeleton, LoadError, PageHead, Textarea, intentLabel } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { usePermissions } from "@/lib/hooks";
import type { ReplyRow, UnmatchedMail } from "@/lib/types";

const ACTION_TEXT: Record<string, string> = { book_call: "Offer times and book a call", answer_question: "Answer their question", ask_referral: "Ask who the right person is", snooze: "Come back on the date below", wait: "Wait until they are back", suppressed: "Stopped and never contacted again", unverified_bounce: "Read it: it says the mail bounced, but it is not a real delivery report, so nothing was changed" };

function Detail({ r }: { r: ReplyRow }) {
  const qc = useQueryClient();
  const { canWrite } = usePermissions();
  const key = `cl-draft-${r.id}`;
  const [draft, setDraft] = useState(r.draft_reply);
  const [slot, setSlot] = useState("");
  useEffect(() => { try { setDraft(sessionStorage.getItem(key) ?? r.draft_reply); } catch { setDraft(r.draft_reply); } }, [key, r.draft_reply]);
  const slots = useQuery({ queryKey: ["slots", r.id], queryFn: () => get<string[]>(`/inbox/${r.id}/slots`), enabled: r.intent === "interested" && !r.handled });
  const refresh = () => qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
  const approve = useMutation({
    mutationFn: () => post<{ status: string; reason: string }>(`/inbox/${r.id}/approve`, { body: draft }),
    onSuccess: (x) => { try { sessionStorage.removeItem(key); } catch { /* ignore */ } x.status === "sent" ? notify.success("Reply sent.") : x.status === "drafted" ? notify.info("Saved as a draft. Draft mode is on, so nothing was sent.") : x.status === "deferred" ? notify.info(`Not sent yet. It is waiting: ${x.reason.replaceAll("_", " ")}.`) : notify.error("Not sent", `Stopped by a safety check: ${x.reason.replaceAll("_", " ")}.`); refresh(); },
    onError: (e: Error) => notify.error("Could not send", e.message),
  });
  const reject = useMutation({ mutationFn: () => post(`/inbox/${r.id}/reject`), onSuccess: () => { notify.info("Draft rejected."); refresh(); } });
  const dismiss = useMutation({ mutationFn: () => post(`/inbox/${r.id}/dismiss`), onSuccess: () => { notify.info("Marked as read."); refresh(); }, onError: (e: Error) => notify.error("Could not mark it", e.message) });
  const book = useMutation({
    mutationFn: () => post<{ starts_at: string }>(`/inbox/${r.id}/book`, { slot }),
    onSuccess: (x) => { notify.success(`Call booked for ${new Date(x.starts_at).toUTCString()}.`); refresh(); },
    onError: (e: Error) => notify.error("Could not book", e.message),
  });
  const hasFill = draft.includes("[[FILL IN");
  const blank = !draft.trim();
  return (
    <Card>
      <div className="cl-stack">
        <div className="cl-item__top"><div><strong>{r.name}</strong> <span className="cl-mini">{r.company} · {r.email}</span></div><IntentBadge intent={r.intent} /></div>
        <blockquote className="cl-quote cl-pre" style={{ margin: 0 }}>{r.body}</blockquote>
        <div className="cl-mini">Read as <strong>{intentLabel(r.intent)}</strong> ({Math.round(r.confidence * 100)}% sure). {r.summary}</div>
        {r.suggested_action ? <div className="sx-row"><span className="cl-mini">Suggested next step:</span><span className="cl-chip">{ACTION_TEXT[r.suggested_action] ?? r.suggested_action}</span>{r.return_on ? <span className="cl-chip">Back on {r.return_on}</span> : null}</div> : null}
        {r.approval_id && !r.handled ? (
          <>
            <Textarea label="Draft reply" value={draft} onChange={(e) => { setDraft(e.target.value); try { sessionStorage.setItem(key, e.target.value); } catch { /* ignore */ } }}
              error={hasFill ? "Replace the [[FILL IN ...]] part with your own words before you approve." : null} hint="You can edit this. Nothing is sent until you approve." rows={9} readOnly={!canWrite} />
            {canWrite ? <div className="sx-row">
              <Button variant="primary" disabled={hasFill || blank} disabledReason={blank ? "Write a message first, or reject the draft" : "Fill in the marked part first"} onClick={async () => { await approve.mutateAsync(); }}>Approve and send</Button>
              <Button variant="ghost" onClick={async () => { await reject.mutateAsync(); }}>Reject</Button>
              <CopyButton value={draft} label="Copy draft" />
            </div> : <span className="cl-mini">Read only: the viewer role cannot approve or send.</span>}
            {canWrite && r.intent === "interested" ? (
              <div className="cl-stack" style={{ borderTop: "1px solid var(--sx-line)", paddingTop: 13 }}>
                <strong>Or book a call now</strong>
                {slots.data?.length ? (
                  <div className="sx-row">
                    <select className="cl-select" aria-label="Open time" value={slot} onChange={(e) => setSlot(e.target.value)}><option value="">Choose a time</option>{slots.data.map((t) => <option key={t} value={t}>{new Date(t).toUTCString()}</option>)}</select>
                    <Button disabled={!slot} disabledReason="Choose a time first" onClick={async () => { await book.mutateAsync(); }}>Book it</Button>
                  </div>
                ) : <span className="cl-mini">{slots.isLoading ? "Looking for open times..." : "No open times found."}</span>}
              </div>
            ) : null}
          </>
        ) : r.handled ? <Badge tone="success">Handled</Badge> : canWrite ? <div className="sx-row"><Button variant="ghost" onClick={async () => { await dismiss.mutateAsync(); }}>Mark as read</Button><span className="cl-mini">Nothing is sent. This only takes it off the list.</span></div> : null}
      </div>
    </Card>
  );
}

function UnmatchedCard() {
  const qc = useQueryClient();
  const { canWrite } = usePermissions();
  const q = useQuery({ queryKey: ["inbox-unmatched"], queryFn: () => get<UnmatchedMail[]>("/inbox/unmatched") });
  const dismiss = useMutation({ mutationFn: (id: number) => post(`/inbox/unmatched/${id}/dismiss`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["inbox-unmatched"] }); }, onError: (e: Error) => notify.error("Could not mark it", e.message) });
  if (!q.data?.length) return null;
  return (
    <Card title={`Mail from addresses that are not leads (${q.data.length})`}>
      <p className="cl-mini" style={{ marginTop: 0 }}>An alias, a forward, a colleague or a stranger wrote to the inbox. Nothing was done with these. Read them, and write back yourself if it matters.</p>
      <ul className="cl-list">{q.data.map((m) => (
        <li key={m.id} className="cl-item" style={{ cursor: "default" }}>
          <span className="cl-item__top"><strong>{m.from || "unknown sender"}</strong><span className="cl-mini">{formatWhen(new Date(m.created_at))}</span></span>
          <span className="cl-item__line">{m.subject || "(no subject)"}</span>
          <blockquote className="cl-quote cl-pre" style={{ margin: 0 }}>{m.snippet}</blockquote>
          {canWrite ? <span className="sx-row"><Button size="sm" variant="ghost" onClick={async () => { await dismiss.mutateAsync(m.id); }}>Mark as read</Button></span> : null}
        </li>))}</ul>
    </Card>
  );
}

export default function InboxPage() {
  const [view, setView] = useState<"open" | "all">("open");
  const [sel, setSel] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["inbox", view], queryFn: () => get<ReplyRow[]>(`/inbox${view === "open" ? "?open=true" : ""}`) });
  const rows = q.data ?? [];
  const current = rows.find((r) => r.id === sel) ?? rows[0];
  return (
    <div className="cl-page">
      <PageHead title="Inbox" sub="Replies from leads, read for you. Anything that would send a message waits for your approval." actions={<SegmentedControl label="Show" value={view} onChange={setView} options={[{ value: "open", label: "Open" }, { value: "all", label: "All" }]} />} />
      <UnmatchedCard />
      {q.isError ? <LoadError error={q.error} onRetry={() => q.refetch()} what="the inbox" /> : !q.data ? <ListSkeleton rows={6} /> : rows.length === 0 ? (
        <Card><EmptyState title={view === "open" ? "Nothing needs you" : "No replies yet"} body="When a lead answers, it appears here with a suggested next step. In the demo, press Run now, then +1 day, a few times." /></Card>
      ) : (
        <SplitView
          list={<Card><ul className="cl-list" aria-label="Replies">{rows.map((r) => (
            <li key={r.id}><button className="cl-item" aria-current={current?.id === r.id} onClick={() => setSel(r.id)}>
              <span className="cl-item__top"><strong>{r.name}</strong><IntentBadge intent={r.intent} /></span>
              <span className="cl-item__line">{r.body}</span><span className="cl-mini">{formatWhen(new Date(r.created_at))}</span>
            </button></li>))}</ul></Card>}
          detail={current ? <Detail key={current.id} r={current} /> : <span />}
        />
      )}
    </div>
  );
}
