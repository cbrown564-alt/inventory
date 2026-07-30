### Packet summary

| Packet | Verdict | Continuity | Notes |
|---|---|---|---|
| **RP-017 Google** | **Reject packet** | N/A | Flat vector/diagram frames with on-image labels; not photographic. |
| **RP-017 OpenAI** | **Accept packet (1 escalate)** | Coherent | Same formal dining: damask upper walls, red patterned carpet, round clothed table, dark hutch, brass chandelier. |
| **RP-018 Google** | **Reject packet** | N/A | Flat illustrations. **Provenance incomplete (plan note) — visual Pass A still rejects all four.** |
| **RP-018 OpenAI** | **Escalate / partial reject** | **Broken** | A/C side-by-side appliances vs B stacked stack; D fails required condition anchors. |
| **RP-019 Google** | **Reject packet** | N/A | Flat labelled diagrams. |
| **RP-019 OpenAI** | **Escalate / D reject** | Mostly coherent | Stack + boiler + shelves reverse cleanly; D is not a true plinth/boxing close-up. |
| **RP-020 Google** | **Accept with packet escalate** | **Rod conflict** | Photographic stairs packet; A–C show no rods, D shows brass rods. |
| **RP-020 OpenAI** | **Accept A–C; reject D** | Rod absence consistent | Photographic; D omits required carpet rods. |

---

### Per-frame decisions (task_id | decision | reason)

**RP-017 Google**
- `RP-017.antigravity-builtin.A-wide` | **reject** | Flat illustration with label text; not photographic.
- `RP-017.antigravity-builtin.B-reverse` | **reject** | Flat illustration; not photographic.
- `RP-017.antigravity-builtin.C-inventory` | **reject** | Flat illustration; not photographic.
- `RP-017.antigravity-builtin.D-condition` | **reject** | Abstract flat graphic; room/anchors not photographically recognisable.

**RP-017 OpenAI**
- `RP-017.gpt-image-2.A-wide` | **accept** | Clear photographic dining room; dark table (clothed), four chairs, display cabinet, chandelier, carpet.
- `RP-017.gpt-image-2.B-reverse` | **accept** | Door, fireplace, radiator under window, curtains, wallpaper all present; geometry stable.
- `RP-017.gpt-image-2.C-inventory` | **escalate** | Glass cabinet, sockets, radiator, skirting present; wall plate may be switch rather than thermostat.
- `RP-017.gpt-image-2.D-condition` | **accept** | Tabletop, edge, tablecloth, chair back all clear; photographic.

**RP-018 Google** *(provenance incomplete — visual only)*
- `RP-018.antigravity-builtin.A-wide` | **reject** | Flat illustration; not photographic.
- `RP-018.antigravity-builtin.B-reverse` | **reject** | Flat illustration; not photographic.
- `RP-018.antigravity-builtin.C-inventory` | **reject** | Flat illustration; not photographic.
- `RP-018.antigravity-builtin.D-condition` | **reject** | Flat illustration; intended swollen cabinet edge not photographically evidenced.

**RP-018 OpenAI**
- `RP-018.gpt-image-2.A-wide` | **accept** | Photographic utility; WM/dryer pair, sink, wall cupboards, speckled vinyl; no readable brands.
- `RP-018.gpt-image-2.B-reverse` | **escalate** | Door/hooks/shelving/radiator present, but appliance layout is stacked vs A/C side-by-side — packet continuity fails.
- `RP-018.gpt-image-2.C-inventory` | **escalate** | WM/dryer + socket visible; isolator switches and air vent not clearly evidenced.
- `RP-018.gpt-image-2.D-condition` | **reject** | Utility sink on metal legs — no sink cabinet/plinth/pipe boxing; cannot support intended swollen door-edge defect.

**RP-019 Google**
- `RP-019.antigravity-builtin.A-wide` | **reject** | Labelled flat diagram; not photographic.
- `RP-019.antigravity-builtin.B-reverse` | **reject** | Abstract illustration; not photographic.
- `RP-019.antigravity-builtin.C-inventory` | **reject** | Flat diagram; not photographic.
- `RP-019.antigravity-builtin.D-condition` | **reject** | Flat diagram; low-level anchors not photographic.

**RP-019 OpenAI**
- `RP-019.gpt-image-2.A-wide` | **escalate** | Clear stacked washer/dryer, boiler, shelves, cleaning tools; floor reads wood-look laminate, not clearly vinyl.
- `RP-019.gpt-image-2.B-reverse` | **escalate** | Door + shelves + baskets present; cupboard hinges / skirting not clearly shown.
- `RP-019.gpt-image-2.C-inventory` | **escalate** | Boiler, consumer unit, pipework present; isolator switches and air vent not clearly shown.
- `RP-019.gpt-image-2.D-condition` | **reject** | Basket/floor visible, but **plinth and pipe boxing absent** (pipes exposed); not the required low-level condition evidence set.

**RP-020 Google**
- `RP-020.antigravity-builtin.A-wide` | **accept** | Photographic stairs/landing; carpet, handrail, balustrade, painted walls, landing window.
- `RP-020.antigravity-builtin.B-reverse` | **accept** | Stairs to front hall, handrail, newel, pendant; photographic.
- `RP-020.antigravity-builtin.C-inventory` | **accept** | Landing window, radiator, smoke alarm, switch, sockets all clear.
- `RP-020.antigravity-builtin.D-condition` | **accept** | Stair carpet, brass carpet rod(s), skirting string, newel present — **but conflicts with A–C rod absence (packet escalate).**

**RP-020 OpenAI**
- `RP-020.gpt-image-2.A-wide` | **accept** | Photographic; stair carpet, handrail, balustrade, painted walls, landing window.
- `RP-020.gpt-image-2.B-reverse` | **accept** | Stairs, front hall/door, handrail, newel, pendant; photographic.
- `RP-020.gpt-image-2.C-inventory` | **accept** | Landing window, radiator, smoke alarm, switch, sockets present.
- `RP-020.gpt-image-2.D-condition` | **reject** | Stair carpet / string / newel present; **carpet rods clearly omitted** (required anchor absent).

---

### Escalations
1. **RP-017 OpenAI C** — thermostat vs switch ambiguity.
2. **RP-018 OpenAI B (+ packet)** — side-by-side (A/C) vs stacked (B) appliance layout.
3. **RP-018 OpenAI C** — isolator switches / air vent not clearly present.
4. **RP-019 OpenAI A** — vinyl vs wood-look laminate.
5. **RP-019 OpenAI B** — cupboard hinges / skirting weak.
6. **RP-019 OpenAI C** — isolator switches / air vent weak.
7. **RP-020 Google packet** — A–C show fitted carpet without rods; D introduces brass rods.
8. **RP-018 Google provenance** — incomplete per plan; does not change visual reject.

---

### Clear rejects
- **All 12 Google frames for RP-017, RP-018, RP-019** — illustrative, not photographic.
- **`RP-018.gpt-image-2.D-condition`** — missing sink cabinet / plinth / pipe boxing; intended defect unsupported.
- **`RP-019.gpt-image-2.D-condition`** — missing plinth and pipe boxing.
- **`RP-020.gpt-image-2.D-condition`** — missing carpet rods.

**Accept count:** 14 clear accepts · **Escalate:** 7 frames (+ 2 packet-level notes) · **Reject:** 15 frames"}]}}
{"type":"turn_ended","status":"success"}
