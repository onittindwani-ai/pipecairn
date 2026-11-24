# Design notes

Written before the pages and the app CSS. The look comes from the shared UI kit (`packages/ui-kit`); this file says what Pipecairn adds on top and why.

## Who looks at it, and what for

An owner of a small business, or the person who runs this for them. They open it a few times a day to answer three questions: did anything new come in, who needs me to decide something, and is anything about to go wrong. So the Overview leads with speed to lead and the waiting decisions, not with totals.

## Palette (60, 30, 10)

- 60 percent warm neutrals: cream `#f6f1e7`, surface `#fbf8f1`, oat `#efe7d8`. A white page would feel clinical next to a coffee brown ink, and pure white or black is never used.
- 30 percent coffee: ink `#2b1d14`, secondary ink `#5a4535`, tertiary `#76604f`. Every text colour passes 4.5 to 1 contrast on its background in both themes (a test in the kit checks this).
- 10 percent accent: **clay** `#a24b2f` (dark theme `#e08a68`). Clay is a warm, grounded red brown. It says "sales" without looking like an alarm. It marks the one primary action on a screen, the active nav item and the focus on charts. True red is kept for real alarms only (a paused mailbox, a failed send).
- Status: sage green for good, amber for caution, red for danger. They always come with a word or an icon, never colour alone.
- Dark theme "espresso" keeps the same order of importance: darker surfaces are further back, lighter ink is closer.

## Type

Geist for the interface and every number, Instrument Serif for page titles and the two big numbers on the Overview. Tabular figures on anything that changes (counts, money, minutes) so digits do not jitter. Body text is capped near 65 characters. Sizes follow the kit steps 13, 16, 21, 27, 34, 55, 89. Apple system fonts are not used on the web.

## Space, radius, depth

Space 8, 13, 21, 34, 55, 89 (the golden family). Radius 8, 13, 21. Depth is a 1 px hairline plus a soft layered shadow. Glass (blur and a translucent warm fill) appears only on floating layers: the command palette, sheets, dialogs. Never on content.

## Motion

Our own tokens, defined in the kit: out curve `cubic-bezier(0.23, 1, 0.32, 1)` for entrances, in out `cubic-bezier(0.77, 0, 0.175, 1)` for on screen moves. Press 140 ms, hover 180 ms, popover 220 ms, sheet 300 ms, page 300 ms, chart draw in 700 ms once. Exits are quicker than entrances. Only transform and opacity animate. Press scale 0.97. Hover lift only on devices that can hover. List entrances stagger 30 to 60 ms and never block input. Keyboard driven and very frequent actions (j and k in a table, drag keys) have no animation. With reduced motion the fades stay and the movement goes. With reduced transparency, glass becomes solid.

## Interactions this app uses

| Interaction | Where |
| --- | --- |
| Button hover, press, focus ring, then spinner and success tick | every action button (kit Button) |
| Count up on change, tabular figures, delta arrows | Overview stats, pipeline column values, Deliverability |
| Skeleton shaped like the final layout | every list and card while loading |
| Optimistic move with rollback and an undo toast | Pipeline drag and drop |
| Row hover reveals actions, middle truncation of emails | Leads table |
| j, k, enter, x, escape in a table, multi select with a floating bar | Leads table (kit DataTable) |
| Command palette on every screen with shortcut hints | Cmd or Ctrl plus K; G then 1 to 9 goes to a page |
| Live validation with the fix in plain words | Sequence builder, Proposal studio, Sign in |
| Draft saved while typing | Proposal studio call notes, Inbox draft reply (browser storage) |
| Copy button that turns into a tick | Integrations, Proposal studio |
| Charts draw in once, crosshair tooltip, legend toggles | Overview |
| Confirm and undo for destructive moves | Mark lost, kill switch, reset demo |
| Empty state with the next action, error state with the fix | every list |
| Offline banner | whole app (kit) |
| Theme change cross fade | top bar toggle |
| Everything reachable by keyboard | whole app |

## The signature moves

1. **Speed to lead ring.** The first thing on the Overview. A ring shows the share of inbound leads first answered within 5 minutes. The centre number counts up. A line under it says how many are waiting and why (quiet hours in their time zone, mailbox caps). New events arrive over a live stream and the ring animates to the new value.
2. **Drag and drop pipeline.** Cards lift into an overlay, the old spot becomes the gap, and a drop settles in 220 ms. The move is applied at once, sent to the server, and rolled back with an error toast if the server refuses. Every move has an undo toast.

## Pages

| Page | Layout and decisions |
| --- | --- |
| Sign in | One centred card on the cream page. Demo credentials are shown only in demo mode. |
| Overview | Row 1: speed to lead card (ring, median minutes, waiting) beside four stat cards (sent, replies, positive replies, open pipeline). Row 2: funnel as horizontal bars, sends per day as an area chart. Row 3: what needs a person (pending approvals, open replies, a deliverability warning if a mailbox is paused). |
| Pipeline | Seven columns, new to lost. Card: name, company, value, score. Horizontal scroll on phones. Moving to Lost asks for a reason. |
| Inbox | Split view 38.2 to 61.8. Left: replies with intent badge and one line. Right: their message, how it was read (rule or model, confidence), suggested action chips, an editable draft, Approve and send, Reject, Book a call with real open times. A draft with a fill in part cannot be approved. |
| Sequences | A vertical timeline of step cards (channel, delay, subject, body). Next to it a live preview rendered for a real lead. Unknown fields are flagged as you type. |
| Leads | Table with search and status filter, score column, flag badges, a side sheet with the score breakdown and the model's explanation, activities and messages. CSV import dialog with a result summary of duplicates and flagged rows. |
| Proposals | Left: form (lead, title, scope lines, price, call notes). Right: live preview of the document. Buttons: Save, PDF, Create contract, Prepare for signature (shows open items and the steps, sends nothing). |
| Deliverability | One card per mailbox: health gauge, cap bar, bounce rate, SPF, DKIM, DMARC chips, resume button for the owner. |
| Approvals | Queue grouped by risk, approve or reject with a note. |
| Integrations | Wizard per category (email, texting, calendar, CRM, signing): which adapter is selected, its tier, which variables it needs, a Test button. Tier B and C are labelled. Nothing says verified live. |
| Audit | Newest first, with a Verify button that checks the hash chain. |

## States

Every list has loading (skeleton), empty (says what to do next), error (says what happened and how to fix it), and offline. A draft mode banner is always visible when the effective mode is draft. A kill switch banner replaces it when the switch is on.

## Mobile

390 px wide. The sidebar becomes a drawer. Tables scroll inside their card. The Pipeline scrolls sideways with snap. The split view stacks. Touch targets are at least 40 px.

## What the kit does not have, built in this app

A multiline text area, a horizontal funnel bar, and the timeline connector in the sequence builder. They use the kit tokens and live in `apps/web/src/components`. The kit has no column resize, saved views or context menus; Pipecairn does not offer them either (see docs/14-LIMITS-AND-HONEST-NOTES.md).
