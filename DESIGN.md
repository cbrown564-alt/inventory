---
name: Home Inventory
description: A calm, evidence-first property inventory product for landlords and tenants.
colors:
  primary: "#9a7729"
  primary-deep: "#7d5e1b"
  primary-soft: "#f0e7d2"
  paper: "#f6f3ec"
  panel: "#fffdf8"
  panel-muted: "#f1ede3"
  ink: "#22262d"
  muted: "#626b76"
  line: "#e4dfd3"
  success: "#1d6f4c"
  warning: "#718093"
  danger: "#a3312a"
  media: "#0e1116"
typography:
  display:
    fontFamily: "Fraunces, New York, Iowan Old Style, Palatino, Charter, Georgia, serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.25
  body:
    fontFamily: "Avenir Next, Avenir, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Avenir Next, Avenir, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    lineHeight: 1.4
  mono:
    fontFamily: "ui-monospace, SF Mono, Cascadia Code, Consolas, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  sm: "7px"
  md: "10px"
  lg: "14px"
  pill: "999px"
spacing:
  1: "4px"
  2: "8px"
  3: "12px"
  4: "16px"
  5: "20px"
  6: "24px"
  7: "32px"
  8: "48px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.panel}"
    rounded: "{rounded.sm}"
    padding: "7px 14px"
  button-primary-hover:
    backgroundColor: "{colors.primary-deep}"
    textColor: "{colors.panel}"
    rounded: "{rounded.sm}"
  card:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.lg}"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
---

# Design System: Home Inventory

## Overview

**Creative North Star: "The evidence folio"**

Home Inventory should feel like opening a beautifully prepared property file,
not operating a generic AI tool. Warm paper surfaces carry orientation,
progress, reports, comments, and decisions. The single dark surface is earned
by close inspection of an image or video, where it gives the evidence visual
priority. The user moves between these states without a jarring product-wide
theme change.

It is premium because it is calm, precise, and legible. Generous imagery,
quiet rules, deliberate type, and exhibit-level provenance replace decoration.
The system rejects generic AI SaaS, cold professional inspection software,
and legalese theatre.

**Key Characteristics:**

- Warm documentary surfaces, not sterile white dashboards.
- Serif moments for property identity and completion, humanist sans for work.
- One brass accent used to guide action, selection, and provenance.
- Dark media only when inspecting evidence closely.
- Mobile layouts prioritise thumb reach, readable evidence, and one action at a time.

## Colors

The palette is a restrained paper-and-brass system with semantic colour used
only to clarify state.

### Primary

- **Archive Brass:** the primary action, selected state, timeline playhead,
  and provenance emphasis. It must remain scarce so it retains authority.

### Neutral

- **Ledger Paper:** the application canvas and long-form document field.
- **Clean Panel:** raised content that needs separation without visual noise.
- **Quiet Panel:** secondary grouping, inactive controls, and gentle staging.
- **Document Ink:** all primary reading and data.
- **Margin Grey:** secondary explanation, timestamps, and helper text.
- **Hairline Rule:** quiet delineation between documentary elements.
- **Inspection Dark:** the sole dark island behind media inspection.

### Named Rules

**The Evidence-Only Dark Rule.** Dark backgrounds are forbidden for navigation,
overview, forms, project home, tenant review, and reports. They are reserved
for the player, lightbox, and annotated evidence.

**The Brass Rarity Rule.** Brass is not decorative. Use it for the current
action, selected item, a timecode, or a provenance seal, never as a large
background field or inactive decoration.

## Typography

**Display Font:** Fraunces, with editorial serif fallbacks.

**Body Font:** Avenir Next and Segoe UI Variable Text, with native system
fallbacks.

**Label/Mono Font:** native monospace for hashes, identifiers, timestamps,
and technical provenance only.

**Character:** The serif gives the property and final issue dignity. The sans
keeps working controls familiar and fast. Monospace behaves like an exhibit
label, never like decorative developer texture.

### Hierarchy

- **Display:** Used for property names, room names, completion headings, and
  the report title. Never use it for controls, tables, or dense queue rows.
- **Headline:** Used for a single screen question or a major flow phase.
- **Title:** Used for cards, room plates, and grouped tasks.
- **Body:** Used for all explanatory copy. Keep prose to roughly 65 to 75
  characters per line when space permits.
- **Label:** Used for controls, status, and compact metadata. Uppercase labels
  are reserved for short documentary annotations, not ordinary buttons.

### Named Rules

**The Readable Field Rule.** No active review surface may use text below the
documented body and label sizes to squeeze more UI onto the screen. Mobile
does not inherit desktop density.

## Elevation

Elevation is documentary rather than theatrical. At rest, panels use a fine
rule and a quiet low shadow. Hover and focus can lift an actionable plate so
the response is felt immediately. Overlays use a single darker veil only when
they genuinely interrupt the task.

### Shadow Vocabulary

- **Low lift:** used for cards and fields at rest to separate paper layers.
- **Action lift:** used for interactive cards on hover and keyboard focus.
- **Overlay lift:** used for the focused media inspector and essential dialogs.

### Named Rules

**The Flat-Until-Useful Rule.** Do not stack cards within cards. A raised
surface must either be actionable or separate a meaningful document layer.

## Components

### Buttons

- **Shape:** gently curved corners, with a 44px minimum touch target on
  mobile even when the visual height is compact.
- **Primary:** one per screen or task region. It advances the current phase,
  never competes with export, sign, and share simultaneously.
- **Secondary and ghost:** quietly reveal repair tools and optional actions.
  They must retain visible focus and clear pressed states.

### Cards / Containers

- **Room plates:** image-led, generous, and named in serif. They introduce
  the property before a user meets the item queue.
- **Task plates:** use a title, a small evidence-backed status, and one next
  action. Avoid repeated icon-heading-description card grids.
- **Finish plate:** acts as a calm closing checklist, not a modal pile-up.

### Inputs / Fields

- **Style:** plain paper fields with a clear border, labels above, and useful
  inline validation.
- **Focus:** a visible primary-colour outline. Error explains the exact repair
  in words and is never communicated by colour alone.

### Navigation

- **Style:** a compact, persistent flow map that uses the same vocabulary on
  every surface: New, Review, Report, Final issue, Finish.
- **Mobile:** navigation is a horizontally scrollable strip or a compact
  menu, never a wrapped row that competes with the screen's primary action.

### Evidence Spine

The room-chaptered video timeline is the signature component. It appears
whenever a claim is checked, connects an item to a cited moment, and must be
tap-friendly with visible timecodes and a clear return path to the queue.

## Do's and Don'ts

### Do:

- **Do** lead each screen with the one question the user needs to answer now.
- **Do** make room, review, and completion progress visible as plain-language
  counts with an obvious next action.
- **Do** place claim, evidence, timestamp, and source-video control within one
  interaction on mobile.
- **Do** use the display serif only for property identity, documentary
  headings, room titles, and completion moments.
- **Do** make the tenant flow read as a fair walkthrough with comments before
  countersigning.

### Don't:

- **Don't** use gradients, magic-wand language, chat-like controls, or generic
  AI SaaS dashboards.
- **Don't** use a dark application shell, tiny dense type, acronym-heavy
  controls, or a desktop-only workflow.
- **Don't** use legal seals, warnings, hashes, or timestamps as decoration.
- **Don't** use coloured side stripes, gradient text, glassmorphism, or nested
  cards.
- **Don't** introduce a modal when an inline phase, dedicated route, or
  progressive disclosure keeps the user oriented.
