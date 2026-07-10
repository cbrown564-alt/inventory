# 28 — Camera-first mobile rebuild

**Status:** active product direction and prototype scope. This supersedes the
desktop-first interpretation of the owner-pairing work in docs/27; it does
not decide the video-versus-photo experiment in docs/26.

## The product promise

The customer should be able to use the camera they already trust:

> Record a normal walkthrough in the phone Camera app. Hand the video to
> Home Inventory. We turn it into an evidence record and bring back only the
> decisions that need the customer.

The web app earns its existence **after** the recording. It is not a
procedure that asks a self-managing landlord to learn how to be an inventory
clerk. Its value is to retain the original, organise it into rooms, draft the
schedule, find uncertainty, connect every claim back to evidence, manage
agreement, and produce a versioned issued record.

This is a camera-first proposition, not a photos-first decision. Room photos
remain a quiet supplement for a meter, small defect, or anything the customer
wants to make unmissable. The app must never make them complete a second
capture process merely because the system would prefer it.

## What the customer sees

```text
Phone Camera → choose the finished walkthrough → “We’re preparing your draft”
                                            │
                                            ├─ originals retained and hashed
                                            ├─ rooms / evidence / draft built in background
                                            └─ only uncertain or consequential claims return

Phone review → confirm / correct / add one detail → sign → tenant review → issue
                                            │
                                            └─ optional continuation on a larger screen
```

The only default capture CTA is **Choose video from Camera**. “Landscape,
say the room name, hold a wide view” belongs behind an optional hint. It is a
quality multiplier to test, not a toll gate. Photo capture is framed as
“Have one thing the video cannot show clearly?”

## Why this is materially better than a file uploader

| Ordinary camera video | What Home Inventory adds |
| --- | --- |
| A long, hard-to-navigate clip | Room structure, representative evidence and time-linked exhibits |
| No readable record of condition | A draft schedule with condition, cleanliness and specific claims |
| Nothing distinguishes confidence from guesswork | An exceptions-first review where a person can reject, repair or mark unseen claims |
| A video alone is difficult to compare later | Stable inventory data, original hashes, issued versions, and check-in/check-out comparison |
| One person’s footage | Tenant comments, countersignature and a tamper-evident acknowledgement trail |

The user is not buying “AI analysis”. They are buying the confidence that a
video they were already willing to record becomes a defensible record without
a £165 clerk visit or a 200-row DIY document.

## The video hypothesis remains empirical

The default must be earned. Docs/26 now separates an ordinary continuous
video (V0) from the actual product hypothesis: a narrated, landscape,
establishing-shot continuous video (V1). It measures all of the following:

- room-name and boundary correctness;
- whether the top evidence image is a recognisable establishing view of its
  named room;
- final report accuracy; and
- the total burden: capture minutes **plus** review-to-issue minutes,
  unchanged accepts, material edits, rejections, additions, unseen marks and
  recaptures.

V1 wins only when its capture-time advantage survives the review phase. If it
does not, the product changes based on evidence: room clips, a light hybrid,
or photos may become the appropriate default. We must not let simplicity of
the UI become a claim that a weak source video makes a strong report.

## Web first; native assistance only when it earns silence

The mobile web product should ship the camera handoff, resumable upload,
cloud build, exception review, signing and multi-device project continuation.
It should **not** present a live AI conversation during filming. A phone web
page cannot rely on Apple-native Vision, Core AI, Foundation Models or iOS
background-task APIs; those are Swift app capabilities. That is an inference
from Apple exposing them through its platform frameworks, rather than a
browser API.

A native iOS companion becomes worthwhile when it can eliminate a real risk
without asking the user to do more work:

