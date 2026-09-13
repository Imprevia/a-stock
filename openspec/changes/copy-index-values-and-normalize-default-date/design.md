## Context

The Section 01 cards are currently outer `<button>` elements whose click selects an index and redraws the charts. The card renders a fixed two-decimal close value and a localized daily change percentage, but has no clipboard affordance or feedback. The research date is derived in the browser with a 15:00 cutoff; the core response already exposes the effective trading date as `asOf` and can mark non-trading fallback in data quality.

## Goals / Non-Goals

**Goals:**

- Preserve card selection and chart behavior while making the close value and daily change independently copyable.
- Keep copied text identical to the visible, localized value and provide success/failure feedback that works with keyboard and assistive technology.
- Normalize only the initial automatically derived date to the backend-confirmed effective trading date, without overriding later manual choices.
- Keep the change provider-free at runtime and avoid API or payload changes.

**Non-Goals:**

- Copying index names, codes, trend labels, turnover ratios, or a combined multi-index summary.
- Adding a trading-calendar service, changing the 15:00 cutoff, or changing how manually requested historical dates are represented.
- Introducing a third-party clipboard or toast dependency.

## Decisions

1. **Separate controls instead of nested buttons.** Replace the semantic outer card button with a card container plus a dedicated selection button/region and two copy controls. This avoids invalid interactive nesting and lets copy handlers stop propagation without breaking selection. The controls carry explicit labels/titles and reuse the existing focus-visible treatment.

2. **Copy the rendered strings.** Build payloads from the same formatting functions used by the template (`close.toFixed(2)` and `formatPct(changePct)`). This prevents locale or sign drift between what users see and what they paste. Missing values remain unavailable rather than being converted to zero.

3. **Clipboard capability with safe fallback.** Attempt `navigator.clipboard.writeText` first. When the API is absent or rejects (notably on an HTTP NodePort origin), use a short-lived hidden textarea plus `document.execCommand('copy')` where supported; otherwise expose an `aria-live` failure message. Success is announced only after a confirmed write path completes.

4. **Ephemeral per-control feedback.** Track the last copy result by index and field so a success/failure label is local to the activated control and automatically clears after a short interval. A shared live region mirrors the message for screen readers without shifting the card layout.

5. **Initial-date synchronization at the response boundary.** Keep a flag that distinguishes the mount-triggered load from user date changes. On the initial response, compare the requested candidate with `asOf`; if they differ, update the date model to `asOf` without issuing a second fetch. Mark the flag false on any user date change so subsequent responses cannot rewrite the control.

6. **Tests and responsive verification.** Extend `app.test.ts` with clipboard success/failure and selection-isolation assertions, and extend date tests/component coverage for initial fallback normalization versus manual selection. Verify the copy controls at desktop and 390px widths; no page-level horizontal overflow is allowed.

## Risks / Trade-offs

- **[Risk]** `document.execCommand` is deprecated or unavailable in some browsers. **Mitigation:** treat it only as a best-effort fallback, keep the failure path explicit, and never announce success without a confirmed write.
- **[Risk]** Replacing the outer card button could subtly change keyboard focus or click hit areas. **Mitigation:** preserve a full-card selection control for non-copy content, add focused component tests, and run keyboard/browser checks.
- **[Risk]** A provider may return an earlier effective date for reasons other than a weekend/holiday. **Mitigation:** normalize only the initial automatic date and retain the response quality warning; manual requests are never rewritten.
- **[Risk]** Copy status text could crowd the compact card on mobile. **Mitigation:** use an absolute/inline status region with the existing 14px minimum and verify the 390px layout.
