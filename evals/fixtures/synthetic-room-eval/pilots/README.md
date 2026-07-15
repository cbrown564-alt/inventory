# Synthetic room generation pilots

Non-scored Phase 0 outputs for `docs/31-synthetic-evaluation-dataset-plan.md`.
They test generation paths only. Neither image has completed dataset review or
gold labelling.

## `pilot-antigravity-unknown.jpg`

- Access: authenticated Antigravity CLI 1.1.2 using Google OAuth; no API key.
- Agent model: `Gemini 3.5 Flash (Low)`.
- Image tool: Antigravity built-in `generate_image`.
- Image backend: **unknown**. Antigravity does not expose the requested image
  model selector, so this must not be labelled Nano Banana Lite, Flash or Pro.
- Size: 1376×768 JPEG.
- SHA-256: `5c65b636b77ccdfac4c03e1578020869d9fd9b719f27bb6d52e850d8bd5b2e1b`.
- Review note: visually plausible kitchen, hood, hob and ceiling alarm. Tiny
  radio controls/markings make it unsuitable for a strict no-readable-text
  acceptance rule without a closer check.

Prompt:

> Generate one 16:9 photorealistic wide-angle smartphone photograph of a
> realistic occupied-but-tidy UK kitchen. Clearly visible and physically
> plausible: one wall-mounted extractor hood above one induction hob, and one
> ceiling-mounted smoke alarm. Natural daylight mixed with warm indoor light,
> modest contemporary finishes, a little ordinary countertop clutter,
> accurate room geometry. No people, no logos, no brands, no watermarks, no
> writing or text.

## `pilot-chatgpt-image-2.png`

- Access: Codex built-in image-generation path (ChatGPT Image 2).
- Size: 1536×1024 PNG.
- SHA-256: `3122b24e37c9eb548b4e5e062c01281635b382f8714942d9b2e2ce0e10d2871a`.
- Review note: plausible doorway kitchen view; extractor hood, induction hob,
  oven, sink, ceiling alarm, units and worktop are visible. Dataset acceptance
  still requires the formal review in docs/31.

Prompt:

> Photorealistic natural smartphone photo, wide landscape view from a doorway
> into a modest occupied UK kitchen, ordinary daylight plus warm ceiling
> lights, slightly cluttered but clean. Clearly visible: extractor hood,
> induction hob, oven, sink, smoke alarm, kitchen units, worktop. No people, no
> readable text, no logos, no watermark, no impossible geometry.
