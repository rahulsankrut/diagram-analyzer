"""GCS adapter — thin async wrapper around google-cloud-storage."""

from __future__ import annotations

import asyncio
import types
from functools import partial
from typing import Any

# Lazy import so the module can be loaded (and mocked in tests) without the
# GCP SDK installed.  The SimpleNamespace stub keeps the module-level name
# ``storage`` patchable by unittest.mock.patch.
try:
    from google.cloud import storage  # type: ignore[import]
except ImportError:
    storage = types.SimpleNamespace(Client=None)  # type: ignore[assignment]


class GCSAdapter:
    """Thin wrapper around the GCS client for testable async I/O.

    All network calls are dispatched to a thread-pool executor so the async
    interface is non-blocking in an asyncio event loop.

    Args:
        bucket_name: Name of the GCS bucket (without ``gs://`` prefix).
        project_id: GCP project ID. Inferred from ADC when omitted.
        client: Injected ``storage.Client`` for testing. Created from ADC if omitted.
    """

    def __init__(
        self,
        bucket_name: str,
        project_id: str | None = None,
        client: Any = None,
    ) -> None:
        self._bucket_name = bucket_name
        self._client = client or storage.Client(project=project_id)

    async def upload_bytes(
        self,
        data: bytes,
        blob_name: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload raw bytes to GCS and return the ``gs://`` URI.

        Args:
            data: Raw bytes to upload.
            blob_name: Destination path inside the bucket.
            content_type: MIME type of the uploaded content.

        Returns:
            GCS URI string in the form ``gs://{bucket}/{blob_name}``.
        """
        loop = asyncio.get_running_loop()
        bucket = self._client.bucket(self._bucket_name)
        blob = bucket.blob(blob_name)
        await loop.run_in_executor(
            None,
            partial(blob.upload_from_string, data, content_type=content_type),
        )
        return f"gs://{self._bucket_name}/{blob_name}"

    async def download_bytes(self, blob_name: str) -> bytes:
        """Download a blob's contents as bytes.

        Args:
            blob_name: Path of the blob inside the bucket.

        Returns:
            Raw bytes of the blob's contents.
        """
        loop = asyncio.get_running_loop()
        bucket = self._client.bucket(self._bucket_name)
        blob = bucket.blob(blob_name)
        return await loop.run_in_executor(None, blob.download_as_bytes)  # type: ignore[return-value]

    def get_signed_url(self, blob_name: str, expiration_minutes: int = 60) -> str:
        """Generate a signed URL for temporary public access to a blob.

        Args:
            blob_name: Path of the blob inside the bucket.
            expiration_minutes: URL lifetime in minutes.

        Returns:
            HTTPS signed URL string.
        """
        import datetime

        bucket = self._client.bucket(self._bucket_name)
        blob = bucket.blob(blob_name)
        return blob.generate_signed_url(  # type: ignore[return-value]
            expiration=datetime.timedelta(minutes=expiration_minutes),
            method="GET",
        )
