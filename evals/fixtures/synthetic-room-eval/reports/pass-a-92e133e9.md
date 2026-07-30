### Packet summary table

| Packet | Room | Accept | Reject | Escalate | Continuity | Verdict |
|---|---|---:|---:|---:|---|---|
| RP-008 Google | Bedroom (empty) | 4 | 0 | 0 | Strong (pale blue, grey carpet, sash, white rad) | Packet OK |
| RP-008 OpenAI | Bedroom (empty) | 3 | 0 | 1 | Strong | C: TRV unclear |
| RP-009 Google | Bedroom (furnished) | 2 | 0 | 2 | Weak (B layout/headboard/bedding drift) | Escalate B+D; provenance gap |
| RP-009 OpenAI | Bedroom (furnished) | 3 | 1 | 0 | Strong A/B/D | C: sockets absent |
| RP-010 Google | Child bedroom | 0 | 4 | 0 | Layout coherent | All reject: readable brands |
| RP-010 OpenAI | Child bedroom | 2 | 1 | 1 | Strong A/B | C: blind/sockets; D: skirting |
| RP-011 Google | Living room | 1 | 1 | 2 | Fair (CRT, grey seating) | C: thermostat; B/D escalate |
| RP-011 OpenAI | Living room | 3 | 1 | 0 | Strong A/B/D | C: vertical blinds absent |
| RP-012 Google | Living room | 4 | 0 | 0* | Fair* (fireplace/floor tone drift) | Frames OK; bay in B clear; *packet escalate; provenance gap |
| RP-012 OpenAI | Living room | 2 | 2 | 0 | Broken by B | **B-reverse: no bay window** |

\\*Per-frame accepts; packet-level continuity escalated (fireplace identity / floor tone).

---

### Per-frame decisions (task_id | decision | reason)

**RP-008 Google**
| task_id | decision | reason |
|---|---|---|
| RP-008.antigravity-builtin.A-wide | accept | Bedroom clear; painted walls, grey carpet, sash, radiator, pendant present; photographic |
| RP-008.antigravity-builtin.B-reverse | accept | Door, furniture, built-in wardrobe, sockets, skirting clear; continuous with A |
| RP-008.antigravity-builtin.C-inventory | accept | Window, curtain pole, radiator, sockets clear; radiator valves support TRV |
| RP-008.antigravity-builtin.D-condition | accept | Grey carpet, skirting, doorstop, threshold strip clear |

**RP-008 OpenAI**
| task_id | decision | reason |
|---|---|---|
| RP-008.gpt-image-2.A-wide | accept | All A anchors present; photographic; continuous palette |
| RP-008.gpt-image-2.B-reverse | accept | Door, furniture, built-in wardrobe, socket(s), skirting present |
| RP-008.gpt-image-2.C-inventory | escalate | Window/pole/radiator/sockets clear; thermostatic valve not clearly identifiable (pipes only) |
| RP-008.gpt-image-2.D-condition | accept | Carpet, skirting, doorstop, threshold strip present |

**RP-009 Google** *(visual Pass A; provenance incomplete)*
| task_id | decision | reason |
|---|---|---|
| RP-009.antigravity-builtin.A-wide | accept | Double bed, headboard, bedside tables, wardrobe, cream carpet; bay visible for continuity |
| RP-009.antigravity-builtin.B-reverse | escalate | Required anchors present, but layout/headboard/wardrobe/bedding diverge from A/C enough to weaken multi-image pairing |
| RP-009.antigravity-builtin.C-inventory | accept | Bay, curtains, blinds, radiator, socket present |
| RP-009.antigravity-builtin.D-condition | escalate | Anchors present; intended *two* scratches — only one clear scratch beside top handle |

**RP-009 OpenAI**
| task_id | decision | reason |
|---|---|---|
| RP-009.gpt-image-2.A-wide | accept | All A anchors + bay; photographic |
| RP-009.gpt-image-2.B-reverse | accept | Door, chest, wall mirror, radiator, ceiling light; strong continuity with A |
| RP-009.gpt-image-2.C-inventory | reject | Bay/curtains/blinds/radiator present; **sockets absent** |
| RP-009.gpt-image-2.D-condition | accept | Drawer/handle/carpet/context clear; two short scratches match intended defect |

**RP-010 Google**
| task_id | decision | reason |
|---|---|---|
| RP-010.antigravity-builtin.A-wide | reject | Readable **LEGO CITY** poster branding |
| RP-010.antigravity-builtin.B-reverse | reject | Recognisable **Toy Story / Disney** character poster (brand IP) |
| RP-010.antigravity-builtin.C-inventory | reject | Readable **Catan Junior** + clear LEGO-style logo on box |
| RP-010.antigravity-builtin.D-condition | reject | Clear LEGO-style logo on toy box under wardrobe |

