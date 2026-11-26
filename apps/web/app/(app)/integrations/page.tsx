"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Card, ConnectionWizard, CopyButton } from "@sendora/ui-kit";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { usePermissions } from "@/lib/hooks";
import type { Integrations } from "@/lib/types";

const LABEL: Record<string, string> = { email: "Email", sms: "Text messages", calendar: "Calendar", crm: "CRM", esign: "Signing" };
const TIER: Record<string, string> = { A: "Built and tested against a mock", B: "Built from public docs, not run live", C: "Recipe prompt only" };

export default function IntegrationsPage() {
  const { canWrite } = usePermissions();
  const q = useQuery({ queryKey: ["integrations"], queryFn: () => get<Integrations>("/integrations") });
  const [status, setStatus] = useState<Record<string, "todo" | "ok" | "error">>({});
  if (q.isError) return <div className="cl-page"><PageHead title="Integrations" /><LoadError error={q.error} onRetry={() => q.refetch()} what="integrations" /></div>;
  if (!q.data) return <div className="cl-page"><PageHead title="Integrations" /><ListSkeleton /></div>;
  return (
    <div className="cl-page">
      <PageHead title="Integrations" sub="Which tool does each job, and whether it answers. No adapter here has been run against the real service. 'Tested' means a local mock server written from the vendor's public docs." />
      <p className="cl-mini" data-testid="tier-legend">{Object.entries(TIER).map(([k, v]) => `Tier ${k}: ${v.charAt(0).toLowerCase()}${v.slice(1)}.`).join(" ")}</p>
      <Card title="Test each connection">
        <ConnectionWizard
          onStatus={(id, s) => setStatus((x) => ({ ...x, [id]: s }))}
          steps={q.data.categories.map((c) => ({
            id: c, title: LABEL[c] ?? c, description: `Using: ${q.data!.adapters.find((a) => a.category === c && a.selected)?.name ?? "none"}`, status: status[c] ?? "todo",
            onTest: !canWrite ? undefined : async () => { const r = await post<{ ok: boolean; detail: string }>(`/integrations/${c}/test`); if (!r.ok) throw new Error(r.detail); },
          }))}
        />
      </Card>
      {q.data.categories.map((c) => (
        <Card key={c} title={LABEL[c] ?? c}>
          <ul className="cl-list">{q.data!.adapters.filter((a) => a.category === c).map((a) => (
            <li key={a.name} className="cl-item" style={{ cursor: "default" }}>
              <span className="cl-item__top"><strong>{a.name}</strong><span className="sx-row">{a.selected ? <Badge tone="accent">selected</Badge> : null}<Badge tone={a.tier === "A" ? "success" : a.tier === "B" ? "warning" : "neutral"}>tier {a.tier}</Badge>{a.live_verified ? <Badge tone="success">verified live</Badge> : <Badge>not verified live</Badge>}</span></span>
              <span className="cl-mini">{a.notes || TIER[a.tier]}</span>
              {a.env_vars.length ? <span className="sx-row">{a.env_vars.map((v) => <CopyButton key={v} value={v} label={v} />)}<span className="cl-mini">{a.configured ? "All set in this environment" : "Not set in this environment"}</span></span> : null}
            </li>))}</ul>
        </Card>
      ))}
    </div>
  );
}
