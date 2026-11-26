"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, MessageSquare, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Card, EmptyState, Field, SegmentedControl, notify } from "@sendora/ui-kit";
import { ListSkeleton, LoadError, PageHead, Textarea } from "@/components/Parts";
import { get, post, put } from "@/lib/api";
import { useMe, usePermissions } from "@/lib/hooks";
import type { SequenceRow, StepRow } from "@/lib/types";

function useDebounced<T>(v: T, ms = 300): T {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

const STARTER = {
  name: "First touch and follow up",
  steps: [
    { channel: "email", delay_hours: 0, subject: "Quick idea for {{company}}", body: "Hi {{first_name}},\n\nI help {{industry}} teams answer new enquiries within minutes. Would a short call this week be useful?\n\nBest,\n{{sender_name}}" },
    { channel: "email", delay_hours: 72, subject: "", body: "Hi {{first_name}}, a short follow up in case my first note got buried. Happy to send a two line summary instead of a call.\n\n{{sender_name}}" },
  ],
};

export default function SequencesPage() {
  const qc = useQueryClient();
  const me = useMe();
  const createStarter = useMutation({
    mutationFn: () => post("/sequences", STARTER),
    onSuccess: () => { notify.success("Starter sequence created. Edit it to say what you do."); qc.invalidateQueries({ queryKey: ["sequences"] }); },
    onError: (e: Error) => notify.error("Could not create the sequence", e.message),
  });
  const { isOwner: canWrite } = usePermissions(); // editing a sequence changes what goes out to people, so it is owner only
  const q = useQuery({ queryKey: ["sequences"], queryFn: () => get<SequenceRow[]>("/sequences") });
  const [name, setName] = useState("");
  const [steps, setSteps] = useState<StepRow[]>([]);
  const [sel, setSel] = useState(0);
  useEffect(() => { if (q.data?.[0]) { setName(q.data[0].name); setSteps(q.data[0].steps); } }, [q.data]);
  const step = steps[sel];
  const dStep = useDebounced(step);
  const preview = useQuery({ queryKey: ["preview", dStep?.subject, dStep?.body], queryFn: () => post<{ subject: string; body: string; lead: string | null; error: string | null }>("/sequences/preview", { subject: dStep!.subject, body: dStep!.body }), enabled: !!dStep });
  const save = useMutation({
    mutationFn: () => put(`/sequences/${q.data![0]!.id}`, { name, steps: steps.map(({ channel, delay_hours, subject, body }) => ({ channel, delay_hours, subject, body })) }),
    onSuccess: () => { notify.success("Sequence saved."); qc.invalidateQueries({ queryKey: ["sequences"] }); },
    onError: (e: Error) => notify.error("Not saved", e.message),
  });
  const patch = (i: number, p: Partial<StepRow>) => setSteps((s) => s.map((x, j) => (j === i ? { ...x, ...p } : x)));
  if (q.isError) return <div className="cl-page"><PageHead title="Sequences" /><LoadError error={q.error} onRetry={() => q.refetch()} what="sequences" /></div>;
  if (!q.data) return <div className="cl-page"><PageHead title="Sequences" /><ListSkeleton /></div>;
  if (!q.data.length) return <div className="cl-page"><PageHead title="Sequences" /><Card><EmptyState title="No sequence yet" body="Nothing is sent until there is a sequence. Create a starter you can edit." />{me.data?.role === "owner" ? <div style={{ marginTop: 13 }}><Button variant="primary" onClick={async () => { await createStarter.mutateAsync(); }}>Create a starter sequence</Button></div> : <p className="cl-mini">Only the owner can create a sequence.</p>}</Card></div>;
  const vars = q.data[0]!.variables;
  const unknownField = (t: string) => [...t.matchAll(/\{\{\s*([\w.]+)\s*\}\}/g)].map((m) => m[1]!).find((f) => !vars.includes(f));
  const badField = steps.findIndex((x) => unknownField(`${x.subject} ${x.body}`));
  const problem = !name.trim() ? "Give the sequence a name" : steps.findIndex((x) => !x.body.trim()) >= 0 ? `Step ${steps.findIndex((x) => !x.body.trim()) + 1} has no message` : steps[0]?.channel === "email" && !steps[0].subject.trim() ? "The first email needs a subject" : badField >= 0 ? `Step ${badField + 1} uses a field that does not exist: {{${unknownField(`${steps[badField]!.subject} ${steps[badField]!.body}`)}}}` : null;
  return (
    <div className="cl-page">
      <PageHead title="Sequences" sub="The messages each lead receives, and how long to wait between them. Sending stops by itself when they reply, opt out or book." actions={<Button variant="primary" disabled={!canWrite || !!problem} disabledReason={canWrite ? problem ?? "" : "Only the owner can change sequences"} onClick={async () => { await save.mutateAsync(); }}>Save sequence</Button>} />
      <div className="cl-two--rev cl-two">
        <Card>
          <Field label="Sequence name" value={name} onChange={setName} maxLength={120} />
          <div className="cl-timeline" style={{ marginTop: 21 }}>
            {steps.map((s, i) => (
              <div key={i} className="cl-step">
                <div className="cl-step__dot" aria-hidden>{i + 1}</div>
                <div className="cl-stack" onFocusCapture={() => setSel(i)} style={{ outline: sel === i ? "none" : undefined }}>
                  <div className="cl-delay">{i === 0 ? "Sent right away" : `Wait ${s.delay_hours} hours after the step before`}</div>
                  <div className="sx-row">
                    <SegmentedControl label={`Step ${i + 1} channel`} value={s.channel} onChange={(v) => patch(i, { channel: v })} options={[{ value: "email", label: "Email" }, { value: "sms", label: "Text" }]} />
                    <Field label="Wait (hours)" type="number" min={0} value={String(s.delay_hours)} onChange={(v) => patch(i, { delay_hours: Math.max(0, Math.min(1440, Number(v) || 0)) })} validate={(v) => (Number(v) >= 0 ? null : "Use zero or more hours")} />
                  </div>
                  {s.channel === "email" ? <Field label="Subject" value={s.subject} onChange={(v) => patch(i, { subject: v })} maxLength={200} /> : null}
                  <Textarea label={s.channel === "sms" ? "Text message" : "Message"} value={s.body} onChange={(e) => patch(i, { body: e.target.value })} maxLength={s.channel === "sms" ? 320 : 5000} hint={s.channel === "sms" ? `${s.body.length} of 320 characters. Add "Reply STOP to opt out".` : undefined} />
                  <Button size="sm" variant="ghost" feedback={false} disabled={!canWrite || steps.length < 2} disabledReason={canWrite ? "A sequence needs at least one step" : "Only the owner can change sequences"} onClick={() => { setSteps((x) => x.filter((_, j) => j !== i)); setSel(0); }}><Trash2 size={14} aria-hidden />Remove step</Button>
                </div>
              </div>
            ))}
          </div>
          <Button feedback={false} disabled={!canWrite} disabledReason="Only the owner can change sequences" onClick={() => { setSteps((s) => [...s, { position: s.length, channel: "email", delay_hours: 72, subject: "", body: "Hi {{first_name}}, " }]); setSel(steps.length); }}><Plus size={14} aria-hidden />Add a step</Button>
          <p className="cl-mini">Fields you can use: {vars.map((v) => `{{${v}}}`).join(", ")}</p>
        </Card>
        <Card title={`Preview of step ${sel + 1}`}>
          {step ? (
            <div className="cl-stack" aria-live="polite">
              <div className="sx-row">{step.channel === "email" ? <Mail size={16} aria-hidden /> : <MessageSquare size={16} aria-hidden />}<span className="cl-mini">As {preview.data?.lead ?? "a lead"} would see it</span></div>
              {preview.data?.error ? <p className="sx-field__error" role="alert">{preview.data.error}</p> : (
                <>
                  {step.channel === "email" ? <strong>{preview.data?.subject}</strong> : null}
                  <p className="cl-pre">{preview.data?.body}</p>
                </>
              )}
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
