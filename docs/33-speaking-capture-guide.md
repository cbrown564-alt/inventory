# 33 — The speaking capture guide (research prototype)

*Written 3 Aug 2026. **Status: exploratory. Low priority. Not on the v1
path.** This document records an idea worth understanding, the reasons it is
not currently buildable, and the smallest experiment that would tell us
whether that changes. It owns no product surface and blocks nothing.*

## The idea

A calm spoken guide that listens to a walkthrough in progress and speaks only
when the evidence being captured is incomplete: *pause here*, *move closer*,
*open that slowly*, *name this room*. Not narration, not a tutorial, not a
voice assistant. A quiet second pair of eyes that says four things in eight
minutes and is otherwise silent.

The appeal is that capture quality is the single largest determinant of report
quality, and it is decided entirely in the eight minutes the owner spends
walking around with a phone — a window in which we currently give them no
feedback at all. Everything the product knows about a bad capture, it learns
after the capture is over, when the only remedy is asking someone to do it
again.

## Why it is not buildable today

Three structural obstacles, in order of severity. The first is decisive.

**1. There is no live capture loop to speak into.** The plan of record
(docs/12) is video-first: one video, recorded on a phone's own camera app,
uploaded to the web app afterwards. Processing happens on a machine the phone
is not talking to, minutes or hours after the walk. A guide that speaks during
capture requires a live capture surface — which is exactly the thing docs/12
killed and docs/28's camera-first mobile workspace explored and shelved. This
concept quietly assumes a product that was deliberately retired. Any serious
version of it is a proposal to revive live capture, and should be argued on
those terms rather than smuggled in as an audio feature.

**2. Real-time quality assessment is unproven on-device.** The guide's value
is entirely in knowing *when* to speak. That means judging blur, coverage and
occlusion on a live frame stream on a phone. The IQA work (docs/18, docs/22)
scores frames after the fact on a workstation, and pyiqa — the strongest
scorer benchmarked — is non-commercially licensed and can never be a product
dependency. A guide that speaks at the wrong moments is worse than silence,
because it trains the owner to ignore it.

**3. The intervention budget is brutally small and we cannot yet estimate
it.** The concept's own stated failure mode is that the guide interrupts too
often. Somewhere between "silent" and "annoying" there is a number of
interventions per walkthrough that helps, and we have no evidence about where
it sits. Plausibly it is three. Plausibly it is zero and a single end-of-room
summary beats any interruption.

## What the repo already has

Not nothing, which is why this is worth writing down rather than dismissing.

`homeinventory/audio_cues.py` implements a frozen transcript-and-cue contract
where narration is kept as research evidence and production consumers receive
only small typed cue lists — the describer never sees narration prose.
`homeinventory/segment.py` uses room cues as segmentation hints and
`homeinventory/curate.py` uses establishing cues to promote hero images. Both
are opt-in behind `--audio-segment-cues` and `--audio-hero-cues`.

So the repo already treats spoken input as a *typed, bounded, confidence-
bearing signal* rather than as instructions. That is the hard architectural
half of a speaking guide, and it exists. What is missing is the live loop and
the judgement about when to speak — obstacles 1 and 3.

It is also worth noting what this implies for the reverse direction: those
same paths currently trust spoken room labels without checking them against
the frames. That is a live robustness question, and it is the one part of this
whole concept area that is cheap and testable today. It is stage B of
docs/32 rather than anything in this document.

## The smallest experiment that would settle it

If this is ever picked up, do not build a guide. Build the transcript of one.

**Wizard-of-Oz on recorded walkthroughs.** Take three walkthrough videos we
already have. For each, a human watches in real time and writes down the exact
moment they would have intervened and what they would have said. Then check
each intervention against the report the video actually produced: would that
intervention have fixed a real gap in the finished evidence?

This costs an afternoon, spends no credits, needs no live capture surface, and
answers the two questions that matter:

- **How many interventions per walkthrough are actually warranted?** If the
  honest answer is one or two, the concept is a nudge in the upload flow, not
  a speaking guide, and the whole direction resolves cheaply.
- **Are the warranted interventions detectable from a live frame stream?**
  "You skipped the utility room" needs a floor plan and is out of reach.
  "That was too blurry to use" needs a blur score and is not.

Only if that record shows a meaningful number of interventions that are both
warranted and live-detectable does the live-capture question become worth
reopening — and at that point it is a docs/12 and docs/28 conversation about
the capture surface, not a voice project.

## If it were built anyway

Recorded so the constraints do not have to be rederived later:

- **Silence is the default state.** Speaking is the exception that must earn
  itself. The measure of the guide is the number of things it did *not* say.
- **The guide never diagnoses.** "Move closer to that" is capture guidance.
  "That looks like damp" is a finding, and findings are the describer's job
  under human review — not something spoken aloud into a room where the owner
  will believe it.
- **Everything the guide says is logged as an artefact**, with timestamp and
  trigger, so a walkthrough's guidance is reproducible and auditable in the
  same way its frames are.
- **The guide is never a gate.** An owner who ignores every prompt still gets
  a report. Guidance that blocks completion is a different product.
- **A phone recording a room is a bad microphone environment.** Anything the
  guide says will be recorded by the phone's own microphone into the
  walkthrough audio track. Either the guide's own speech is subtracted from
  that track, or the acoustic axis in docs/32 is measuring the guide talking
  to itself.

## Boundaries

- This is a research prototype. It does not appear in v1 scope, the plan of
  record, or any roadmap commitment.
- It does not justify reviving live capture on its own. That decision belongs
  to docs/12 and docs/28.
- No credits are spent on voice generation before the Wizard-of-Oz record
  exists.

## Related owners

- `docs/12-video-first-journey.md` — product plan of record; the reason there
  is no live capture loop.
- `docs/28-camera-first-mobile-rebuild.md` — the shelved camera-first mobile
  workspace and its experiment guardrails.
- `docs/26-capture-strategy-experiment.md` — capture strategy evidence,
  including the unused-audio note on narrated continuous video.
- `docs/32-acoustic-evidence-synthetic-lab.md` — the evaluation side of the
  same concept, which is fundable now.
- `homeinventory/audio_cues.py` — the existing spoken-signal contract.
