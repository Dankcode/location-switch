# Validation

## Automated and browser checks

- 11 tests passed: coordinate validation (including NaN), unauthorized mutation rejection, spoof/restore dispatch, acknowledgment timing, unknown state after failure, device ownership, Photon longitude/latitude mapping and cache, search outage fallback, and Developer Mode preflight refusal.
- JavaScript syntax, Python compilation, launcher shell syntax and dependency lock consistency passed.
- Codex in-app browser used directly; no external Playwright fallback.
- Real address search: a public landmark query returned a matching result. Selection populated the coordinates and persisted across reload.
- Simulated hardware QA on a separate temporary server: set → spoofed status → restore → real status → second-device selection. Invalid latitude 91 disabled set. No fake devices are included in the shipped app.
- Final visual checks: desktop and mobile layouts were inspected; the 390px mobile layout had no horizontal overflow. QA screenshots are excluded from the public repository.

## Design comparison ledger

| Comparison | Concept / render evidence | Outcome |
| --- | --- | --- |
| Copy and order | Location Switch → Connected device → Spoof destination → Selected destination → actions → setup footer | Core copy/order preserved; dynamic device names and state messages reflect actual data. |
| Layout | Single centered column, shared left edge, address/search row, two coordinate columns, two wide desktop actions | Matches concept; actions stack on narrow screens. |
| Typography | Large navy title, lighter subtitle, clear section/field hierarchy, deliberate button sizes | System font implements concept hierarchy without a remote font dependency. |
| Palette | White canvas, navy text, cool-gray outlines, cobalt primary, outlined restore | Preserved; disabled controls visibly dim and keyboard focus uses a blue ring. |
| Spacing | Open whitespace, no nested cards, aligned form widths, divider before footer | Preserved; error messages expand the flow when needed. |
| Icon | Outline navigation arrow above heading | Code-native SVG matches the concept's metaphor and stroke treatment. |
| Responsive | Compact form and full-width actions | 390px layout checked; no clipping or overflow. |

The final implementation was checked against the design concept. Intentional differences: real connection/status states and disabled controls; native select arrow and number-input steppers; accessible focus ring; address-result list and operational messages; address-search attribution/privacy line; responsive stacked actions. Core above-the-fold copy has no unrelated additions. No remaining material layout defects were found. The generated concept is a reference, not a pixel-identical raster shipped as UI.

## Physical device test

The iPhone became available late in QA. A live set was attempted at a private test destination. Initial setup failed before the set operation because the developer DVT service was absent. Read-only diagnostics reported Developer Mode off and no developer image mounted. The app now checks Developer Mode before attempting the tunnel and explains the remedy.

This test did not apply a spoof. Physical GPS verification requires Developer Mode to report enabled, an appropriate developer image, and a successful set/clear. Neither session status nor a command response independently measures the phone's GPS. See README.md for setup and recovery.
