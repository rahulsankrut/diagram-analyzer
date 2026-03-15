"""Tests for tile storage backends — LocalStorage and GCSStorage."""

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.tiling.tile_storage import GCSStorage, LocalStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    return tmp_path / "tiles"


@pytest.fixture
def local_storage(storage_dir: Path) -> LocalStorage:
    return LocalStorage(storage_dir)


@pytest.fixture
def sample_tile_image() -> Image.Image:
    """A small RGB image with a distinctive colour for pixel-level verification."""
    return Image.new("RGB", (256, 256), color=(128, 64, 192))


def _encode_png(image: Image.Image) -> bytes:
    """Encode *image* to PNG bytes (used to fake GCS download_as_bytes)."""
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# LocalStorage
# ---------------------------------------------------------------------------


class TestLocalStorage:
    def test_save_returns_path_string(
        self, local_storage: LocalStorage, sample_tile_image: Image.Image
    ) -> None:
        path = local_storage.save("tile-001", sample_tile_image)
        assert isinstance(path, str)
        assert "tile-001" in path

    def test_save_creates_png_file(
        self,
        local_storage: LocalStorage,
        storage_dir: Path,
        sample_tile_image: Image.Image,
    ) -> None:
        local_storage.save("tile-001", sample_tile_image)
        assert (storage_dir / "tile-001.png").exists()

    def test_load_roundtrip_preserves_size(
        self, local_storage: LocalStorage, sample_tile_image: Image.Image
    ) -> None:
        local_storage.save("tile-002", sample_tile_image)
        loaded = local_storage.load("tile-002")
        assert loaded.size == sample_tile_image.size

    def test_load_roundtrip_preserves_pixel_values(
        self, local_storage: LocalStorage
    ) -> None:
        """Verify that a specific pixel colour survives a save/load cycle."""
        img = Image.new("RGB", (4, 4), color=(255, 0, 0))
        local_storage.save("red-tile", img)
        loaded = local_storage.load("red-tile")
        assert loaded.getpixel((0, 0)) == (255, 0, 0)

    def test_exists_true_after_save(
        self, local_storage: LocalStorage, sample_tile_image: Image.Image
    ) -> None:
        local_storage.save("tile-003", sample_tile_image)
        assert local_storage.exists("tile-003") is True

    def test_exists_false_before_save(self, local_storage: LocalStorage) -> None:
        assert local_storage.exists("never-saved") is False

    def test_load_missing_raises_file_not_found(
        self, local_storage: LocalStorage
    ) -> None:
        with pytest.raises(FileNotFoundError):
            local_storage.load("missing-tile")

    def test_constructor_creates_base_dir(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "nested" / "deep" / "tiles"
        LocalStorage(new_dir)
        assert new_dir.exists()

    def test_multiple_tiles_stored_independently(
        self, local_storage: LocalStorage
    ) -> None:
        img_a = Image.new("RGB", (64, 64), color=(0, 255, 0))
        img_b = Image.new("RGB", (32, 32), color=(0, 0, 255))
        local_storage.save("tile-a", img_a)
        local_storage.save("tile-b", img_b)
        assert local_storage.load("tile-a").size == (64, 64)
        assert local_storage.load("tile-b").size == (32, 32)

    def test_overwrite_existing_tile(
        self, local_storage: LocalStorage
    ) -> None:
        """Saving a tile with the same ID overwrites the previous file."""
        img_v1 = Image.new("RGB", (64, 64), color=(255, 0, 0))
        img_v2 = Image.new("RGB", (64, 64), color=(0, 255, 0))
        local_storage.save("tile-overwrite", img_v1)
        local_storage.save("tile-overwrite", img_v2)
        loaded = local_storage.load("tile-overwrite")
        assert loaded.getpixel((0, 0)) == (0, 255, 0)

    def test_string_path_accepted(self, tmp_path: Path, sample_tile_image: Image.Image) -> None:
        """LocalStorage should accept a plain string as base_dir."""
        storage = LocalStorage(str(tmp_path / "str_tiles"))
        storage.save("tile-str", sample_tile_image)
        assert storage.exists("tile-str")


# ---------------------------------------------------------------------------
# GCSStorage — with mocked GCS client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bucket(sample_tile_image: Image.Image) -> MagicMock:
    """A fully-wired mock GCS bucket whose blob returns downloadable PNG bytes."""
    bucket = MagicMock()
    blob = MagicMock()
    blob.exists.return_value = True
    blob.download_as_bytes.return_value = _encode_png(sample_tile_image)
    bucket.blob.return_value = blob
    return bucket


class TestGCSStorage:
    def test_save_returns_gs_uri(
        self, mock_bucket: MagicMock, sample_tile_image: Image.Image
    ) -> None:
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client.return_value.bucket.return_value = mock_bucket
            storage = GCSStorage("my-bucket", prefix="tiles/")
        uri = storage.save("tile-abc", sample_tile_image)
        assert uri.startswith("gs://my-bucket/")
        assert "tile-abc" in uri

    def test_save_calls_upload_from_string(
        self, mock_bucket: MagicMock, sample_tile_image: Image.Image
    ) -> None:
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client.return_value.bucket.return_value = mock_bucket
            storage = GCSStorage("my-bucket")
        storage.save("tile-001", sample_tile_image)
        blob = mock_bucket.blob.return_value
        blob.upload_from_string.assert_called_once()

    def test_load_returns_image_with_correct_size(
        self, mock_bucket: MagicMock, sample_tile_image: Image.Image
    ) -> None:
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client.return_value.bucket.return_value = mock_bucket
            storage = GCSStorage("my-bucket")
        img = storage.load("tile-001")
        assert img.size == sample_tile_image.size

    def test_load_missing_raises_file_not_found(
        self, mock_bucket: MagicMock
    ) -> None:
        mock_bucket.blob.return_value.exists.return_value = False
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client.return_value.bucket.return_value = mock_bucket
            storage = GCSStorage("my-bucket")
        with pytest.raises(FileNotFoundError):
            storage.load("absent-tile")

    def test_exists_delegates_to_blob(self, mock_bucket: MagicMock) -> None:
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client.return_value.bucket.return_value = mock_bucket
            storage = GCSStorage("my-bucket")
        assert storage.exists("tile-001") is True

    def test_exists_false_when_blob_absent(self, mock_bucket: MagicMock) -> None:
        mock_bucket.blob.return_value.exists.return_value = False
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client.return_value.bucket.return_value = mock_bucket
            storage = GCSStorage("my-bucket")
        assert storage.exists("absent") is False

    def test_no_sdk_save_raises_runtime_error(
        self, sample_tile_image: Image.Image
    ) -> None:
        """save() must raise RuntimeError when the GCS SDK is unavailable."""
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client = None
            storage = GCSStorage("test-bucket")
        with pytest.raises(RuntimeError, match="google-cloud-storage"):
            storage.save("tile-x", sample_tile_image)

    def test_no_sdk_load_raises_runtime_error(self) -> None:
        """load() must raise RuntimeError when the GCS SDK is unavailable."""
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client = None
            storage = GCSStorage("test-bucket")
        with pytest.raises(RuntimeError, match="google-cloud-storage"):
            storage.load("tile-x")

    def test_no_sdk_exists_raises_runtime_error(self) -> None:
        """exists() must raise RuntimeError when the GCS SDK is unavailable."""
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client = None
            storage = GCSStorage("test-bucket")
        with pytest.raises(RuntimeError, match="google-cloud-storage"):
            storage.exists("tile-x")

    def test_blob_name_includes_prefix(
        self, mock_bucket: MagicMock, sample_tile_image: Image.Image
    ) -> None:
        """GCS blob names must include the configured prefix."""
        with patch("src.tiling.tile_storage._gcs_storage") as mock_gcs:
            mock_gcs.Client.return_value.bucket.return_value = mock_bucket
            storage = GCSStorage("my-bucket", prefix="diagram/tiles/")
        storage.save("tile-prefix-test", sample_tile_image)
        mock_bucket.blob.assert_called_with("diagram/tiles/tile-prefix-test.png")
