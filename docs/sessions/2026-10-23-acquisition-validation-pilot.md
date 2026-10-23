# Acquisition Validation Pilot — 2026-10-23

## What we set out to do

Develop a lightweight validation pilot for discovery, qualification, and analyst prioritization in Acquisition Target Finder, including the practical effect of the Review API's 250-record cap.

## What actually got done

- Updated [the validation pilot](../acquisition-target-validation-pilot.md) with explicit app-result columns in the worksheet and corrected the positive-candidate false-positive metric label. Added the conventional false-positive-rate formula as optional, requiring a fully reviewed negative universe.
- Verified from the current implementation that `/api/results` supports page navigation with a maximum of 250 records per response; the Review screen requests 1,000 but does not fetch later pages. The run-scoped CSV export covers confirmed/probable candidates only; Excel includes additional review/excluded and location sheets.
- No app behavior, scoring, classification, or tests were changed. No PR was opened.

## Where I went wrong or had to be corrected

- I initially tried to create the pilot document as a new file before checking that the exact path already existed. The tool rejected the duplicate creation; I then read and updated the existing tracked document without overwriting it.

## What the human had to repeat more than once

Nothing.

## Proposed changes

None. The validation plan is project documentation for the requested exercise; no standing rule or skill change is warranted.
