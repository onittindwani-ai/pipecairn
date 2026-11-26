# How well does the reply reader read replies? (honest numbers)

All replies in every test set are sample text. Numbers below come from `python3 tools/eval_replies.py` and are saved in `data/eval/`.

## The short version

- The reply reader that ships in demo mode is **a set of rules, not a language model**. It exists so the product runs with no account and no key.
- On the first 70 test replies it got 69 right (98.6 percent). That number is **not a fair measure**: the same person wrote the rules and the 70 replies.
- On a new set of 134 replies written separately, in different wording, the same rules got **44 right (32.8 percent)** on the first run. That reader has since been improved. For the improved reader the number to believe is set B below: **114 of 170 (67.1 percent)**.
- On the held out set the rules missed 14 of 21 requests to stop. In Pipecairn a missed stop request is not sent on to the next email (see "What a miss does" below), but the person is not put on the suppression list.
- How well a **live language model** reads replies has not been measured. UNVERIFIED. It must be measured on the held out set before a client depends on it.

## Independent held out sets A and B (the numbers to quote)

Two further sets were written by separate AI test authors who **never saw the code, the rules or the earlier sets** (174 replies in set A, 170 in set B; 7 intents; 13 to 14 percent marked ambiguous by their author). Their README and keys are saved unchanged in `data/eval/independent/set_a/` and `set_b/`. The scoring tool is `tools/eval_independent.py`. The protocol was followed in this order: tool written from the sets' README only; set A run once on the reader as it was and saved untouched; the reader improved using only general language knowledge (nothing copied from set A or set B, and neither set was read in detail); set B run once and saved untouched; set A run again.

