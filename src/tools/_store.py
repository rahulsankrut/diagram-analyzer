"""Data access interface for LLM agent tool functions.

``DiagramStore`` is the single seam between tool functions and the underlying
storage backends (Firestore, GCS, local filesystem).  In production a concrete
implementation is wired in once at application startup via
:func:`configure_store`.  In tests the store is replaced with a mock.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image

from src.models.diagram import DiagramMetadata
from src.models.tiling import Tile, TilePyramid


class DiagramStore(ABC):
    """Abstract data access interface used by all tool functions.

    Concrete implementations back this with Firestore + GCS (production) or
    in-memory mocks (tests).  The active store is set once at startup via
    :func:`configure_store` and retrieved by tool functions via
    :func:`get_store`.
    """

    @abstractmethod
    def get_metadata(self, diagram_id: str) -> DiagramMetadata | None:
        """Return DiagramMetadata for *diagram_id*, or ``None`` if not found.

        Args:
            diagram_id: UUID of the target diagram.

        Returns:
            Populated :class:`DiagramMetadata` or ``None``.
        """

    @abstractmethod
    def get_pyramid(self, diagram_id: str) -> TilePyramid | None:
        """Return TilePyramid for *diagram_id*, or ``None`` if tiling has not run.

        Args:
            diagram_id: UUID of the target diagram.

        Returns:
            :class:`TilePyramid` or ``None``.
        """

    @abstractmethod
    def load_tile_image(self, tile: Tile) -> Image.Image | None:
        """Load the PIL Image for *tile*, or ``None`` if the image is not stored.

        Args:
            tile: Tile whose image should be loaded.

        Returns:
            PIL Image or ``None``.
        """

    @abstractmethod
    def load_original_image(self, diagram_id: str) -> Image.Image | None:
        """Load the full-resolution PIL Image for *diagram_id*.

        Args:
            diagram_id: UUID of the target diagram.

        Returns:
            PIL Image or ``None`` when the source file is unavailable.
        """


_instance: DiagramStore | None = None


def configure_store(store: DiagramStore) -> None:
    """Set the module-level :class:`DiagramStore` used by all tool functions.

    Must be called once at application startup before any tool is invoked.
    In tests, call this with a mock object to inject a fake store.

    Args:
        store: The concrete :class:`DiagramStore` to activate.
    """
    global _instance
    _instance = store


def get_store() -> DiagramStore:
    """Return the active :class:`DiagramStore`.

    Returns:
        The configured store.

    Raises:
        RuntimeError: If :func:`configure_store` has not been called.
    """
    if _instance is None:
        raise RuntimeError(
            "DiagramStore is not configured. "
            "Call src.tools._store.configure_store(store) before invoking tools."
        )
    return _instance
