# Pilot test script: quoting by hand vs with the app

**Goal.** Measure, with a real person who quotes deals at Empower, how long one quote takes by hand and with the app, and how
good each result is. This is the "real user" evidence for section 7 of the report.

**What it tests, honestly.** The workflow and the quality of the draft. It runs on the **demo data** (synthetic people,
projects and rates that look like Empower's), so it does not test accuracy on Empower's real projects; the backtest covers that.

| | |
|---|---|
| **Tester** | A parent or colleague who has quoted software projects at Empower (ideally the person who does it today) |
| **You** | The facilitator: you run the session, time it, and take notes. Don't help with the quote. |
| **Time** | About 70 minutes: 40 min by hand, 15 min with the app, 10 min scoring, 5 min wrap-up |
| **Request** | BrightSmile Dental Group: patient booking app, 14 clinics, Dentrix, HIPAA, "around $60-80k", "before April" |
| **Files** | `pilot/Empower_manual_quoting_kit.xlsx` (one copy per tester) and the app running on your laptop |

---

## Before the session (10 minutes)

1. Start the app (`python run.py`) and check that you can sign in as **Director**.
2. Open a fresh copy of `Empower_manual_quoting_kit.xlsx` in Excel. All yellow cells should be empty or at their defaults.
3. Keep the app's **Deals** page closed until Part 2. It already contains example BrightSmile deals, and seeing them first
   would anchor the manual quote.
4. Have a clock visible (phone stopwatch is fine).

## What to say at the start (read it out)

> "This is for my AI course project. I built an app that drafts quotes for Empower from a client's email. I want to see how it
> compares with how you do it today. You'll quote one request by hand, with a spreadsheet of demo data that looks like ours,
> then run the same request through the app, then score both. The people and numbers are made up, so judge the method as if
> they were real. Please be critical: what's wrong with the app is the most useful thing you can tell me. Is it OK if I
> quote what you say in my report? You can say no, or role only."

Note their answer about quoting.

## Part 1: by hand (up to 40 minutes)

- Ask them to write the **start time** in *Scorecard* C6, then open *Start here* and *Client request*.
- They fill the yellow cells in *Quote worksheet*: build hours per role, risk level, regulated data, discount, start and
  go-live dates, team, risks, client questions. The sheet adds PM, tech lead, QA and contingency and does the price and margin.
  The reference sheets (rate card, people and weekly availability, module history, past projects) stand in for Empower's files.
- **Stop** when they have a quote they'd discuss internally, or at **40 minutes**. They write the **end time** (C7). If they
  hit the limit, ask: "how long would a proper quote really take you?" and write it in C8.
- **Your notes:** where they spent time, what they looked up, what they skipped, anything they said out loud.

## Part 2: the same request in the app (about 15 minutes)

- In the app: sign in as **Director** → **New deal** → click the sample file **brightsmile_rfp.pdf** (same request) →
  **Run Deal Desk**. They write the **start time** in *Scorecard* C10 when they press Run.
- While it runs (2-3 minutes; 2 min 21 s in the dry run on 25 Oct) they can watch the stepper. When it finishes, they read **Overview, Estimate, Team &
  timeline, Pricing, Review, Proposal**, and write the time when they've formed a view (C11).
- They record a **decision** at the bottom of the Overview tab (**Approve to send** / **Request changes** / **Reject**), filling **"Hours this quote takes by hand"** and
  **"Draft quality (1–5)"**. The app's *Usage & safety* page then shows them under *Reviewer feedback*.
- **Your notes:** what they looked at first, what they questioned, anything they disagreed with.

## Part 3: score both (about 10 minutes)

- They fill *Scorecard*: each line rated 1-5 for their quote and the app's, with a reason, then the questions at the bottom
  (editing time, would they use it, what they wouldn't trust, one sentence you may quote, how to credit them).

## Wrap-up questions (5 minutes, you ask, you write)

1. "Where did the app save you the most time? Where did it cost you time?"
2. "Which number in the app would you change before sending, and to what?"
3. "Would you have caught the Dentrix and budget problems by hand? How long would that take normally?"
4. "If this ran on our real data, what would you use it for first?"

## After the session: what to collect

- [ ] The filled workbook (save it as `pilot/results/pilot_<date>.xlsx`; this folder is for your copy, don't commit a real
      person's name without their OK)
- [ ] A screenshot of the app's finished run and of *Usage & safety* → *Reviewer feedback*
- [ ] Optionally a photo of them using the app (only with permission)
- [ ] Your notes and their quote

Send these to Claude in the session and it fills the report's *Pilot with Empower* block, the `[[CONFIRM ...]]` line, and
slide 9.

## How it will be reported (keep it honest)

- One tester (n = 1), demo data, Director's role, the stated timing for each part.
- Manual time is capped at 40 minutes, so if they hit the cap, report their own estimate of the full time next to it.
- Report both ratings tables, including where the app scored lower, and what they would not trust.
- The manual quote's numbers can be compared with the app's (hours, price, margin), but neither is "right" on demo data;
  the useful comparison is time, completeness (risks, questions, staffing), and the tester's judgment.

## Dry run (25 Oct, by Claude, not a pilot)

Every step above was run once against the real app to check the procedure; no feedback was recorded. Found and fixed: the
gateway replayed a cached earlier run (16 s instead of a real run); the leak guard redacted the client's own "$60-80k"
budget and blocked *Approve to send*; the kit's request text was shorter than the PDF; an empty worksheet showed a false
margin warning. The kit's sums match the app's calculator exactly (5,210 h, USD 157,400 T&M, USD 176,200 fixed).

## If no one at Empower is available

Run the same script with a classmate playing the sales lead (weaker evidence: they don't quote for a living), or do it
yourself and say so. Either way, report who the tester was.
