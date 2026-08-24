# SQLite migrations

The MVP bootstraps migration version 1 transactionally in `repository.SCHEMA` and records it in
`schema_migrations`. Future schema changes must add monotonically numbered migration modules here;
they must never edit a database whose recorded version is newer than the running package.

