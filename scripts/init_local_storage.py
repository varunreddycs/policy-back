from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        return


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_raw_container_name() -> str:
    return os.getenv("AZURE_POLICY_RAW_CONTAINER", "policy-raw")


def main() -> None:
    _load_dotenv_if_present()

    raw_container = _get_raw_container_name()
    extracted_container = os.getenv("AZURE_POLICY_EXTRACTED_CONTAINER", "policy-extracted")
    queue_name = _require_env("AZURE_POLICY_EXTRACTION_QUEUE_NAME")

    account_name = _require_env("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = _require_env("AZURE_STORAGE_ACCOUNT_KEY")

    blob_account_url = _require_env("AZURE_STORAGE_ACCOUNT_URL")
    queue_account_url = _require_env("AZURE_STORAGE_QUEUE_ACCOUNT_URL")

    api_version = os.getenv("AZURE_STORAGE_API_VERSION")

    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import BlobServiceClient
    from azure.storage.queue import QueueServiceClient

    blob_svc = BlobServiceClient(account_url=blob_account_url, credential=account_key, api_version=api_version)
    queue_svc = QueueServiceClient(account_url=queue_account_url, credential=account_key, api_version=api_version)

    created = []

    for container in [raw_container, extracted_container]:
        try:
            blob_svc.create_container(container)
            created.append(f"container:{container}")
        except ResourceExistsError:
            pass

    try:
        queue_svc.create_queue(queue_name)
        created.append(f"queue:{queue_name}")
    except ResourceExistsError:
        pass

    print(
        "local_storage.ready",
        {
            "account": account_name,
            "blob_url": blob_account_url,
            "queue_url": queue_account_url,
            "raw_container": raw_container,
            "extracted_container": extracted_container,
            "queue": queue_name,
            "created": created,
        },
    )


if __name__ == "__main__":
    main()
