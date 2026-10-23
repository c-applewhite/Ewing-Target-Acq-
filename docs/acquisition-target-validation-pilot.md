# Acquisition Target Validation Pilot

## Purpose

Test whether the existing Acquisition Target Finder helps Ewing identify independent suppliers worth investigating for acquisition. The pilot evaluates discovery, qualification, and analyst prioritization; it does **not** authorize changing the frozen classifier or 100-point score.

An acquisition-fit score is not evidence that a business is willing or available to sell. A public Sale Signal is separate evidence; no public match means availability is unknown, not that the business is unavailable.

## Pilot scope and participants

- **Markets:** three distinct, analyst-selected markets. Use (1) an existing-branch market, (2) a ZIP market near Ewing operations, and (3) a ZIP market with limited nearby Ewing presence. Select actual markets with the corporate-development analyst; do not infer or invent representative locations.
- **Runs:** use recent completed runs for those markets if their search terms, radius, and data are suitable. Otherwise, create one new run per market with the existing workflow and record its run ID, date, search terms, radius, and search mode.
- **People:** one developer prepares and reconciles the data; one corporate-development analyst supplies the known-business roster, evaluates candidates, and creates an independent shortlist.
- **Size:** review all `confirmed_target` and `probable_target` companies returned for each run, all known businesses whether or not found, and a small documented sample of `manual_review` and `excluded` rows. If the positive list is too large to review in one sitting, pause and agree a smaller set of markets or a sampling method before calculating precision.
- **No live API requirement:** do not repeat searches just to run the pilot if suitable existing results are available. Record any difference in run age or settings.

## Data needed

1. **Three run datasets:** run ID, market, search mode, radius, terms, completion date/status, and every company-level result with its Google Place ID (when available), name, locations, website/domain, Google categories, product flags, analyst-visible operating indicators, distance, app classification, overall score, band, component scores, and search evidence.
2. **Known-business roster per market:** businesses the analyst already believes are independent landscape / hardscape / stone / masonry / related suppliers and wants the search to find. Include name, city/address or website, how the business was identified, and an evidence date. Record the basis for independence and target relevance. The roster is a validation reference, not a claim to be a complete census of the market.
3. **Human review:** worksheet fields below, including evidence and rationale for judgments. The analyst should review candidates without seeing the app classification or score before making an independent shortlist.
4. **Optional Sale Signal evidence:** status, source, URL, and checked date, if present in the run or verified separately. Keep this out of the acquisition-fit judgment and score comparison.

Do not scrape sites or add a new provider for this pilot. Use existing run evidence and exports plus analyst-provided knowledge and sources approved for ordinary research.

## Worksheet

Use one row per unique company per run. Suggested CSV header:

```csv
market_id,run_id,company_id,place_id,company_name,city,state,address,website,google_categories,product_flags,rating,review_count,operational_status,location_count,distance_miles,search_evidence,known_target,known_target_match_method,app_classification,app_score,app_score_band,app_rank,app_product_fit,app_geographic_fit,app_business_quality,app_data_confidence,analyst_independent_supplier,analyst_target_fit,analyst_priority_rank,analyst_decision,analyst_rationale,missing_evidence,reviewer,review_date,independence_evidence,public_sale_signal,public_sale_source,public_sale_url,public_sale_checked_date
```

Use these review values consistently:

- `analyst_independent_supplier`: `yes`, `no`, or `uncertain`.
- `analyst_target_fit`: `strong`, `possible`, `not_fit`, or `insufficient_evidence`.
- `analyst_decision`: `investigate`, `hold_for_information`, `do_not_prioritize`, or `duplicate_or_closed`.
- `analyst_priority_rank`: a rank assigned during the blind review; blank if not in the analyst's top 20.
- `known_target`: `yes` or `no`; mark from the pre-run known-business roster, not from the app score.
- `public_sale_signal`: use the recorded signal status or `not_checked`. Do not use this field to label acquisition fit or analyst priority.

Keep a separate analyst-facing copy with `classification`, scores, bands, and `app_rank` hidden until the analyst has recorded independent supplier/fit judgments and their top-20 ranking. Then restore those columns for comparison. Add known businesses not found by the app as rows with a stable local ID, `known_target=yes`, and no app result fields.

## Execution

1. **Choose and document markets.** The analyst picks three markets covering the market types above and supplies a known-business roster for each before reviewing that market's results. Note when no credible known-business roster can be assembled; recall for that market will then be unmeasurable.
2. **Freeze the run input.** Select suitable existing runs or make one run per market. Record settings and preserve the run IDs. Do not alter search terms or scoring between the three runs to make one market look better.
3. **Extract complete company results.** Use existing run results and Excel export where useful. The CSV export is a ranked shortlist of confirmed/probable targets, not the full classified result set; it cannot by itself measure false negatives or inspect manual/excluded rows. Use the run-scoped Results API across all pages, or the workbook's run-level location data reconciled to unique companies, when the full population is needed.
4. **Build blind worksheets.** Deduplicate to one row per company per run. Match known businesses first by Place ID if available, otherwise by website/domain plus location, then by name and address with analyst confirmation. Preserve ambiguous matches for adjudication rather than counting them as found.
5. **Review and rank.** The analyst reviews all confirmed/probable results for target fit, plus the known businesses not found and the documented sample of manual-review/excluded results. Before seeing model output, the analyst identifies and ranks up to 20 businesses worth investigating from the discovered results, records why, and notes what evidence is missing. If fewer than 20 merit investigation, rank only those and document that choice.
6. **Unblind and compare.** Reveal app class, scores, component explanations, and app ranking. Reconcile company matches and analyst decisions. Discuss high-score false positives, known targets classified manual/excluded, and promising analyst picks ranked below the app's top 20.
7. **Separate availability check.** Record any Sale Signal status and provenance independently. A positive public listing can inform follow-up; `No Signal`, `No Public Match`, and `not_checked` do not mean unavailable and do not change any fit or prioritization label.