**RP-010 OpenAI**
| task_id | decision | reason |
|---|---|---|
| RP-010.gpt-image-2.A-wide | accept | Single bed, wardrobe, desk, blue rug, toy storage present; no readable brand text |
| RP-010.gpt-image-2.B-reverse | accept | Door, bookcase, radiator, ceiling shade, carpet present; continuity with A |
| RP-010.gpt-image-2.C-inventory | reject | Desk/chair/radiator present; **window blind absent** (curtains only); sockets not evidenced |
| RP-010.gpt-image-2.D-condition | escalate | Bed frame, carpet, blue rug clear; **skirting board** not clearly evidenced |

**RP-011 Google**
| task_id | decision | reason |
|---|---|---|
| RP-011.antigravity-builtin.A-wide | accept | Grey sofa, armchair, coffee table, TV unit, beige carpet; photographic |
| RP-011.antigravity-builtin.B-reverse | escalate | Door, bookcase, radiator, partial floor lamp present; ceiling fixture is directional spots, not a clear **ceiling shade** |
| RP-011.antigravity-builtin.C-inventory | reject | Balcony door, vertical blinds, radiator, sockets present; **thermostat absent** |
| RP-011.antigravity-builtin.D-condition | escalate | Arm/cushion/carpet present; fray is large/jagged vs intended **small** frayed patch (label risk) |

**RP-011 OpenAI**
| task_id | decision | reason |
|---|---|---|
| RP-011.gpt-image-2.A-wide | accept | All A anchors present |
| RP-011.gpt-image-2.B-reverse | accept | Door, bookcase, radiator, floor lamp, ceiling shade present |
| RP-011.gpt-image-2.C-inventory | reject | Balcony door, radiator, thermostat present; **vertical blinds absent** (curtains/sheers only); sockets not evidenced |
| RP-011.gpt-image-2.D-condition | accept | Sofa arm, cushion, carpet; small fray/hole matches intended small fray |

**RP-012 Google** *(visual Pass A; provenance incomplete; bay continuity OK in B)*
| task_id | decision | reason |
|---|---|---|
| RP-012.antigravity-builtin.A-wide | accept | Leather sofa, patterned rug, fireplace, bookshelves, coffee table; bay present |
| RP-012.antigravity-builtin.B-reverse | accept | **Bay window clearly present** with blinds/curtains; door, armchair, radiator, floorboards present |
| RP-012.antigravity-builtin.C-inventory | accept | Fireplace surround, mantel, wall sconces, socket, skirting context present |
| RP-012.antigravity-builtin.D-condition | accept | Floorboards, rug edge, skirting, hearth present |

**RP-012 OpenAI** *(B-reverse bay check: FAIL)*
| task_id | decision | reason |
|---|---|---|
| RP-012.gpt-image-2.A-wide | accept | All A anchors; bay clearly at far end |
| RP-012.gpt-image-2.B-reverse | reject | **Required bay window absent** — flat back wall with door/radiator only; other B anchors present |
| RP-012.gpt-image-2.C-inventory | reject | Fireplace/mantel/wall light/bay present; **sockets absent** |
| RP-012.gpt-image-2.D-condition | accept | Floorboards, rug edge, skirting, hearth present |

---

### Escalations list

1. `RP-008.gpt-image-2.C-inventory` — TRV not clearly distinguishable from plain pipework  
2. `RP-009.antigravity-builtin.B-reverse` — packet continuity vs A/C (furniture layout / headboard / treatments)  
3. `RP-009.antigravity-builtin.D-condition` — scratch count (one clear vs intended two)  
4. `RP-010.gpt-image-2.D-condition` — skirting board not clearly evidenced  
5. `RP-011.antigravity-builtin.B-reverse` — ceiling shade identity (spots vs shade)  
6. `RP-011.antigravity-builtin.D-condition` — defect severity vs intended “small” fray  
7. **Packet-level:** Google `RP-012` — fireplace style and floor tone drift across views (frames individually pass)  
8. **Provenance (not Pass A visual):** Google `RP-009` and `RP-012` lack successful wrapper provenance  

---

### Clear rejects list

1. `RP-009.gpt-image-2.C-inventory` — sockets absent  
2. `RP-010.antigravity-builtin.A-wide` — readable LEGO CITY branding  
3. `RP-010.antigravity-builtin.B-reverse` — Toy Story / Disney brand characters  
4. `RP-010.antigravity-builtin.C-inventory` — readable Catan Junior + LEGO logo  
5. `RP-010.antigravity-builtin.D-condition` — LEGO logo on box  
6. `RP-010.gpt-image-2.C-inventory` — window blind absent; sockets not evidenced  
7. `RP-011.antigravity-builtin.C-inventory` — thermostat absent  
8. `RP-011.gpt-image-2.C-inventory` — vertical blinds absent; sockets not evidenced  
9. `RP-012.gpt-image-2.B-reverse` — **bay window absent** (required)  
10. `RP-012.gpt-image-2.C-inventory` — sockets absent  

**Counts:** 22 accept · 12 reject · 6 escalate (frame-level). Strongest hard fails: entire Google RP-010 brand set, and OpenAI RP-012 B-reverse missing bay evidence."}]}}
{"type":"turn_ended","status":"success"}
