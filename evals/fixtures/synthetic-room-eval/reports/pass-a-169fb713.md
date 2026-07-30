### Packet summary table

| Scenario | Provider | Room | Overall | Notes |
|---|---|---|---|---|
| RP-001 | Google | Kitchen | escalate | Room OK; induction identity weak; B missing blind; cooker config/handles/floor drift across views |
| RP-002 | Google | Bathroom | mixed | Strong bathroom packet; C clear brand reject; D scuff heavier than “short shallow”; floor finish drifts |
| RP-003 | OpenAI | Kitchen | mixed | Strong kitchen look; C missing heat alarm; A/D splashback type drifts (wood upstand vs subway) |
| RP-004 | Google | Kitchen | reject_packet | Fairy logo on A; B missing radiator/blind; D peel≠triangular tear |
| RP-004 | OpenAI | Kitchen | mixed | Good floor tear on D; C has dishwasher not under-counter fridge; oven freestanding↔built-in drift |
| RP-005 | Google | Kitchen | mixed | Blue island kitchen clear; B readable brand; C no heat alarm; D missing stool/tiles; A wood vs B tiles |
| RP-005 | OpenAI | Kitchen | mixed | Strong navy kitchen; B/D lack required floor tiles; C no heat alarm |
| RP-006 | Google | Bathroom | mixed | A/C strong; B no extractor + towel-rail/reflection oddities; D chip OK, silicone unclear |
| RP-006 | OpenAI | Bathroom | mixed | Strong continuity; C missing floor drain; B extractor ambiguous; D silicone unclear |
| RP-007 | Google | Shower room | mixed | Sloped shower room clear; C missing soap tray; A tile floor vs B vinyl drift |
| RP-007 | OpenAI | Shower room | accept_all | Coherent attic shower room; soap dish present on C; no hard rejects |

Skipped: OpenAI RP-001 / RP-002 (already `pass_a_accepted`). No Google RP-003 in queue.

---

### Per-frame decisions

**RP-001 Google**
- `RP-001.antigravity-builtin.A-wide` | escalate | Kitchen clear; glass hob shows radiant rings, not clearly induction
- `RP-001.antigravity-builtin.B-reverse` | reject | Required window blind absent (bare window); skirting unclear
- `RP-001.antigravity-builtin.C-inventory` | escalate | Anchors mostly present; hob still not clearly induction; appliance style vs A/B drifts
- `RP-001.antigravity-builtin.D-condition` | escalate | Required surfaces present; chip much larger than “small”; handles/floor pattern vs A diverge

**RP-002 Google**
- `RP-002.antigravity-builtin.A-wide` | accept | Bath, screen, basin, WC, towel rail, grey tiles all clear
- `RP-002.antigravity-builtin.B-reverse` | escalate | Core fixtures OK; skirting not clearly evidenced
- `RP-002.antigravity-builtin.C-inventory` | reject | Readable Dove logo on bath ledge bottle
- `RP-002.antigravity-builtin.D-condition` | escalate | Bath panel/silicone/tiles present; scuff prominent vs “short shallow”; floor looks plank vs A seamless vinyl

**RP-003 OpenAI**
- `RP-003.gpt-image-2.A-wide` | accept | White units, oak-effect top, sink, oven, ceramic hob present
- `RP-003.gpt-image-2.B-reverse` | escalate | Fridge/radiator/door present; floor reads wood laminate not vinyl; skirting unclear
- `RP-003.gpt-image-2.C-inventory` | reject | Heat alarm absent (ceiling shows bare bulb only)
- `RP-003.gpt-image-2.D-condition` | escalate | Splashback/grout/worktop/socket present; subway tiles conflict with A wood upstand

**RP-004 Google**
- `RP-004.antigravity-builtin.A-wide` | reject | Readable Fairy logo on dish soap
- `RP-004.antigravity-builtin.B-reverse` | reject | Radiator absent; window blind absent (lace/curtains only); clock/door present
- `RP-004.antigravity-builtin.C-inventory` | accept | Sink, drainer, mixer, sockets, under-counter fridge present; brand text not clearly readable
- `RP-004.antigravity-builtin.D-condition` | reject | Floor damage is large peel/lift, not small triangular tear; would falsify intended label

**RP-004 OpenAI**
- `RP-004.gpt-image-2.A-wide` | accept | Wood units, laminate top, freestanding cooker, sink, patterned vinyl present
- `RP-004.gpt-image-2.B-reverse` | escalate | Door/radiator/clock present; “window blind” is lace+curtains; skirting unclear
- `RP-004.gpt-image-2.C-inventory` | reject | Under-counter fridge absent (dishwasher in its place)
- `RP-004.gpt-image-2.D-condition` | escalate | Triangular tear + required low evidence present; cooker reads built-in vs A freestanding

**RP-005 Google**
- `RP-005.antigravity-builtin.A-wide` | accept | Blue units, island, range, sink, pendants present
- `RP-005.antigravity-builtin.B-reverse` | reject | Readable “Marriage’s” flour brand; patio doors/radiator/stools/tiles present
- `RP-005.antigravity-builtin.C-inventory` | reject | Heat alarm absent (smoke detector only); Rangemaster-like branding also concerning
- `RP-005.antigravity-builtin.D-condition` | reject | Bar stool absent; floor tile absent (wood planks); worktop/island present

