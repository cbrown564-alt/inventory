# Market research: property inventory & inspection apps (July 2026)

Compiled from a multi-agent web research sweep (25 sources, 124 extracted claims).
**Caveat:** most competitor claims come from vendors' own marketing pages and were
not adversarially verified. Pricing/ratings captured ~mid-2026.

## Headline conclusions

1. **"Video walkthrough → AI report" already exists and is not a moat.** At least five
   UK players ship it: iListingAI/Inspecti, Amnis, KapturAI, Inspecto, Paraspot.
2. **Every AI-native entrant targets professionals** (inventory clerks, letting agents,
   portfolio managers). None is positioned for self-managing landlords or renters at
   tenancy changeover. That consumer segment is the open position.
3. **UK deposit schemes define a concrete evidential spec** an app must meet (see below).
   DIY landlord reports carry an "independence discount" that product design must mitigate.
4. **Speed messaging is commoditised** ("90% faster", "under 5 minutes"). Differentiate on
   trust/evidence quality, consumer accessibility, and report design instead.

## Competitive map

### Photo-first incumbents (professional market)
| Product | Notes |
|---|---|
| Inventory Hive | UK leader positioning; photos + 360° cameras (Ricoh Theta/Insta360); AI limited to meter reading; 6 pro segments incl. landlords; Android app ~3.6★ from only 29 ratings (~5k downloads) |
| InventoryBase | "Trusted by Professionals"; 750m+ images vs 2m+ minutes video; BaseAI generates text from photos, explicitly assistive; £25–£200/month (Capterra) |
| Reports2Go | Free — caps low-end willingness to pay; photo/video attachment, no AI generation |
| Imfuna | PAYG from ~£10/report; positions on timestamped evidence + audit trails for TDS/DPS |

### AI-native video-first entrants (all professional-targeted)
| Product | Capture | AI | Pricing | Evidence positioning |
|---|---|---|---|---|
| iListingAI ("Inspecti") | Narrated video walkthrough, real-time analysis | Google Gemini multimodal, 1fps + fused voice, 1M-token context | Flex £9/report (7-day retention!); Pro Clerk £79/mo (£65 annual) | TDS/DPS-friendly: timestamps, geo, audit trail, dual e-signature |
| Amnis | Single narrated video sent to a WhatsApp bot | CV + speech recognition; rooms, items, condition ratings | £10/inspection PAYG; per-door subscription | "Every frame links back to the original unedited video" |
| KapturAI (Kaptur) | One walkthrough video | Full inventory generated in minutes; auto check-in/check-out comparison | n/a | No deposit-scheme evidential features disclosed |
| Inspecto | "Film any property on any phone" | Auto issue detection, voice-to-notes | Free £0 / Solo £15 / Growth £49 / Business £99 + AI credits (£0.50–£1.20 overage) | n/a |
| Paraspot | Tenant-performed AI-guided scans, real-time coverage validation | Before/after scan comparison | n/a | Time-stamped, geo-tagged reports |
| Inventorai | Photo upload, AI opt-in by design | "AI Mode" analyses photos | From £24/mo + AI credit packs | For clerks/agents/property managers |

### US / consumer-adjacent
| Product | Notes |
|---|---|
| RentCheck | 4.8★ from ~18k App Store ratings. Resident-led, room-by-room guided **photo** checklist → timestamped tamper-evident PDF. No video, no AI. UX complaints: zoom toggle regression (6 taps), one-active-user-per-inspection limit |

## The UK evidential spec (TDS / DPS / mydeposits)

An adjudication-ready inventory must have:
- **Date/timestamps on all media** — un-dated media cannot be verified (DPS also checks file metadata)
- **Tenant signature at check-in AND check-out** — mydeposits: max weight only when signed by both parties
- **Written report with embedded photos** — media complements the written record, "one should not replace the other"; video-only output is evidentially weak
- **Video must be time-referenced** — adjudicators need exact start/end times; raw unindexed video is a burden; highlight the relevant part
- **Comparison is the decisive artefact** — adjudicators decide by comparing check-in vs check-out; without both, landlord claims are "highly likely to be rejected"
- **Burden of proof is on the landlord** — deposit money is the tenant's until evidence proves otherwise
- **DIY (landlord-compiled) inventories are accepted but discounted** — need proof the tenant saw and had opportunity to agree/comment; mydeposits' credibility test asks "Is the inventory independent?"

Product mitigations for the independence discount: tenant review-and-countersign flow,
embedded dated photos, tamper-evident audit trail, frames linked to unedited source video.

## Pricing anchors
- PAYG: £9–10/report (iListingAI Flex, Amnis); Imfuna from ~£10
- Subscriptions: £15–99/mo (Inspecto tiers), £79/mo (iListingAI Pro Clerk), from £24/mo + credits (Inventorai), £25–200/mo (InventoryBase)
- Free floor exists (Reports2Go; Inspecto free tier)
- Note: iListingAI's £9 Flex tier retains reports only 7 days — long-term retention ("evidence vault") is a differentiation lever

## Coverage gaps in this research
Not captured: TIM, Property Inspect, InventoryFlex, zInspector, HappyCo, SnapInspect detail;
Inventory Hive/InventoryBase full pricing; cleaning-inspection and vehicle-inspection markets;
most app-store review corpora (only RentCheck iOS + Inventory Hive Android sampled).

## Open questions
1. How do TDS/DPS/mydeposits adjudicators treat **AI-generated** reports in practice? (No published guidance found — treatment inferred from DIY-inventory rules.)
2. Real-world output quality/traction of the video-first entrants (accuracy, hallucination rates, user numbers) — all current claims are their own marketing.
3. Pricing/ratings/roadmaps of the uncovered competitors above.
4. Size and willingness-to-pay of the UK self-managing landlord + renter segment; how many DIY landlords currently produce no inventory at all?

## Key sources
- Scheme guidance: mydeposits "Using photos and video as evidence" (PDF), TDS/DPS/mydeposits joint guide to deposits, disputes & damages (PDF), depositprotection.com "What makes good evidence", NRLA on photo/video evidence
- Vendors: inventoryhive.co.uk, inventorybase.co.uk, ilisting.ai, amnis.ai, kaptursoftware.co.uk, inspecto.co.uk, paraspot.ai, inventorai.co.uk, getrentcheck.com
- Store listings: RentCheck (App Store), Inventory Hive (Play Store)
