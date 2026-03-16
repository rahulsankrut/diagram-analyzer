"""Top-level pipeline orchestrator for the CAD Diagram Analyzer.

Ties ingestion → preprocessing → tiling → agent into a single entry point.
:class:`InMemoryDiagramStore` is the concrete :class:`~src.tools._store.DiagramStore`
used for local development; production deployments swap in a Firestore + GCS
backed implementation without changing any other code.

Typical one-shot usage::

    from src.orchestrator import Orchestrator

    orch = Orchestrator.create_local()
    response = orch.analyze("./schematic.png", "What components are on this board?")
    print(response)
"""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from src.models.diagram import DiagramMetadata
from src.models.tiling import Tile, TilePyramid
from src.tiling.tile_generator import TileGenerator, TilingConfig
from src.tiling.tile_storage import LocalStorage, TileStorage
from src.tools._store import DiagramStore, configure_store

logger = logging.getLogger(__name__)

_DEFAULT_TILE_DIR = Path("/tmp/cad-diagram-analyzer/tiles")


# ---------------------------------------------------------------------------
# Concrete in-memory DiagramStore
# ---------------------------------------------------------------------------


class InMemoryDiagramStore(DiagramStore):
    """Concrete :class:`~src.tools._store.DiagramStore` backed by Python dicts.

    Suitable for local development, integration tests, and single-process
    servers that keep all data in RAM.  Not suitable for multi-process or
    persistent deployments.

    Beyond the read-only :class:`~src.tools._store.DiagramStore` ABC methods,
    this class exposes ``put_*`` write methods used by :class:`Orchestrator`
    during ingestion.
    """

    def __init__(self) -> None:
        self._metadata: dict[str, DiagramMetadata] = {}
        self._pyramids: dict[str, TilePyramid] = {}
        self._tile_images: dict[str, Image.Image] = {}
        self._original_images: dict[str, Image.Image] = {}

    # ------------------------------------------------------------------
    # DiagramStore read interface
    # ------------------------------------------------------------------

    def get_metadata(self, diagram_id: str) -> DiagramMetadata | None:
        """Return stored DiagramMetadata for *diagram_id*, or ``None``."""
        return self._metadata.get(diagram_id)

    def get_pyramid(self, diagram_id: str) -> TilePyramid | None:
        """Return stored TilePyramid for *diagram_id*, or ``None``."""
        return self._pyramids.get(diagram_id)

    def load_tile_image(self, tile: Tile) -> Image.Image | None:
        """Return the cached PIL Image for *tile*, or ``None``."""
        return self._tile_images.get(tile.tile_id)

    def load_original_image(self, diagram_id: str) -> Image.Image | None:
        """Return the cached original PIL Image, or ``None``."""
        return self._original_images.get(diagram_id)

    # ------------------------------------------------------------------
    # Write methods (used by Orchestrator during ingestion)
    # ------------------------------------------------------------------

    def put_metadata(self, metadata: DiagramMetadata) -> None:
        """Store or overwrite metadata for ``metadata.diagram_id``.

        Args:
            metadata: Populated :class:`~src.models.DiagramMetadata`.
        """
        self._metadata[metadata.diagram_id] = metadata

    def put_pyramid(self, pyramid: TilePyramid) -> None:
        """Store or overwrite the tile pyramid for ``pyramid.diagram_id``.

        Args:
            pyramid: Generated :class:`~src.models.TilePyramid`.
        """
        self._pyramids[pyramid.diagram_id] = pyramid

    def put_tile_image(self, tile_id: str, image: Image.Image) -> None:
        """Cache a tile's PIL Image for fast tool access.

        Args:
            tile_id: Unique tile identifier.
            image: Tile image to cache.
        """
        self._tile_images[tile_id] = image

    def put_original_image(self, diagram_id: str, image: Image.Image) -> None:
        """Cache the full-resolution PIL Image for crop-based tools.

        Args:
            diagram_id: UUID of the diagram.
            image: Full-resolution PIL Image to cache.
        """
        self._original_images[diagram_id] = image

    @property
    def diagram_count(self) -> int:
        """Number of diagrams currently held in the store."""
        return len(self._metadata)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Ties the full CAD analysis pipeline together.

    Accepts a raw image upload (path or bytes), runs preprocessing + tiling,
    writes every artefact into the configured store, and optionally queries the
    ADK agent.  All collaborators are constructor-injectable so tests can
    supply lightweight stubs without touching real GCP services.

    Args:
        preprocessing_pipeline: Configured :class:`~src.preprocessing.pipeline.PreprocessingPipeline`
            (or any mock with ``async run(image) -> DiagramMetadata``).
        tile_storage: :class:`~src.tiling.tile_storage.TileStorage` backend.
        store: Writable :class:`InMemoryDiagramStore` that tools will read from.
        agent: Configured :class:`~src.agent.cad_agent.CADAnalysisAgent`,
            or ``None`` for ingest-only mode.
        tiling_config: Optional :class:`~src.tiling.tile_generator.TilingConfig`
            override.
    """

    def __init__(
        self,
        *,
        preprocessing_pipeline: Any,
        tile_storage: TileStorage,
        store: InMemoryDiagramStore,
        agent: Any = None,
        tiling_config: TilingConfig | None = None,
    ) -> None:
        self._pipeline = preprocessing_pipeline
        self._tile_storage = tile_storage
        self._store = store
        self._agent = agent
        self._tiling_config = tiling_config or TilingConfig()
        # Wire the store so all tool functions can reach it immediately.
        configure_store(store)

    # ------------------------------------------------------------------
    # Core async pipeline
    # ------------------------------------------------------------------

    async def ingest(
        self,
        source: Path | bytes,
        filename: str = "upload.png",
    ) -> str:
        """Ingest one diagram image through the full pre-processing pipeline.

        Steps:

        1. Decode *source* to a PIL Image.
        2. Run OCR + CV + title block extraction via the preprocessing pipeline.
        3. Generate the multi-resolution tile pyramid.
        4. Persist every tile via :attr:`tile_storage`.
        5. Write metadata, pyramid, and original image into the store.

        Args:
            source: Local file :class:`~pathlib.Path` or raw image ``bytes``.
            filename: Human-readable filename stored in metadata; inferred
                automatically when *source* is a :class:`~pathlib.Path`.

        Returns:
            The UUID ``diagram_id`` assigned during preprocessing.
        """
        pil_image, filename = _load_image(source, filename)

        raw_metadata: DiagramMetadata = await self._pipeline.run(pil_image)
        # Use model_copy so we never mutate a shared fixture/mock return value.
        metadata = raw_metadata.model_copy(update={"source_filename": filename})
        diagram_id = metadata.diagram_id

        pyramid = self._generate_and_store_tiles(pil_image, metadata)

        self._store.put_metadata(metadata)
        self._store.put_pyramid(pyramid)
        self._store.put_original_image(diagram_id, pil_image)

        logger.info(
            "Ingested diagram %s — %d tiles, source: %s",
            diagram_id,
            len(pyramid.tiles),
            filename,
        )
        return diagram_id

    async def ingest_and_analyze(
        self,
        source: Path | bytes,
        query: str,
        filename: str = "upload.png",
    ) -> str:
        """Ingest a diagram then immediately query the agent.

        Args:
            source: Local file path or raw image bytes.
            query: Natural-language question for the agent.
            filename: Hint for the diagram filename; inferred when *source*
                is a :class:`~pathlib.Path`.

        Returns:
            Agent's textual analysis response.

        Raises:
            RuntimeError: If no agent was provided at construction time.
        """
        if self._agent is None:
            raise RuntimeError(
                "No agent configured. Pass agent= to Orchestrator or use "
                "Orchestrator.create_local() which builds one automatically."
            )
        diagram_id = await self.ingest(source, filename)
        return self._agent.analyze(diagram_id, query)

    # ------------------------------------------------------------------
    # Sync convenience entry point (CLI / quick testing)
    # ------------------------------------------------------------------

    def analyze(self, image_path: Path | str, query: str) -> str:
        """One-shot convenience method: ingest + analyze, synchronously.

        Intended for CLI scripts and interactive testing.  Internally calls
        :meth:`ingest_and_analyze` via :func:`asyncio.run`, so this method
        **must not** be called from inside an already-running event loop.

        Args:
            image_path: Path to a local diagram image (PNG, TIFF, …).
            query: Natural-language question for the agent.

        Returns:
            Agent's textual analysis response.
        """
        path = Path(image_path)
        return asyncio.run(
            self.ingest_and_analyze(path, query, filename=path.name)
        )

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def create_local(
        cls,
        tile_dir: Path | str | None = None,
        model: str = "gemini-2.5-flash",
        *,
        _agent_cls: Any = None,
        _runner_cls: Any = None,
        _types_mod: Any = None,
    ) -> "Orchestrator":
        """Build an :class:`Orchestrator` wired with local-filesystem defaults.

        Does **not** require GCP credentials: uses no-op OCR and CV stubs so
        the pipeline runs end-to-end on a developer laptop.  Tiles are written
        to *tile_dir* on disk and metadata is held in memory.

        Args:
            tile_dir: Directory for tile image files.  Defaults to
                ``/tmp/cad-diagram-analyzer/tiles``.
            model: Gemini model ID forwarded to :class:`~src.agent.cad_agent.CADAnalysisAgent`.
            _agent_cls/_runner_cls/_types_mod: ADK dependency-injection seams
                for unit tests (see :class:`~src.agent.cad_agent.CADAnalysisAgent`).

        Returns:
            Fully wired :class:`Orchestrator`.
        """
        from src.preprocessing.pipeline import PreprocessingPipeline
        from src.agent.cad_agent import CADAnalysisAgent

        pipeline = PreprocessingPipeline(
            ocr_extractor=_NoOpOCR(),  # type: ignore[arg-type]
            cv_pipeline=_NoOpCV(),  # type: ignore[arg-type]
        )
        storage = LocalStorage(tile_dir or _DEFAULT_TILE_DIR)
        store = InMemoryDiagramStore()

        try:
            agent: Any = CADAnalysisAgent(
                model,
                _agent_cls=_agent_cls,
                _runner_cls=_runner_cls,
                _types_mod=_types_mod,
            )
        except RuntimeError:
            agent = None

        return cls(
            preprocessing_pipeline=pipeline,
            tile_storage=storage,
            store=store,
            agent=agent,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_and_store_tiles(
        self,
        pil_image: Image.Image,
        metadata: DiagramMetadata,
    ) -> TilePyramid:
        """Generate the tile pyramid and persist every tile image.

        Args:
            pil_image: Full-resolution source image.
            metadata: Pre-processed diagram metadata.

        Returns:
            :class:`~src.models.TilePyramid` with ``image_path`` populated on
            every tile.
        """
        generator = TileGenerator(pil_image, metadata, self._tiling_config)
        pyramid = generator.generate()
        for tile in pyramid.tiles:
            tile_image = generator.get_tile_image(tile)
            saved_path = self._tile_storage.save(tile.tile_id, tile_image)
            tile.image_path = saved_path
            self._store.put_tile_image(tile.tile_id, tile_image)
        return pyramid


# ---------------------------------------------------------------------------
# Private no-op stubs used by create_local()
# ---------------------------------------------------------------------------


def _load_image(
    source: Path | bytes,
    filename: str,
) -> tuple[Image.Image, str]:
    """Open *source* as a PIL Image and return ``(image, filename)``.

    Args:
        source: File path or raw image bytes.
        filename: Fallback display name when *source* is ``bytes``.

    Returns:
        Tuple of (RGB PIL Image, resolved filename string).

    Raises:
        TypeError: If *source* is neither ``Path``/``str`` nor ``bytes``.
    """
    if isinstance(source, bytes):
        return Image.open(BytesIO(source)).convert("RGB"), filename
    path = Path(source)
    return Image.open(path).convert("RGB"), path.name


class _NoOpOCR:
    """Stub OCR extractor that returns an empty label list without GCP calls."""

    async def extract(self, image: Any) -> list:  # noqa: ARG002
        return []


class _NoOpCV:
    """Stub CV pipeline that returns an empty CVResult without OpenCV calls."""

    def run(self, image: Any, text_labels: Any = None) -> Any:  # noqa: ARG002
        from src.models.cv import CVResult

        return CVResult()
