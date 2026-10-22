---
paths:
  - "services/**"
  - "models/**"
  - "**/*repository*"
  - "**/*database*"
---
# Data access

- External data comes from the services layer (`services/`), which reads API keys from the environment / `.env`. Never put a key or secret in code or a committed config file.
- Every external call (Google Places, Census, Brave) has a timeout and a graceful fallback. On failure, show the user the last known / partial data with a clear label, not a crash.
- The database is SQLite via SQLAlchemy. Do not add Postgres, Redis, a background worker, or a message queue — that infrastructure is deferred (see the PRD). Do not open a direct P21 or Snowflake connection; customer demand arrives as a CSV import.
- Schema changes are additive and nullable, applied by `_migrate_schema()` at startup. Never drop or rename a column or table in a way that loses data. Legacy data (the DFW market, legacy score columns) is preserved.
- Keep data-access logic in the services / models layers. Routes in `app.py` coordinate; they don't hand-roll external calls scattered through the handler.
- Log external calls enough to audit them: what was asked, how long it took, whether it succeeded.
