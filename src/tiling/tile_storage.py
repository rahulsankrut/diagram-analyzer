"""Tile image storage backends — local filesystem and Google Cloud Storage."""

from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path

from PIL import Image

try:
    from google.cloud import storage as _gcs_storage
except ImportError:
    import types as _types

    _gcs_storage = _types.SimpleNamespace(Client=None)  # type: ignore[assignment]


class TileStorage(ABC):
    """Abstract base class for tile image storage backends.

    Both :class:`LocalStorage` and :class:`GCSStorage` implement this interface
    so that the tiling pipeline can swap backends without code changes.
    """

    @abstractmethod
    def save(self, tile_id: str, image: Image.Image) -> str:
        """Persist a tile image and return its storage path or URI.

        Args:
            tile_id: Unique tile identifier used to derive the filename/key.
            image: PIL Image to persist.

        Returns:
            Local filesystem path or GCS URI where the tile was written.
        """

    @abstractmethod
    def load(self, tile_id: str) -> Image.Image:
        """Load a previously saved tile image.

        Args:
            tile_id: Unique tile identifier.

        Returns:
            PIL Image loaded from storage.

        Raises:
            FileNotFoundError: If the tile does not exist in storage.
        """

    @abstractmethod
    def exists(self, tile_id: str) -> bool:
        """Check whether a tile has been saved to storage.

        Args:
            tile_id: Unique tile identifier.

        Returns:
            True if the tile exists, False otherwise.
        """


class LocalStorage(TileStorage):
    """Saves tile images to the local filesystem.

    Intended for development and testing.  Tile images are stored under
    *base_dir* using the pattern ``{tile_id}.{ext}``.

    Args:
        base_dir: Root directory for tile files.  Created automatically if it
            does not exist.
        fmt: Pillow format string for the output image (default ``"PNG"``).
    """

    def __init__(self, base_dir: Path | str, fmt: str = "PNG") -> None:
        self._base_dir = Path(base_dir)
        self._fmt = fmt.upper()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # TileStorage interface
    # ------------------------------------------------------------------

    def save(self, tile_id: str, image: Image.Image) -> str:
        """Save a tile image to disk.

        Args:
            tile_id: Unique tile identifier.
            image: PIL Image to save.

        Returns:
            Absolute path string of the saved file.
        """
        path = self._tile_path(tile_id)
        image.save(path, format=self._fmt)
        return str(path)

    def load(self, tile_id: str) -> Image.Image:
        """Load a tile image from disk.

        Args:
            tile_id: Unique tile identifier.

        Returns:
            PIL Image loaded from disk.

        Raises:
            FileNotFoundError: If the tile file does not exist.
        """
        path = self._tile_path(tile_id)
        if not path.exists():
            raise FileNotFoundError(f"Tile not found in local storage: {tile_id}")
        # .copy() so the file handle is closed before callers mutate the image.
        return Image.open(path).copy()

    def exists(self, tile_id: str) -> bool:
        """Check if a tile file exists on disk.

        Args:
            tile_id: Unique tile identifier.

        Returns:
            True if the file exists, False otherwise.
        """
        return self._tile_path(tile_id).exists()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _tile_path(self, tile_id: str) -> Path:
        """Derive the local filesystem path for a tile.

        Args:
            tile_id: Unique tile identifier.

        Returns:
            :class:`Path` for the tile file.
        """
        return self._base_dir / f"{tile_id}.{self._fmt.lower()}"


class GCSStorage(TileStorage):
    """Saves tile images to Google Cloud Storage.

    Intended for production deployments.  Tile images are stored as blobs at
    ``{prefix}{tile_id}.{ext}`` inside the given GCS bucket.

    If the ``google-cloud-storage`` SDK is not installed, or cannot be
    initialised, all methods raise :class:`RuntimeError`.

    Args:
        bucket_name: GCS bucket name.
        prefix: Blob key prefix appended before the tile filename (default
            ``"tiles/"``).
        fmt: Pillow format string for the output image (default ``"PNG"``).
    """

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "tiles/",
        fmt: str = "PNG",
    ) -> None:
        self._bucket_name = bucket_name
        self._prefix = prefix
        self._fmt = fmt.upper()
        if _gcs_storage.Client is not None:
            client = _gcs_storage.Client()
            self._bucket = client.bucket(bucket_name)
        else:
            self._bucket = None

    # ------------------------------------------------------------------
    # TileStorage interface
    # ------------------------------------------------------------------

    def save(self, tile_id: str, image: Image.Image) -> str:
        """Upload a tile image to GCS.

        Args:
            tile_id: Unique tile identifier.
            image: PIL Image to upload.

        Returns:
            GCS URI of the uploaded blob (``gs://{bucket}/{prefix}{tile_id}.ext``).

        Raises:
            RuntimeError: If the google-cloud-storage SDK is not installed.
        """
        self._require_bucket()
        buf = BytesIO()
        image.save(buf, format=self._fmt)
        blob_name = self._blob_name(tile_id)
        blob = self._bucket.blob(blob_name)  # type: ignore[union-attr]
        blob.upload_from_string(buf.getvalue(), content_type=f"image/{self._fmt.lower()}")
        return f"gs://{self._bucket_name}/{blob_name}"

    def load(self, tile_id: str) -> Image.Image:
        """Download a tile image from GCS.

        Args:
            tile_id: Unique tile identifier.

        Returns:
            PIL Image downloaded from GCS.

        Raises:
            RuntimeError: If the google-cloud-storage SDK is not installed.
            FileNotFoundError: If the blob does not exist in the bucket.
        """
        self._require_bucket()
        blob = self._bucket.blob(self._blob_name(tile_id))  # type: ignore[union-attr]
        if not blob.exists():
            raise FileNotFoundError(f"Tile not found in GCS: {tile_id}")
        return Image.open(BytesIO(blob.download_as_bytes()))

    def exists(self, tile_id: str) -> bool:
        """Check whether a tile blob exists in GCS.

        Args:
            tile_id: Unique tile identifier.

        Returns:
            True if the blob exists, False otherwise.

        Raises:
            RuntimeError: If the google-cloud-storage SDK is not installed.
        """
        self._require_bucket()
        blob = self._bucket.blob(self._blob_name(tile_id))  # type: ignore[union-attr]
        return bool(blob.exists())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _blob_name(self, tile_id: str) -> str:
        return f"{self._prefix}{tile_id}.{self._fmt.lower()}"

    def _require_bucket(self) -> None:
        if self._bucket is None:
            raise RuntimeError(
                "google-cloud-storage SDK is not available. "
                "Install it with: pip install google-cloud-storage"
            )
