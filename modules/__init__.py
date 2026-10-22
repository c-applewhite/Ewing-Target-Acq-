"""Pipeline modules for the Acquisition Target Finder.

Each module has one primary responsibility:

    collector
        Collect raw business records from the Google Places API.

    normalizer
        Normalize company names, phone numbers, addresses, cities,
        ZIP codes, and website domains.

    deduplicator
        Merge repeated records for the same physical location and group
        distinct locations under the same company when reliable evidence
        exists.

    classifier
        Apply transparent rules to classify companies as confirmed targets,
        probable targets, manual review, or excluded.

    scorer
        Calculate the transparent four-component, 100-point target score.

    reviewer
        Apply analyst classifications, notes, ownership corrections,
        product corrections, and score overrides.

    exporter
        Generate Excel and CSV outputs for ranked targets, manual review,
        exclusions, locations, and search summaries.
"""