**RP-005 OpenAI**
- `RP-005.gpt-image-2.A-wide` | accept | Blue units, island, range, sink, pendants present
- `RP-005.gpt-image-2.B-reverse` | reject | Required floor tiles absent (wood planks); radiator/patio doors/stools present
- `RP-005.gpt-image-2.C-inventory` | reject | Heat alarm absent; Waitrose-like bag also brand risk
- `RP-005.gpt-image-2.D-condition` | reject | Floor tile absent (wood); stool/worktop/island present

**RP-006 Google**
- `RP-006.antigravity-builtin.A-wide` | accept | Walk-in shower, WC, vanity, towel rail, stone tiles present
- `RP-006.antigravity-builtin.B-reverse` | reject | Extractor vent absent; three towel rails + mirror reflection mismatch (geometry/continuity)
- `RP-006.antigravity-builtin.C-inventory` | accept | Rain head, handset, mixer, glass, floor drain present
- `RP-006.antigravity-builtin.D-condition` | escalate | Chip on drawer corner present; silicone joint not clearly shown; mixer only partial

**RP-006 OpenAI**
- `RP-006.gpt-image-2.A-wide` | accept | Walk-in shower, WC, vanity, towel rail, stone tiles present
- `RP-006.gpt-image-2.B-reverse` | escalate | Door/vanity/mirror/tiles present; ceiling disc may be vent or detector
- `RP-006.gpt-image-2.C-inventory` | reject | Floor drain absent; rain/handset/mixer/glass present
- `RP-006.gpt-image-2.D-condition` | escalate | Chip + drawer/basin/tap present; silicone joint not clearly shown

**RP-007 Google**
- `RP-007.antigravity-builtin.A-wide` | accept | Enclosure, pedestal basin, WC, mosaic, sloped ceiling present
- `RP-007.antigravity-builtin.B-reverse` | escalate | Door/mirror/towel ring/extractor/vinyl present; floor type vs A (tiles) drifts
- `RP-007.antigravity-builtin.C-inventory` | reject | Soap tray absent; handset/mixer/glass/extractor present
- `RP-007.antigravity-builtin.D-condition` | accept | Mosaic, grout, silicone, shower tray present

**RP-007 OpenAI**
- `RP-007.gpt-image-2.A-wide` | accept | Enclosure, pedestal basin, WC, mosaic, sloped ceiling present
- `RP-007.gpt-image-2.B-reverse` | accept | Door, mirror, towel ring, extractor, vinyl present; matches A identity
- `RP-007.gpt-image-2.C-inventory` | accept | Handset/mixer/glass/extractor present; soap dish on riser
- `RP-007.gpt-image-2.D-condition` | accept | Mosaic, grout, silicone, shower tray present

---

### Escalations list

- **RP-001 A/C**: hob not clearly induction (radiant rings / ambiguous glass hob)
- **RP-001 D**: chip severity >> “one small chip”; handle/floor continuity vs A
- **RP-001 packet**: freestanding white cooker (A/B) vs built-in stainless (C) — multi-view identity weak
- **RP-002 B**: skirting not clearly visible
- **RP-002 D**: scuff larger/more conspicuous than “short shallow”; floor finish vs A
- **RP-003 B**: vinyl vs wood-effect laminate; skirting unclear
- **RP-003 D / packet**: splashback type change vs A
- **RP-004 OpenAI B**: blind vs lace/curtains; skirting unclear
- **RP-004 OpenAI D / packet**: freestanding vs built-in oven continuity
- **RP-006 Google D**: silicone not clear; mixer partial
- **RP-006 OpenAI B**: extractor vs detector ambiguity
- **RP-006 OpenAI D**: silicone not clear
- **RP-007 Google B / packet**: floor finish drift (A dark tiles vs B vinyl); tap style drift A↔B

---

### Clear rejects list

- **RP-001.antigravity-builtin.B-reverse** — required window blind absent
- **RP-002.antigravity-builtin.C-inventory** — readable Dove brand
- **RP-003.gpt-image-2.C-inventory** — heat alarm absent
- **RP-004.antigravity-builtin.A-wide** — readable Fairy brand
- **RP-004.antigravity-builtin.B-reverse** — radiator and window blind absent
- **RP-004.antigravity-builtin.D-condition** — peeled floor, not small triangular tear
- **RP-004.gpt-image-2.C-inventory** — under-counter fridge absent (dishwasher instead)
- **RP-005.antigravity-builtin.B-reverse** — readable Marriage’s brand
- **RP-005.antigravity-builtin.C-inventory** — heat alarm absent
- **RP-005.antigravity-builtin.D-condition** — bar stool and floor tile absent
- **RP-005.gpt-image-2.B-reverse** — floor tiles absent
- **RP-005.gpt-image-2.C-inventory** — heat alarm absent
- **RP-005.gpt-image-2.D-condition** — floor tiles absent
- **RP-006.antigravity-builtin.B-reverse** — extractor vent absent (+ geometry/continuity concerns)
- **RP-006.gpt-image-2.C-inventory** — floor drain absent
- **RP-007.antigravity-builtin.C-inventory** — soap tray absent

No files modified; nothing marked accepted in `tasks.csv`."}]}}
{"type":"turn_ended","status":"success"}
