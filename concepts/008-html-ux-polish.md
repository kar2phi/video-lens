# HTML UX Polish — March 2026

A targeted pass over `template.html` (individual report viewer) and `gallery/index.html` (browse/filter page) to fix UX gaps, visual inconsistencies, and missed polish. Changes are grouped by the problem they solve.

---

## template.html

### Back-to-gallery link (nav-actions)

**Problem:** Reports open via `target="_blank"` so the browser back button does nothing useful. Once in a report there was no way to return to the gallery without closing the tab.

**Change:** Added a `←` chevron link (`#gallery-link`) to `.nav-actions`, before the markdown export button. Bound to the `g` keyboard shortcut and documented in the help modal. A JS guard hides the link unless the page is served from localhost — prevents a broken href when reports are opened directly from the filesystem or shared externally.

---

### Resizer handle visibility on hover

**Problem:** The `::after` drag handle (a short vertical line on the resizer bar) had `opacity: 0` on `:hover` and `.dragging`. This removed the visual affordance exactly when the user was looking for confirmation that they'd grabbed the handle.

**Change:** Flipped to `opacity: 1` on hover/drag, and added `background: rgba(255,255,255,0.7)` so the handle stands out against the now-red resizer bar.

---

### Help modal overflow on small screens

**Problem:** No `max-height` on `#help-modal`, so it could clip below the viewport on short screens.

**Change:** Added `max-height: calc(100vh - 4rem); overflow-y: auto`.

---

### Key Points / Takeaway font

**Problem:** `body { font-family: Georgia }` makes sense for prose (Summary reads like an article), but Key Points and Takeaway are dense bullet lists. Georgia at body size looks heavier than necessary for structured data and diverges from the gallery's treatment of the same content type.

**Change:** Surgical override: `#key-points li, #takeaway li` switch to DM Sans with `line-height: 1.65`. The Summary section (which is genuinely prose) keeps Georgia untouched.

---

### Outline expand animation

**Problem:** Outline details snapped open with `display: none → block` — no transition, visually jarring.

**Change:** Replaced with a `max-height` + `opacity` animation (0.18s ease). Ceiling is 150px — outline details are always short (1–3 lines, ~30–60px), so the height portion snaps in ~20ms while the opacity fade takes the full 0.18s, producing an effect that looks like a clean fade. Removed the old `display: none/block` overrides.

---

### Outline clickable affordance

**Problem:** Items had no visual signal they were interactive until hovered. `cursor: pointer` was set in JS per-item after the fact.

**Change:** Moved `cursor: pointer` to CSS on `ol.topics li`. Changed `border-left: 2px solid transparent` to `border-left: 2px solid rgba(0,0,0,0.07)` — a ghost rail that becomes red on active, providing a persistent interactive hint. Dark mode override added (`rgba(255,255,255,0.07)`). Removed the now-redundant JS cursor assignment.

---

### Progress bar: drag-to-seek + hover feedback

**Problem:** The progress bar only supported click-to-seek, not dragging. There was also no visual feedback that it was interactive.

**Change:**
- CSS: `transition: height 0.15s ease` + `#progress-track:hover { height: 5px }` — the bar grows on hover as an affordance.
- JS: Replaced the click handler with a mousedown/mousemove/mouseup drag handler. The `#progress-fill` transition is disabled during drag (prevents the fill lagging behind the cursor) and restored on mouseup.

---

### Section nav active underline

**Problem:** The 2px underline at 0.72rem uppercase was barely visible — easy to miss which section was active.

**Change:** In `.section-nav a`: `border-bottom: 2px` → `3px`, `padding-bottom: 2px` → `1px`. Total occupied height is unchanged (3+1 = 4 = 2+2), so layout doesn't shift.

---

## gallery/index.html

### Help modal overflow

Same fix as template.html: `max-height: calc(100vh - 4rem); overflow-y: auto`.

---

### Theme toggle button style

**Problem:** The theme toggle was a filled pill (`.theme-btn`) while every other icon button used `.icon-btn` (circular, bordered). Visually inconsistent.

**Change:** Replaced `<button class="theme-btn">` with `<button class="icon-btn">` containing an SVG icon. `applyTheme()` now sets the SVG `innerHTML` using the same `sunPath`/`moonPath` strings from template.html. Removed the `.theme-btn` CSS block entirely.

---

### Empty state visual signal

**Problem:** "No reports match" was plain unstyled text — no visual signal that it's a dead end rather than a loading state.

**Change:** Added a search-slash SVG icon above the heading. Updated `.empty p` to use `var(--left-meta)` for the subtext color (was inheriting `var(--left-heading)` grey from `.empty`, too faint).

---

### Help modal text styling

**Problem:** Gallery `#help-modal p` was missing the `color` and `font-family` declarations that template.html had, causing it to inherit inconsistently.

**Change:** Added `color: var(--right-text); font-family: 'DM Sans', system-ui, sans-serif` to `#help-modal p`.

---

### Tag chip overflow: raise cap + actionable "+N more"

**Problem:** The visible tag cap was 25, silently dropping any tags beyond that. Users with larger collections had no way to access the hidden tags from the filter bar.

**Change:** Cap raised to 50 (covers most collections). If total tags still exceed 50, a dashed `+N more` chip is rendered. Clicking it sets `showAllTags = true` and rebuilds the chip list showing all tags. This is actionable rather than a dead-end badge. `buildTagChips()` is now safe to call multiple times (clears the container before rebuilding, restores active state from `activeTags`).

---

### Card hover enhancement

**Problem:** `translateY(-2px)` was barely perceptible. `box-shadow` transition wasn't declared, so the shadow change was instant.

**Change:**
```css
.card { transition: background-color 0.2s, border-color 0.2s, transform 0.15s, box-shadow 0.15s; }
.card:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(0,0,0,0.13); border-color: var(--left-border); }
```

---

### Count display stability

**Problem:** The `N of M` count string changed width as filter results changed, causing the header layout to shift.

**Change:** Added `font-variant-numeric: tabular-nums; white-space: nowrap` to `#count`.
