# ADR-003: SQLite WAL persistence

Status: Accepted

MVP uses SQLite with WAL, foreign keys, explicit transactions, and migrations. Repository
interfaces keep a future PostgreSQL implementation possible without adding it now.

