---
paths:
  - "services/market_data_service*"
  - "**/*census*"
  - "**/*market*"
  - "**/*permit*"
  - "**/*population*"
---
# Market data (Census and enrichment)

Market enrichment is derived data from public sources. It must always carry its provenance, and it must degrade gracefully.

- Every enrichment figure — median household income, population, building-permit activity — is shown with its source and as-of year. Never present a derived number bare.
- Population for recent vintages comes from the downloadable Census CSVs (SUB-EST for places, CO-EST for counties) on www2.census.gov. The Census API does not serve local population past Vintage 2021. This is intentional; do not "fix" it by switching population to the API.
- Income comes from the Census API ACS5 (variable `B19013_001E`). Permits/1,000 is gated on a geography match — don't report a rate when the geography doesn't line up.
- The vintage / year constants (ACS5 year, population vintage, permit year) are deliberate. Changing them is an explicit, tested change, not a cleanup.
- Every external read has a timeout and a fallback the user can understand. A partial result with clear labels beats a failed page.
- API keys come from the environment / `.env`, never from code and never from a committed config file.
- Don't scrape. Market data comes from the Census sources above and discovery from the Google Places API — not from scraping pages.