| Capability | Good quiet use | Not acceptable as a default |
| --- | --- | --- |
| Vision / Core ML live detection | Notice a likely missed high-value category at a room boundary; prepare a local coverage hint | Narrate every object or claim completeness from uncertain detection |
| Speech recognition | Treat spoken “this is the kitchen” as a room-boundary hint and preserve it as evidence metadata | Require narration or mislabel a room when audio is poor |
| Foundation Models / Core AI | Classify a small candidate frame set, extract structured local cues, or turn a recorded spoken note into a draft label | Treat on-device output as clerk-grade condition/defect judgement without the same evaluation gate |
| Background processing and upload | Finish a user-initiated upload or lightweight local analysis after they leave the app | Promise a mobile web upload will continue indefinitely after Safari is closed |

Apple now documents real-time Vision object recognition, multimodal image
prompting in Foundation Models, and Core AI for fully on-device models. Those
are promising tools for a **native, optional capture-assist tier**, not proof
that a live assistant improves inventories. Foundation Models availability is
device-, region- and Apple-Intelligence-dependent, so it must always have a
quiet fallback. [Vision live capture](https://developer.apple.com/documentation/vision/recognizing-objects-in-live-capture), [Foundation Models image analysis](https://developer.apple.com/documentation/FoundationModels/analyzing-images-with-multimodal-prompting), and [Core AI](https://developer.apple.com/core-ai/) describe the available native building blocks.

### Intervention rule

The assistant may interrupt only when all three are true:

1. the potential miss is consequential (for example, a meter, smoke alarm,
   or an entire room has not plausibly appeared);
2. the local signal is sufficiently reliable; and
3. the prompt appears at a natural pause and offers a one-tap choice such as
   “Add a close photo” or “This is not applicable”.

No running commentary, no fake certainty, no mandatory shot list. The ideal
experience feels like nothing happened—until a true omission would have cost
the user later.

## Rebuild boundaries

The current prototype now uses a room-led field workspace as the default:

- camera-first video handoff with optional photo supplementation;
- exceptions-first phone review and thumb-reachable decisions;
- the existing `Inventory` schema, evidence links, hash manifest,
  acknowledgement trail, signing, tenant review and report renderer unchanged;
- `/review` retained temporarily as the specialist evidence desk for
  annotations, room corrections and dense desktop review.

This is deliberately a **product-surface rebuild**, not a false claim that
the local review server is a finished cloud product. Before promising a phone
to computer handoff, the next architecture increment needs authenticated
projects, HTTPS, direct resumable object storage, background build workers,
scoped tenant invitations, version locks and an exportable evidence archive.
The LAN owner capability link in docs/27 remains a local prototype fallback;
it is not the mobile-first sharing model.

### Current prototype increment

The default video control opens the device's existing video library rather
than forcing a second browser-camera recording. For large files, the local
server now retains a byte offset while the upload is incomplete and a small
completion receipt once it is safely stored. The browser checks that state and
retries from the recorded offset after a transient failure; if the page is
reloaded, choosing the same file continues that upload instead of creating a
duplicate. This is resumable transfer, not background web processing: Safari
may still suspend the page, and the user may need to choose the video again
after leaving it.

The phone review queue is now genuinely exceptions-first. It brings forward
only an unreviewed item with low or unknown draft confidence, missing linked
evidence or condition data, a drafted defect, or a safety/meter category.
Routine well-evidenced claims remain available in the specialist evidence desk
instead of turning phone review into a clerking exercise. This is a deliberate
queueing rule, not an accuracy claim or an automatic acceptance: the original
evidence and the full draft remain inspectable before issue.

## Near-term proof sequence

1. Test V0/V1/P1/P2 from docs/26 on at least two properties and include the
   review-burden measurement.
2. Test the camera-first handoff with ordinary landlords: can they finish a
   recording, hand it off, return later and issue without being coached?
3. Build the hosted project spine before further LAN pairing polish.
4. Spike native quiet assistance with one narrow target—room-boundary speech
   plus a high-value coverage check—and compare it against no assistance for
   false prompts, capture time, battery, and final report quality.
5. Promote only interventions that lower total burden and pass the same
   signed-report evidence bar as the cloud path.
