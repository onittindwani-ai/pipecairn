"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Dialog, Field, Button, Kanban, Sheet, formatCurrency, notify } from "@sendora/ui-kit";
import { LeadDetailBody } from "@/components/LeadDetail";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { usePermissions } from "@/lib/hooks";
import type { Deal, Pipeline } from "@/lib/types";

const TITLES: Record<string, string> = { new: "New", contacted: "Contacted", replied: "Replied", meeting: "Meeting", proposal: "Proposal", won: "Won", lost: "Lost" };

export default function PipelinePage() {
  const qc = useQueryClient();
  const { canWrite } = usePermissions();
  const q = useQuery({ queryKey: ["pipeline"], queryFn: () => get<Pipeline>("/pipeline") });
  const [lost, setLost] = useState<{ id: number; from: string } | null>(null);
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState<Deal | null>(null);

  const setStage = (id: number, stage: string) => qc.setQueryData<Pipeline>(["pipeline"], (p) => (p ? { ...p, deals: p.deals.map((d) => (d.id === id ? { ...d, stage } : d)) } : p));

  const move = useMutation({
    mutationFn: ({ id, stage, lost_reason }: { id: number; stage: string; from: string; lost_reason?: string }) => post<Deal>(`/pipeline/${id}/move`, { stage, lost_reason: lost_reason ?? "" }),
    onMutate: ({ id, stage }) => setStage(id, stage), // optimistic: the card moves at once
    onError: (e: Error, v) => { setStage(v.id, v.from); notify.error("The move was not saved", `${e.message} The card went back.`); },
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["overview"] });
      void notify.undo(`Moved to ${TITLES[v.stage]}`, () => move.mutate({ id: v.id, stage: v.from, from: v.stage }));
    },
  });

  if (q.isError) return <div className="cl-page"><PageHead title="Pipeline" /><LoadError error={q.error} onRetry={() => q.refetch()} what="the pipeline" /></div>;
  if (!q.data) return <div className="cl-page"><PageHead title="Pipeline" /><ListSkeleton rows={6} /></div>;
  const items = q.data.deals.map((d) => ({ id: String(d.id), columnId: d.stage, deal: d }));
  return (
    <div className="cl-page">
      <PageHead title="Pipeline" sub="Drag a card to move a deal. Every move can be undone for a few seconds." />
      <div className="cl-kanban-wrap">
        <Kanban
          label="Deal pipeline"
          columns={q.data.stages.map((s) => ({ id: s, title: TITLES[s] ?? s }))}
          items={items}
          cardLabel={(i) => `${(i as (typeof items)[number]).deal.name || "Unnamed"}, ${(i as (typeof items)[number]).deal.company}`}
          onOpen={(i) => setOpen((i as (typeof items)[number]).deal)}
          onMove={(id, to, from) => {
            if (to === from) return;
            if (!canWrite) { notify.info("Read only: the viewer role cannot move deals."); return; }
            if (to === "lost") setLost({ id: Number(id), from });
            else move.mutate({ id: Number(id), stage: to, from });
          }}
          renderCard={(i) => {
            const d = (i as (typeof items)[number]).deal;
            return (
              <div style={{ display: "grid", gap: 3 }}>
                <strong>{d.name || "Unnamed"}</strong>
                <span className="cl-mini">{d.company}</span>
                <span className="sx-row" style={{ gap: 8 }}><span className="sx-num">{formatCurrency(d.value_cents / 100)}</span>{d.score !== null ? <Badge>{d.score}</Badge> : null}</span>
              </div>
            );
          }}
        />
      </div>
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)} title={open?.name || "Unnamed"} description={open?.company}>{open ? <LeadDetailBody id={open.lead_id} /> : null}</Sheet>
      <Dialog open={lost !== null} onOpenChange={(o) => { if (!o) { setLost(null); setReason(""); } }} title="Mark this deal as lost" description="Add a short reason so you can learn from it later."
        actions={<Button variant="danger" disabled={!reason.trim()} disabledReason="Write a reason first" onClick={async () => { const l = lost!; await move.mutateAsync({ id: l.id, stage: "lost", from: l.from, lost_reason: reason.trim() }); setLost(null); setReason(""); }}>Mark as lost</Button>}>
        <Field label="Reason" value={reason} onChange={setReason} maxLength={200} placeholder="For example: chose a cheaper option" />
      </Dialog>
    </div>
  );
}
