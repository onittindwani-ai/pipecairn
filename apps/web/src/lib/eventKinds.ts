/** Every kind of event the API records. The live stream names each frame after its kind (`event: reply.classified`), and a browser delivers a named frame only to a
 *  listener for that name, so the page listens to each of these. A test on the API side fails when a kind is recorded that is not listed here. */
export const EVENT_KINDS = [
  "cycle.ran", "enrollment.stopped", "leads.imported", "meeting.booked", "message.drafted", "message.failed", "message.unconfirmed",
  "reply.classified", "reply.unmatched", "suppression.added", "suppression.lifted",
] as const;
