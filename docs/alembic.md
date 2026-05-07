# Alembic workflow 
Alembic is database schema migration tool for Python apps using SQLAlchemy
Similar to ```git``` for database schema

Instead of manually running SQL like
```ALTER TABLE users ADD COLUMN age INT;```

We write Python script/files to version it
By doing this:
- Version-controlled schema changes (update, removal)
- SQLAlchemy integration: reduce SQL manual work
- We can roll forward or backward 
- Help engineers to collaborate and evolve schema safely
- Keep environmens(dev, staging, prod) in sync
- Automation-friendly: fits into CI/CD, deploy schema+ app together

## Cases where Alembic cannot handle well:
**Alemic cannot**:
- Cannot prevent long locks: production outage
- Cannot avoid downtime automatically
- Cannot handle large-table migrations gracefully
- For large-scale/high traffic systems: which requires
    - Schema changes require zero-downtime
    - Backfills
    - Feature flags
- Complex data migrations:
    - Autogenerate can be dangerous: incorrect SQL; blind trust
    - 

