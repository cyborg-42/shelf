# SHELF — Project Goal (Frozen)

> **This document is locked.** It captures *why* Shelf exists and what
> "done" means. It does not change as implementation details change.
> Everything here is distilled from `SHELF_MASTER_DOCUMENT.md` (the
> master blueprint) as of 2026-09-25. If the vision genuinely needs to
> change, that's a conscious decision — don't silently drift from this file.

## 1. What Shelf Is

Shelf is an AI-IoT smart shelf system that tracks grocery/produce
inventory automatically, without manual entry. A 4-quadrant shelf uses:

- A **camera + YOLOv8n** object-detection model to recognize what produce
  item was just placed on or removed from the shelf.
- **4× HX711 load cells (ESP32-driven)** to continuously measure the
  weight on each quadrant.
- A **"delta-binding" pipeline** that fuses the two signals: a camera
  scan opens a short window; a weight increase during that window
  auto-binds the scanned item to that quadrant; a weight decrease is
  read as consumption.
- A **FastAPI backend** as the single source of truth (SQLite-backed),
  broadcasting live state over WebSocket.
- A **Flutter mobile app** as the human-facing view: live inventory,
  stock alerts, scan history, depletion forecasts.

## 2. The Problem It Solves

Manual inventory tracking (of a fridge, pantry, or retail shelf) is
tedious and gets abandoned. Shelf removes the manual step: put an item
down, the system already knows what it is and how much of it there is.

## 3. What "Done" Looks Like (Success Criteria)

Shelf is DONE when, live and unrehearsed, someone can:

1. Place a real produce item (apple, banana, orange, or carrot) in front
   of the camera and have it correctly identified.
2. Set that item on a physical quadrant of the shelf and watch the
   backend auto-bind it to that quadrant via the weight delta — no
   manual quadrant selection.
3. Remove/consume the item and see the shelf's recorded weight and
   status (Available / Low Stock / Critical / Depleted) update
   correctly within seconds.
4. Watch all of the above reflected live in the Flutter app (inventory
   view + WebSocket push), not just in a database or API response.
5. See a depletion forecast ("estimated days remaining") for each
   quadrant that is based on real logged weight history, not a
   hardcoded number.
6. Trust that this works for **all 4 quadrants**, not just one that
   happened to be demoed once.

If all six hold up under a live demo with real hardware, the system is
functionally complete. Everything else (polish, extra features, extra
produce classes) is bonus, not requirement.

## 4. Non-Negotiable Scope Boundaries

**In scope:** the 4-quadrant hybrid vision+weight pipeline described
above, for the 4 produce classes already supported (Apple, Banana,
Orange, Carrot), end-to-end from physical hardware to the phone app.

**Out of scope (don't let these become blockers):** supporting produce
classes beyond the current 4, a production-grade multi-user auth system,
cloud deployment, or a polished consumer-grade UI redesign. These are
future-roadmap ideas, not part of what "done" means for this project.

## 5. Evaluation Target

This is a final-year college/course project, and the stated bar is an
**8.5+ (out of 10)** on the course's evaluation. The exact rubric text
wasn't available when this file was written, so this section names the
dimensions any reasonable engineering-project rubric scores on — treat
it as the working target, and correct it here (this one section only,
not the frozen vision above) the moment the real rubric is seen:

- **Working end-to-end demo** — Section 3's six criteria, live, on real
  hardware. This is almost certainly the single biggest weight.
- **Technical depth** — the AI+IoT fusion (YOLO + delta-binding) is the
  project's actual novelty; be ready to explain *why* it works, not just
  that it does.
- **Robustness/testing** — the existing `smoke_test.py` and
  `test_binding.py` passing, for all 4 quadrants, not just Banana.
- **Documentation** — an accurate, current README (the existing one is
  stale and describes an earlier color-model approach — see the Finish
  Line checklist for the cleanup step).
- **Presentation/demo clarity** — a clean, rehearsed run-through, ideally
  with a fallback (recorded video) in case live hardware misbehaves.

## 6. How This File Is Used

- Section 1–4 (Vision, Problem, Success Criteria, Scope) are **frozen**.
  Don't rewrite them to match whatever got built — if reality diverges,
  that's a signal to fix the build, not the goal.
- Section 5 (Evaluation Target) may be corrected once the real rubric is
  known — it's a working estimate, not the vision itself.
- Day-to-day implementation steps live in the "Shelf Finish Line"
  checklist (tracked separately), which should always be read as
  "how we get to Section 3," never as a redefinition of Section 3.

*Source: distilled from SHELF_MASTER_DOCUMENT.md v2.0.0, sections
1 (Executive Summary), 2 (Architecture), and 11 (Strategic Roadmap).*
