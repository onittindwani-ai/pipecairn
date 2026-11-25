export interface SpeedToLead { inbound_leads: number; touched: number; waiting: number; within_target: number; target_minutes: number; share: number; median_minutes: number | null }
export interface Overview {
  sent: number; drafted: number; replies: number; positive_replies: number; reply_rate: number; pipeline_cents: number; won_cents: number;
  speed_to_lead: SpeedToLead; funnel: { stage: string; count: number }[]; daily: { d: string; sent: number }[];
  pending_approvals: number; open_replies: number; unmatched_mail: number; scheduled: number; now: string;
}
export interface LeadRow { id: number; name: string; email: string; company: string; title: string; status: string; score: number | null; source: string; flags: string[]; timezone: string; created_at: string }
export interface LeadList { count: number; total: number; rows: LeadRow[] }
export interface LeadDetail extends LeadRow {
  phone: string; sms_consent: boolean; industry: string; company_size: number; score_breakdown: Record<string, number>; score_explanation: string; deal: Deal | null;
  activities: { kind: string; summary: string; at: string }[]; messages: { id: number; channel: string; direction: string; to: string; subject: string; body: string; status: string; blocked_reason: string; at: string }[];
  enrollments: { id: number; status: string; step: number; next_send_at: string | null; stop_reason: string }[];
}
export interface Deal { id: number; lead_id: number; stage: string; value_cents: number; name: string; company: string; score: number | null; closed_at: string | null; lost_reason: string }
export interface Pipeline { stages: string[]; deals: Deal[] }
export interface ReplyRow {
  id: number; lead_id: number; channel: string; intent: string; confidence: number; summary: string; body: string; subject: string; suggested_action: string; draft_reply: string;
  approval_id: number | null; handled: boolean; return_on: string; created_at: string; name: string; company: string; email: string; score: number | null;
}
export interface StepRow { position: number; channel: "email" | "sms"; delay_hours: number; subject: string; body: string }
export interface SequenceRow { id: number; name: string; active: boolean; steps: StepRow[]; variables: string[] }
export interface Mailbox { id: number; address: string; daily_cap: number; sent_today: number; sent_total: number; bounce_count: number; bounce_rate: number; warmup_days: number; spf_ok: boolean; dkim_ok: boolean; dmarc_ok: boolean; is_active: boolean; paused_reason: string; health: number }
export interface ApprovalRow { id: number; action: string; summary: string; risk: string; status: string; requested_by: string; decided_by: string | null; note: string | null; created_at: string; payload: Record<string, unknown>; draft: string; reply_id: number | null; reply_open: boolean }
export interface UnmatchedMail { id: number; from: string; to: string; subject: string; snippet: string; handled: boolean; created_at: string }
export interface AuditRow { id: number; actor: string; action: string; target: string | null; detail: Record<string, unknown>; at: string }
export interface AdapterRow { category: string; name: string; tier: string; live_verified: boolean; notes: string; selected: boolean; env_vars: string[]; configured: boolean }
export interface Integrations { categories: string[]; adapters: AdapterRow[]; demo_mode: boolean }
export interface Settings { mode: string; effective_mode: string; kill_switch: boolean; demo_mode: boolean; problems: string[]; quiet_hours: string; weekends: boolean }
export interface Me { user: string; role: string; demo_mode: boolean }
export interface ProposalRow { id: number; lead_id: number; title: string; scope: string[]; price_cents: number; status: string; body_md: string; created_at: string }
