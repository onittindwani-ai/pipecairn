"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, CheckCheck, FileText, Gauge, KanbanSquare, ListOrdered, LogOut, Mail, Pause, Plug, ShieldCheck, Table2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AppShell, Badge, Button, CommandPalette, ConfirmDialog, notify, useTheme, type PaletteItem } from "@sendora/ui-kit";
import { api, get, post } from "@/lib/api";
import { useLiveRefresh, useMe, usePermissions, useSettings } from "@/lib/hooks";
import type { Overview } from "@/lib/types";

const NAV = [
  { id: "/", label: "Overview", icon: Gauge },
  { id: "/pipeline", label: "Pipeline", icon: KanbanSquare },
  { id: "/inbox", label: "Inbox", icon: Mail },
  { id: "/sequences", label: "Sequences", icon: ListOrdered },
  { id: "/leads", label: "Leads", icon: Table2 },
  { id: "/proposals", label: "Proposals", icon: FileText },
  { id: "/deliverability", label: "Deliverability", icon: Activity },
  { id: "/approvals", label: "Approvals", icon: CheckCheck },
  { id: "/integrations", label: "Integrations", icon: Plug },
  { id: "/audit", label: "Audit log", icon: ShieldCheck },
];

export function AppFrame({ children }: { children: ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const qc = useQueryClient();
  const me = useMe();
  const settings = useSettings();
  const { canWrite, isOwner } = usePermissions();
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => get<Overview>("/overview") });
  const { setChoice } = useTheme();
  const [palette, setPalette] = useState(false);
  const [confirmKill, setConfirmKill] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  useLiveRefresh();

  // "G" then a number goes to that page, as the command palette says. Ignored while typing and when a dialog is open.
  useEffect(() => {
    let armed = 0;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || t?.closest("input, textarea, select, [contenteditable=true], [role=dialog], [role=alertdialog]")) return;
      if (e.key === "g" || e.key === "G") { armed = Date.now(); return; }
      if (armed && Date.now() - armed < 1500 && /^[1-9]$/.test(e.key)) { armed = 0; const n = NAV[Number(e.key) - 1]; if (n) router.push(n.id); return; }
      armed = 0;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  const active = NAV.find((n) => (n.id === "/" ? path === "/" : path.startsWith(n.id)))?.id ?? "/";
  const demo = me.data?.demo_mode ?? false;
  const refresh = () => qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });

  const run = useMutation({
    mutationFn: () => post<{ send: { sent: number; drafted: number; deferred: number } }>("/demo/tick"),
    onSuccess: (r) => { notify.success(`Ran every job. Sent ${r.send.sent}, drafted ${r.send.drafted}, waiting ${r.send.deferred}.`); refresh(); },
    onError: (e: Error) => notify.error("The run failed", e.message),
  });
  const advance = useMutation({
    mutationFn: (hours: number) => post("/demo/advance", { hours }),
    onSuccess: () => { notify.info("Moved the demo clock forward."); refresh(); },
  });
  const toggleKill = useMutation({
    mutationFn: (on: boolean) => post("/settings", { kill_switch: on }),
    onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["settings"] }); },
    onError: (e: Error) => notify.error("Could not change the kill switch", e.message),
  });
  const reset = useMutation({
    mutationFn: () => post("/demo/reset"),
    onSuccess: () => { notify.success("Demo data reset."); refresh(); },
    onError: (e: Error) => notify.error("Could not reset", e.message),
  });

  const items: PaletteItem[] = useMemo(() => [
    ...NAV.map((n, i) => ({ id: `go-${n.id}`, label: `Go to ${n.label}`, group: "Navigate", shortcut: i < 9 ? ["G", String(i + 1)] : undefined, onSelect: () => router.push(n.id) })),
    { id: "signout", label: "Sign out", group: "Account", onSelect: () => void api("/session", { method: "DELETE" }).catch(() => null).then(() => window.location.assign("/login")) },
    ...(me.data?.role === "owner" ? [{ id: "kill", label: "Pause everything (kill switch)", group: "Account", onSelect: () => setConfirmKill(true) }] : []),
    { id: "dark", label: "Switch to dark theme", group: "Actions", onSelect: () => setChoice("dark") },
    { id: "light", label: "Switch to light theme", group: "Actions", onSelect: () => setChoice("light") },
    ...(demo && canWrite ? [{ id: "run", label: "Run every job now", group: "Demo", onSelect: () => void run.mutateAsync() }, { id: "adv", label: "Move the demo clock forward one day", group: "Demo", onSelect: () => void advance.mutateAsync(24) }] : []),
    ...(demo && isOwner ? [{ id: "reset", label: "Reset the demo data", group: "Demo", onSelect: () => setConfirmReset(true) }] : []),
  ], [router, setChoice, demo, run, advance, me.data?.role, canWrite, isOwner]);

  const s = settings.data;
  const o = overview.data;
  return (
    <>
      {/* One status strip that is always there, so nothing below it jumps when the mode is known. */}
      {s?.kill_switch ? (
        <div className="cl-banner cl-banner--danger" role="status"><strong>Kill switch is on.</strong> <span className="cl-hide-sm">Nothing is sent and no reply can be approved.</span> <Button size="sm" variant="ghost" onClick={async () => { await toggleKill.mutateAsync(false); }}>Turn it off</Button></div>
      ) : s?.effective_mode === "draft" ? (
        <div className="cl-banner" role="status"><strong>Draft mode.</strong> <span className="cl-hide-sm">Messages are saved as drafts. Nothing is sent.</span></div>
      ) : s && demo ? (
        <div className="cl-banner cl-banner--info" role="status"><strong>Demo mode.</strong> <span className="cl-grow cl-hide-sm">Demo data. Nothing leaves this machine.</span><span className="cl-grow show-sm-only" />
          {canWrite ? <><Button size="sm" variant="primary" onClick={async () => { await run.mutateAsync(); }}>Run now</Button>
          <Button size="sm" onClick={async () => { await advance.mutateAsync(24); }}>+1 day</Button></> : <span className="cl-mini">Read only: the {me.data?.role ?? "viewer"} role cannot run jobs.</span>}</div>
      ) : s ? (
        <div className="cl-banner cl-banner--live" role="status"><strong>Live.</strong> <span className="cl-hide-sm">Messages are really sent, inside the limits.</span></div>
      ) : (
        <div className="cl-banner cl-banner--info" role="status">Checking the sending mode...</div>
      )}
      <AppShell
        productName="Pipecairn"
        nav={NAV.map((n) => ({ ...n, count: n.id === "/inbox" ? o?.open_replies || undefined : n.id === "/approvals" ? o?.pending_approvals || undefined : undefined }))}
        activeId={active}
        onNavigate={(id) => router.push(id)}
        onOpenPalette={() => setPalette(true)}
        breadcrumbs={["Pipecairn", NAV.find((n) => n.id === active)?.label ?? ""]}
        topRight={
          <>
            {me.data?.role === "owner" ? <Button size="sm" variant="ghost" feedback={false} className="cl-iconify" aria-label={s?.kill_switch ? "Turn the kill switch off" : "Pause all"} onClick={() => (s?.kill_switch ? toggleKill.mutate(false) : setConfirmKill(true))}><Pause size={14} aria-hidden /><span className="cl-hide-sm">{s?.kill_switch ? "Turn it off" : "Pause all"}</span></Button> : null}
            {me.data ? <span className="cl-hide-sm"><Badge tone="accent">{me.data.role}</Badge></span> : null}
            <Button size="sm" variant="ghost" feedback={false} className="cl-iconify" aria-label="Sign out" onClick={async () => { await api("/session", { method: "DELETE" }).catch(() => null); window.location.assign("/login"); }}><LogOut size={14} aria-hidden /><span className="cl-hide-sm">Sign out</span></Button>
          </>
        }
      >
        {children}
      </AppShell>
      <CommandPalette items={items} open={palette} onOpenChange={setPalette} />
      <ConfirmDialog open={confirmKill} onOpenChange={setConfirmKill} title="Pause everything?" description="The kill switch stops all sending and approving at once. You can turn it off again from the banner." confirmLabel="Pause all" destructive onConfirm={() => void toggleKill.mutateAsync(true)} />
      <ConfirmDialog open={confirmReset} onOpenChange={setConfirmReset} title="Reset the demo?" description="This puts the sample seed data back and clears everything you did in the demo." confirmLabel="Reset" destructive onConfirm={() => void reset.mutateAsync()} />
    </>
  );
}