| Run | Replies | Strict (the key's main label) | Lenient (any label the key accepts) | Status |
|---|---|---|---|---|
| Old self written held out set, first run | 134 | 44 (32.8 percent) | not scored | Written by the same project. See "The four numbers". |
| **Set A, first run** (`set_a_first_run.json`) | 174 | **103 (59.2 percent)** | 110 (63.2 percent) | Held out. Reader as it was before the improvements. |
| Set A, after the improvements (`set_a_after_tuning.json`) | 174 | 142 (81.6 percent) | 146 (83.9 percent) | **No longer held out.** Set A was run before the changes, and the second run shows the changes helped on it, not how the reader does on new text. |
| **Set B, first run** (`set_b_first_run.json`) | 170 | **114 (67.1 percent)** | 121 (71.2 percent) | **Held out and the number to believe** for the improved reader. |

How to read this:
- The reader is rules, **not a language model**. On text it has not seen it gets about two replies in three exactly as the key says (67 percent on set B), and about 71 percent if the key's own "acceptable" alternatives are counted. A live language model is not measured here (UNVERIFIED, see `docs/14-LIMITS-AND-HONEST-NOTES.md`).
- Set A rose from 59.2 to 81.6 percent after the improvements, but that second run is not held out. The fair test of the improved reader is set B (67.1 percent). Set A first run and set B first run are different readers on different text, so they are not a like for like comparison, and 5 points is within noise at this size.
- Clear requests to stop that were missed: 14 of 34 on set A first run, 8 of 34 on set A after the changes, **7 of 34 on set B first run**. A missed stop is not sent on to a next email (the lead is set to "replied" and any answer waits for a person) but the address is not put on the suppression list. A person must still read the inbox.
- Ordinary messages read as a stop request when the key says stop is not acceptable: 7 on A first run, 3 on A after, 5 on B first run. Those leads would be suppressed by mistake.
- Obeying an instruction hidden in a reply: 0 on both sets (no injection was read as "interested").
- Per class on set B (strict): interested precision 0.74 and recall 0.52; question 0.43 and 0.74; not now 0.76 and 0.59; wrong person 0.44 and 0.44; unsubscribe 0.86 and 0.71; out of office 0.88 and 0.88; bounce 1.00 and 0.90. The weak spots are wrong person, interested and a plain "no" written in unusual or corporate wording.
- By tag on set B (lenient): legal threats 0.40, signatures and disclaimers 0.50, non profit wording 0.50, referrals 0.57, quoted threads 0.61, formal wording 0.69. Bounces, delivery delay notices and injections were all read correctly.

What changed in the fifth look (1.0.1): the reader now also says how sure a rule is. A complete request ("unsubscribe", "remove me from your list", "stop emailing me", STOP, STOPALL, QUIT, CANCEL, END) suppresses the address; wording that only might be one ("block", "legal team", "remove the setup fee") stops the follow ups and goes to a person, with no suppression. That changes what the inbox does, not which of the seven labels the reader returns, so the tables above are the numbers of the earlier readers. Re-run once after the change with `tools/eval_independent.py` (the labels only): set B first run 114 (67.1 percent) strict and 121 lenient, as before, with 7 of 34 clear stops missed; set A after the improvements 143 strict and 147 lenient (one reply more than the saved file), 7 of 34 missed. Set A is not held out, so that one reply says nothing about new text.

What the improvements were (all general, none taken from either set):
- the reader drops the quoted original message, the signature, "Sent from my phone" lines and legal or newsletter footers before reading, so our own "reply STOP" line and a company footer are no longer read as the person's request (`reply_text.py`);
- curly quotes and contractions are normalised ("don't" to "do not");
- a plain refusal ("not interested", "no thanks") with no time word is read as a request to stop, and with a time word ("not interested right now, try next year") as not now; a negated cue ("not interested") is no longer read as interest;
- wider wording for stop requests (including legal and privacy wording and common phrases in German, French, Spanish, Portuguese, Italian, Dutch, Polish, Turkish, Swedish and Hindi written in Latin letters), delivery failures, away and ticket acknowledgement replies, someone else handles this, ask me later, yes and scheduling phrases (`reply_rules.py`, `offline_lexicon.py`);
- the subject line is read too, for delivery notices and automatic replies ("Undeliverable:", "Automatic reply:").

Honest limits of these two sets: each key is one AI test author's reading of a short spec (a flat "no" is "unsubscribe" with "not now" accepted; a referral is "wrong person"; an auto reply ticket is "out of office"), non English text was written by a model, the sets are small, and the improved rules were also tuned against the project's own older sets (`reply_testset`, `reply_heldout`, `reply_heldout2`), which therefore no longer count as held out at all (they read 70, 134 and 42 correct of the same totals). Set B is still held out for the reader as it is now, as long as nobody tunes on it.

## The four numbers

| Set | Cases | Correct | Accuracy | Missed stop requests | Status |
|---|---|---|---|---|---|
| `data/reply_testset.json` | 70 | 69 | 98.6 percent | 0 of 12 | Written by the same author as the rules. Optimistic. |
| `data/reply_heldout.json`, **first run** | 134 | 44 | **32.8 percent** | 14 of 21 | Held out. This is the reported score. |
| `data/reply_heldout2.json`, first run | 42 | 12 | 28.6 percent | 5 of 6 | Written after the rules were tuned, by someone who had read them. Only partly held out. |
| `data/reply_heldout.json`, after tuning | 134 | 134 | 100 percent | 0 of 21 | **No longer held out.** The rules were changed after reading the failures, so this only proves the fixes work on those exact replies. |

The tuned rules then scored 28.6 percent on the fresh second set. That is the sign of what happened: tuning on the failures taught the rules those 134 replies, not how people write.

## How the held out set was made

1. It was written first, as `tools/make_reply_heldout.py`, **before the rules were read for this purpose**. It has 134 replies, at least 14 per class, in styles on purpose unlike the first set: very short ("yep pls send times"), rambling with signatures and "Sent from my iPhone", typos, sarcasm, quoted text under the reply, forwarded notes, polite refusals that are not stop requests, questions that hide interest, out of office notices with a return date, bounce text in several forms, a few replies in French, German and Spanish, and 6 replies that try to give the system orders.
2. It was run **once** on the rules as they were. That result was saved untouched (`data/eval/heldout_first_run.json`) and is the reported score. A test checks the saved numbers are unchanged.
3. Only then were the rules read and the failures listed.

## The first run in detail (held out, before tuning)

| Class | Cases | Precision | Recall |
|---|---|---|---|
| interested | 21 | 62.5 percent | 23.8 percent |
| question | 21 | 18.6 percent | 90.5 percent |
| not now | 21 | 100 percent | 9.5 percent |
| wrong person | 19 | 60 percent | 15.8 percent |
| unsubscribe | 21 | 77.8 percent | 33.3 percent |
| out of office | 17 | 100 percent | 23.5 percent |
| bounce | 14 | 100 percent | 28.6 percent |

Confusion pairs (what it should have been, then what the rules said):
- not now read as question: 17; interested as question: 16; wrong person as question: 16; out of office as question: 13; unsubscribe as question: 11; bounce as question: 10.
- Smaller groups: unsubscribe read as interested (2, "Not interested. Don't email me again." has the word "interested"), question read as unsubscribe (2, the word "spam" and "opt outs" in a question), and one each of not now as interested, not now as wrong person, unsubscribe as wrong person.

**Why.** The rules know a short list of phrases. Anything else falls through to "question", which is the safe default that sends a reply to a person, so most misses land there. The detail that matters: words and phrases decide, not meaning.

## What the two failure kinds mean

- **Falls to question (most misses).** A person reads it, so nothing bad is sent. The inbox does more work.
- **Stop request missed (14 of 21 on the first run).** In `inbox.py` a reply that is not read as a stop, bounce, out of office or not now stops the sequence and sets the lead to "replied", and any answer waits in the approval queue. So no further automatic email goes out. What does not happen: the address is not added to the suppression list, so it could be written to again if it is imported again later. A person must mark it "Never contact".
- **An ordinary message read as a stop request.** A question about "opt outs" or "spam" was read as a stop request, which would suppress a real prospect. The tuning narrowed those two rules.

## What was changed after the first run (and what it proves)

After the first score was saved, the safety rules (`replies.py`) and the offline stand in (`offline_llm.py`) were widened: more bounce and out of office wording, more ways to say stop (including a few in other languages), narrower "spam" and "opt out" patterns, and more phrase lists for wrong person, not now and interested. Some new tests also check that ordinary messages are not grabbed by the rules (for example "I'll circle back next week" is not an out of office).

This took the same 134 replies to 100 percent, which proves nothing about new wording: the 42 fresh replies were then read at 28.6 percent. **Do not quote the 100 percent.**

## Recommendation

1. Treat the offline stand in as a demo, never as a measure of product quality.
2. Put a live model behind the reply reader for real use. Keep the rules for opt outs, bounces and out of office as a first, cheap check, and widen them with the phrases a live model finds.
3. Before a client relies on it, run `python3 tools/eval_replies.py --set heldout` and `--set heldout2` with the live model (the tool takes the default backend today; switching it to a live backend is a small change) and compare. UNVERIFIED until someone does.
4. Keep growing the held out sets from real, consented replies when they exist, and never tune on a set you still call held out.
5. Keep a person in the loop: every drafted answer already waits for approval.

## Limits of this evaluation

- The labels were chosen by one person. Two hard cases follow a stated policy (a polite decline with no request to stop is "not now"; a pure question is "question" even when it hints at interest). A different policy would change a few scores.
- 134 and 42 replies are small samples. Do not read decimals into the percentages.
- Names, companies and addresses are sample names. Languages other than English are few.
