### Packet summary

| Packet | Verdict |
|---|---|
| **RP-013 Google** | All 4 reject — solid grey labeled placeholders; no room, no anchors, continuity meaningless |
| **RP-013 OpenAI** | Living-room move-in continuity OK (A↔B reverse, C window inventory, D floor detail). **C rejects** (sockets absent). **A escalate** (wall mark vs intended none) |
| **RP-014 Google** | All 4 reject — labeled `(Mock)` schematic diagrams, not photographic |
| **RP-014 OpenAI** | Hall continuity OK. **D rejects** — six pale scuffs in a 2×3 grid vs intended three |
| **RP-015 Google** | All 4 reject — flat clip-art / vector illustrations |
| **RP-015 OpenAI** | Same hall theme, but **A/B/D reject** (Nike swoosh and/or geometry). **C accept**. B is not a true reverse (still faces front door; stairs appear) |
| **RP-016 Google** | A+B only; photographic dining room; reverse continuity coherent → **both accept** |
| **RP-016 OpenAI** | Full A–D packet coherent (oak/grey chairs, French doors, pendant) → **all accept** |

---

### Per-frame decisions (task_id | decision | reason)

**RP-013 Google**
- `RP-013.antigravity-builtin.A-wide` | **reject** | Solid grey placeholder with task label; room not recognisable; illustrative not photographic
- `RP-013.antigravity-builtin.B-reverse` | **reject** | Same blank placeholder failure
- `RP-013.antigravity-builtin.C-inventory` | **reject** | Same blank placeholder failure; sockets/window/radiator absent
- `RP-013.antigravity-builtin.D-condition` | **reject** | Same blank placeholder failure

**RP-013 OpenAI**
- `RP-013.gpt-image-2.A-wide` | **escalate** | Clear photographic living room with charcoal sofa, nested tables, TV stand, boxes, laminate; but a distinct dark wall mark above the TV with intended defects `none`
- `RP-013.gpt-image-2.B-reverse` | **accept** | Entrance door, radiator, coat hooks, floor lamp, boxes all present; photographic; no brands/people
- `RP-013.gpt-image-2.C-inventory` | **reject** | Required **sockets absent** (walls obscured by boxes/sofa; no outlet visible on recheck). Blind is horizontal slats, not a clear roller blind
- `RP-013.gpt-image-2.D-condition` | **accept** | Laminate, table leg, rug edge, skirting present; photographic floor detail; intended none holds

**RP-014 Google**
- `RP-014.antigravity-builtin.A-wide` | **reject** | Labeled mock diagram; illustrative not photographic
- `RP-014.antigravity-builtin.B-reverse` | **reject** | Same mock/schematic failure
- `RP-014.antigravity-builtin.C-inventory` | **reject** | Same mock/schematic failure
- `RP-014.antigravity-builtin.D-condition` | **reject** | Same mock/schematic failure (text “three pale scuff marks” is not photographic evidence)

**RP-014 OpenAI**
- `RP-014.gpt-image-2.A-wide` | **accept** | Hall walls, striped runner, coat hooks, entryphone, ceiling light; photographic
- `RP-014.gpt-image-2.B-reverse` | **accept** | Front door, door chain, letter plate (mail slot), shoe rack, skirting; photographic
- `RP-014.gpt-image-2.C-inventory` | **accept** | Entryphone, consumer unit (fuse box), light switch, smoke alarm, sockets all clear
- `RP-014.gpt-image-2.D-condition` | **reject** | Intended three pale door scuffs; close inspection shows **six** uniform horizontal scuffs in a 2×3 grid — falsifies intended label. Threshold visible; door seal not clearly evidenced

**RP-015 Google**
- `RP-015.antigravity-builtin.A-wide` | **reject** | Flat illustrative room diagram, not photographic
- `RP-015.antigravity-builtin.B-reverse` | **reject** | Same illustrative failure
- `RP-015.antigravity-builtin.C-inventory` | **reject** | Same illustrative failure
- `RP-015.antigravity-builtin.D-condition` | **reject** | Same illustrative failure; rug lines also geometrically incoherent

**RP-015 OpenAI**
- `RP-015.gpt-image-2.A-wide` | **reject** | Clear Nike swoosh on black sneaker (logo/readable brand). Anchors otherwise present
- `RP-015.gpt-image-2.B-reverse` | **reject** | Nike branding on foreground sneaker; required doormat absent; view still faces front door (not reverse) and introduces staircase absent from A
- `RP-015.gpt-image-2.C-inventory` | **accept** | Radiator, thermostat, sockets, light switch, smoke alarm present; photographic; no clear brands
- `RP-015.gpt-image-2.D-condition` | **reject** | Unreliable shoe geometry (melted/malformed footwear). Doormat/tiles/skirting present; threshold strip at door not clearly shown; branding ambiguous on recheck

**RP-016 Google**
- `RP-016.antigravity-builtin.A-wide` | **accept** | Oak table, six chairs, French doors, pendant, timber floor; photographic; only negligible faint wall mark
- `RP-016.antigravity-builtin.B-reverse` | **accept** | Internal door(s), sideboard, radiator, wall mirror, skirting; coherent reverse from French doors

**RP-016 OpenAI**
- `RP-016.gpt-image-2.A-wide` | **accept** | All required dining anchors present; photographic
- `RP-016.gpt-image-2.B-reverse` | **accept** | Internal door, sideboard, radiator, mirror, skirting; mirror reflection consistent with French doors
- `RP-016.gpt-image-2.C-inventory` | **accept** | French doors, curtain pole, radiator, sockets, TRV present
- `RP-016.gpt-image-2.D-condition` | **accept** | Oak tabletop, chair upholstery, timber floor, table leg; intended none holds

---

### Escalations
- `RP-013.gpt-image-2.A-wide` — distinct wall mark above TV vs intended defects `none`

---

### Clear rejects
- **All Google RP-013** (4) — blank placeholders  
- **All Google RP-014** (4) — labeled mocks  
- **All Google RP-015** (4) — illustrative diagrams  
- `RP-013.gpt-image-2.C-inventory` — required sockets absent  
- `RP-014.gpt-image-2.D-condition` — six scuffs vs intended three  
- `RP-015.gpt-image-2.A-wide` — Nike logo  
- `RP-015.gpt-image-2.B-reverse` — Nike logo + missing doormat + broken reverse continuity  
- `RP-015.gpt-image-2.D-condition` — unreliable shoe geometry  

**Counts:** accept 14 · reject 15 · escalate 1 (of 30 frames)"}]}}
{"type":"turn_ended","status":"success"}
