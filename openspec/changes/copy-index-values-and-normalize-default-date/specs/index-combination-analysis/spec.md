## ADDED Requirements

### Requirement: Independent copying of index values and daily changes

The Section 01 index cards SHALL expose two separate, keyboard-focusable copy controls for each displayed index: one for the formatted index value (the close value) and one for the formatted daily change percentage. Each control SHALL copy exactly the text visible in its own field, SHALL NOT copy the index name, and SHALL NOT change the selected index or chart when activated. A successful copy SHALL be announced with a short accessible status; an unavailable or rejected clipboard operation SHALL show a failure status and MUST NOT claim success.

#### Scenario: Copy an index value without selecting the card

- **WHEN** the user activates the copy control attached to an index value such as `3833.38`
- **THEN** the clipboard receives exactly `3833.38`, a success status is shown, and the selected index remains unchanged

#### Scenario: Copy a daily change percentage independently

- **WHEN** the user activates the copy control attached to a daily change such as `+0.82%`
- **THEN** the clipboard receives exactly `+0.82%`, a success status identifies the change value, and the card's selection state is unchanged

#### Scenario: Clipboard permission or capability is unavailable

- **WHEN** the browser rejects or does not provide a clipboard write operation
- **THEN** the interface attempts its supported local fallback or reports a visible and accessible copy failure, without displaying a success status

### Requirement: Initial research date resolves to an actual trading day

The research dashboard SHALL retain its existing local-time 15:00 cutoff when deriving the initial candidate date, but after the first core response it SHALL synchronize the date control to the response's effective trading date whenever the candidate was a non-trading date or otherwise fell back. This automatic synchronization SHALL apply only to the initial default load; a date explicitly chosen by the user SHALL remain selected even when the response reports a different effective date, with the existing data-quality warning preserved.

#### Scenario: Initial weekend or holiday candidate is normalized

- **WHEN** the first load derives a calendar date that has no market session and the core response reports an earlier effective `asOf`
- **THEN** the top date control displays that effective trading date while the response retains its existing fallback warning

#### Scenario: Initial candidate is already a trading day

- **WHEN** the first load's 15:00-derived candidate is the effective trading date
- **THEN** the date control remains unchanged and no extra request is triggered

#### Scenario: Manual date selection is not overwritten

- **WHEN** the user selects a date explicitly and the response uses a different effective date because the selected date has no session
- **THEN** the date control keeps the user's selected date and the page displays the existing effective-date/quality distinction