## Measures

Report counts and rates **per market and combined**, alongside the numerator and denominator. Do not claim statistical certainty from this small, analyst-curated pilot.

| Measure | Calculation | What it tells us |
|---|---|---|
| Known-target discovery recall | Known businesses matched to any company result, including manual-review or excluded results ÷ known businesses with a usable identity in the roster | Whether search surfaced the known suppliers at all. Also list not-found and ambiguous matches individually. |
| Known-target qualified recall | Known businesses classified `confirmed_target` or `probable_target` ÷ known businesses with a usable identity | Whether discovery plus the existing qualification gate surfaced known targets as candidates. Show known businesses found only as manual review/excluded separately. |
| Candidate precision | Analyst-confirmed independent suppliers with `strong` or `possible` target fit among all `confirmed_target` and `probable_target` results ÷ all such results reviewed | How often the model's positive candidate classes appear relevant to the analyst. |
| Candidate false-positive share | Positive-class results judged `not_fit` or not independent ÷ all `confirmed_target` and `probable_target` results reviewed | How much analyst effort is spent rejecting positive-class candidates. This is the false-discovery share among candidates, not the conventional false-positive rate. Report `uncertain` separately, not as a silent negative. |
| False-positive rate (optional) | Positive-class results judged `not_fit` or not independent ÷ all reviewed results judged `not_fit` or not independent (FP ÷ [FP + TN]) | Use only when the full relevant result universe has been human-reviewed; otherwise label the denominator as sampled and do not generalize it. |
| Top-K agreement | Number of businesses shared by the app's top K ranked results and the analyst's blind top K ÷ K. Calculate K=10 and K=20 when each list has at least K entries; otherwise report the actual K. | Whether the current score ranking surfaces the businesses the analyst would prioritize. Also report analyst top-K candidates outside app top-K. |
| Score-band review | Counts of `strong`, `possible`, `not_fit`, and `insufficient_evidence` judgments within each app score band | Whether the bands separate promising from marginal results in these markets. Use as descriptive evidence, not proof of predictive validity. |

For the recall denominator, exclude roster entries that cannot be reliably identified in the market and list them with the exclusion reason. Do not remove valid known businesses just because the app did not find them. For precision and false-positive calculations, review every positive-class result in the selected runs; if that cannot be done, report the sample and do not present an unweighted sample rate as full-run precision.

Qualification and score-band findings are related, not independent: the existing data-confidence component gives credit based in part on the rule-based classification. Compare app ranks and scores against the analyst's blind judgments, but do not count agreement between the classifier and total score as separate validation evidence.

Before the analyst sees unblinded scores, the product owner should agree what recall, candidate precision, and top-K agreement would be useful enough for this pilot. The project has no existing acceptance thresholds; do not invent a pass/fail result after seeing the data.

## Results and next-priority decision

Produce a short summary with the three market settings, run IDs/dates, known-roster size and source, metrics with denominators, review limitations, and a few anonymized or approved examples of misses and false positives. Do not label any company as available for acquisition based on fit or score.

Use the evidence to choose the next product question, not to change the frozen model during validation:

- **Discovery gap:** several credible known businesses are absent or mismatched. Investigate search coverage/terms or result reconciliation first.
- **Qualification gap:** known businesses are found but often end up manual/excluded, or positive classes contain many analyst `not_fit` judgments. Investigate classifier/product evidence with the product owner; do not silently retune it.
- **Prioritization/usability gap:** top-K overlap is weak or analysts cannot explain why a company ranked highly. Investigate score transparency, evidence presentation, and analyst workflow before proposing any model change.
- **No clear gap / insufficient evidence:** do not build a speculative feature. Improve the validation sample or gather more analyst-labeled examples first.

The pilot is diagnostic; no numeric go/no-go threshold is currently specified in the PRD.

## Review API 250-record limit

There is a real **Review-screen retrieval limitation**, but not a hard API ceiling on the full run:

- `/api/results` accepts `page` and `per_page`, caps each response at 250, and returns `total` and `pages`.
- The Review screen requests `per_page=1000`, which the API reduces to 250. The screen does not request later pages, so it displays at most the first 250 score-ranked records for a run.
- The Results screen uses API pagination (50 per page by default), so later results can be reached there. The run-scoped API can also return later pages when requested.
- `/api/export/csv` includes only `confirmed_target` and `probable_target` rows, so it is not a complete source for false-negative or classification review. Use API pages or the Excel export's run-level location data for manual-review/excluded rows, carefully deduplicating locations to companies.

Thus, additional results are accessible through existing functionality, but the Review screen alone silently omits them when a run has more than 250 companies. Record actual counts per selected run and use a complete source for pilot calculations. Fixing Review-screen pagination would be a separate feature decision, not part of this validation pilot.

## Validation boundary

The developer can collect run settings, reconcile IDs, calculate the defined metrics, and report the API/export limits. The analyst must choose representative markets, provide the known-business roster, determine independence and target fit, rank candidates, and explain judgments. Search recall cannot be evaluated without a credible known-business roster; score usefulness cannot be concluded without analyst judgments. No validation results are asserted in this plan.
