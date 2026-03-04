from __future__ import annotations

import os
import uuid
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.db.models.policy_models import Tenant  # noqa: E402
from packages.db.session import get_sessionmaker  # noqa: E402


def _load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        return


def _env_uuid(name: str, default: str) -> uuid.UUID:
    value = os.getenv(name) or default
    return uuid.UUID(value)


def main() -> None:
    _load_dotenv_if_present()

    tenant_id = _env_uuid("LOCAL_TENANT_ID", "00000000-0000-0000-0000-000000000001")
    tenant_slug = os.getenv("LOCAL_TENANT_SLUG", "local")
    tenant_name = os.getenv("LOCAL_TENANT_NAME", "Local Tenant")

    SessionLocal = get_sessionmaker()
    session = SessionLocal()
    try:
        existing = session.get(Tenant, tenant_id)
        if existing is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    slug=tenant_slug,
                    name=tenant_name,
                    is_active=True,
                )
            )
            session.commit()
            print("local_db.seeded", {"tenant_id": str(tenant_id), "slug": tenant_slug})
        else:
            print("local_db.already_seeded", {"tenant_id": str(tenant_id), "slug": existing.slug})
    finally:
        session.close()


if __name__ == "__main__":
    main()
