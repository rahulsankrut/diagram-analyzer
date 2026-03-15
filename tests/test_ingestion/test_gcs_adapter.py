"""Unit tests for GCSAdapter."""

from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.gcs_adapter import GCSAdapter


class TestGCSAdapter:
    def test_upload_calls_upload_from_string(
        self, mock_gcs_client: MagicMock
    ) -> None:
        adapter = GCSAdapter(bucket_name="test-bucket", client=mock_gcs_client)
        import asyncio

        asyncio.run(adapter.upload_bytes(b"data", "path/to/blob.png", "image/png"))

        mock_gcs_client.bucket.assert_called_once_with("test-bucket")
        blob = mock_gcs_client.bucket.return_value.blob.return_value
        blob.upload_from_string.assert_called_once_with(b"data", content_type="image/png")

    async def test_upload_returns_gcs_uri(self, mock_gcs_client: MagicMock) -> None:
        adapter = GCSAdapter(bucket_name="my-bucket", client=mock_gcs_client)
        uri = await adapter.upload_bytes(b"bytes", "diagrams/test.png")
        assert uri == "gs://my-bucket/diagrams/test.png"

    async def test_download_calls_download_as_bytes(
        self, mock_gcs_client: MagicMock
    ) -> None:
        adapter = GCSAdapter(bucket_name="test-bucket", client=mock_gcs_client)
        result = await adapter.download_bytes("some/blob.png")
        assert result == b"fake-image-bytes"
        blob = mock_gcs_client.bucket.return_value.blob.return_value
        blob.download_as_bytes.assert_called_once()

    def test_constructor_creates_client_from_adc_when_none_given(self) -> None:
        with patch("src.ingestion.gcs_adapter.storage.Client") as mock_cls:
            GCSAdapter(bucket_name="b", project_id="my-project")
            mock_cls.assert_called_once_with(project="my-project")

    def test_injected_client_not_recreated(self, mock_gcs_client: MagicMock) -> None:
        with patch("src.ingestion.gcs_adapter.storage.Client") as mock_cls:
            GCSAdapter(bucket_name="b", client=mock_gcs_client)
            mock_cls.assert_not_called()
