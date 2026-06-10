# Migrations (Phase 2 refactor)

This folder exists to match the target `policy-to-prod/infra/migrations` layout.

Source of truth (currently used by Alembic):
- `alembic.ini` at repo root
- `migrations/` at repo root

If you want to fully move migrations under `infra/migrations/`, we can do that next by:
1) Moving `migrations/` here
2) Updating `alembic.ini` `script_location`
3) Updating any CI/scripts that call `alembic`
