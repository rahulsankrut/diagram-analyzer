"""Local development server for the CAD Diagram Analyzer.

Exposes two HTTP endpoints:

* ``POST /analyze`` — run the ADK agent against a pre-processed diagram.
* ``POST /ingest``  — upload a raw image, run OCR + CV + tiling, return its
  diagram ID so subsequent ``/analyze`` calls can reference it.

FastAPI and uvicorn are optional at import time so the module can be imported
in test environments that don't have those packages installed.  The ``app``
object is ``None`` in that case and the ``run_server()`` helper will raise a
clear error.

Start the server locally::

    python -m src.agent.server
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel

# Load .env from project root before any GCP SDK picks up credentials/config.
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Ensure google-genai SDK routes through Vertex AI (ADC) instead of API key.
# These mirror the values in .env but are set explicitly as a safety net.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT_ID", ""))
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.environ.get("VERTEX_AI_LOCATION", "us-central1"))

# Suppress noisy SDK warnings that look like errors but are informational.
# "there are non-text parts in the response" fires on every tool call — expected.
import logging as _logging
import warnings
warnings.filterwarnings("ignore", message="there are non-text parts in the response")
_logging.getLogger("google_genai.types").setLevel(_logging.ERROR)
_logging.getLogger("google.adk").setLevel(_logging.WARNING)

# ---------------------------------------------------------------------------
# Lazy FastAPI / uvicorn imports
# ---------------------------------------------------------------------------

try:
    from fastapi import FastAPI, File, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    import uvicorn

    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover — only hit when SDK not installed
    _FASTAPI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Request / response Pydantic models (always importable)
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """Request body for POST /analyze.

    Attributes:
        diagram_id: UUID of a previously ingested diagram.
        query: Natural-language question or task for the agent.
        user_id: Opaque caller identifier forwarded to the ADK session service.
    """

    diagram_id: str
    query: str
    user_id: str = "default-user"


class AnalyzeResponse(BaseModel):
    """Response body for POST /analyze.

    Attributes:
        diagram_id: Echoed from the request.
        query: Echoed from the request.
        response: Final text produced by the agent.
    """

    diagram_id: str
    query: str
    response: str


class IngestResponse(BaseModel):
    """Response body for POST /ingest.

    Attributes:
        diagram_id: UUID assigned to the newly ingested diagram.
        success: ``True`` when all pipeline stages completed without error.
        error_message: Human-readable detail when ``success`` is ``False``.
    """

    diagram_id: str
    success: bool
    error_message: str | None = None


# ---------------------------------------------------------------------------
# App factory — deferred so ``app`` is only built when FastAPI is present
# ---------------------------------------------------------------------------


def create_app() -> Any:
    """Build and return the FastAPI application.

    Returns:
        Configured :class:`fastapi.FastAPI` instance.

    Raises:
        RuntimeError: If ``fastapi`` is not installed.
    """
    if not _FASTAPI_AVAILABLE:
        raise RuntimeError(
            "fastapi is not installed. Run: pip install 'fastapi[standard]'"
        )

    _app = FastAPI(
        title="CAD Diagram Analyzer",
        description="Agentic analysis of electrical schematics and P&IDs.",
        version="0.1.0",
    )

    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Single orchestrator instance shared across all requests.
    _orchestrator = _build_orchestrator()

    # ------------------------------------------------------------------
    # POST /ingest
    # ------------------------------------------------------------------

    @_app.post("/ingest", response_model=IngestResponse)
    async def ingest(file: UploadFile = File(...)) -> IngestResponse:
        """Ingest a diagram image: OCR + CV + tiling → diagram_id.

        Accepts any image format supported by Pillow (PNG, TIFF, JPEG, …).

        Args:
            file: Uploaded image file.

        Returns:
            :class:`IngestResponse` with the assigned ``diagram_id``.
        """
        try:
            raw = await file.read()
            diagram_id = await _orchestrator.ingest(
                raw,
                filename=file.filename or "upload.png",
            )
        except Exception as exc:  # noqa: BLE001
            return IngestResponse(
                diagram_id="",
                success=False,
                error_message=str(exc),
            )

        return IngestResponse(diagram_id=diagram_id, success=True)

    # ------------------------------------------------------------------
    # POST /analyze
    # ------------------------------------------------------------------

    @_app.post("/analyze", response_model=AnalyzeResponse)
    async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
        """Run the ADK agent against a pre-processed diagram.

        Args:
            request: Body containing ``diagram_id`` and ``query``.

        Returns:
            :class:`AnalyzeResponse` with the agent's textual analysis.

        Raises:
            HTTPException 404: When the diagram is not found in the store.
        """
        from src.tools._store import get_store

        store = get_store()
        if store.get_metadata(request.diagram_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Diagram not found: {request.diagram_id}",
            )
        if _orchestrator._agent is None:
            raise HTTPException(
                status_code=503,
                detail="Agent not configured. Check Vertex AI credentials.",
            )
        try:
            text = await _orchestrator._agent.analyze_async(
                request.diagram_id,
                request.query,
                user_id=request.user_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return AnalyzeResponse(
            diagram_id=request.diagram_id,
            query=request.query,
            response=text,
        )

    # Mount static files last so API routes take priority.
    _static_dir = Path(__file__).parent.parent / "static"
    if _static_dir.is_dir():
        _app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")

    return _app


# ---------------------------------------------------------------------------
# Orchestrator factory
# ---------------------------------------------------------------------------

import logging as _logging

_log = _logging.getLogger(__name__)


def _build_orchestrator() -> Any:
    """Build an Orchestrator wired with real GCP services when available.

    Tries to use Document AI OCR + OpenCV CV pipeline so the agent receives
    real structured data. Falls back to no-op stubs if credentials or the SDK
    are not available (e.g. pure offline testing).
    """
    from src.agent.cad_agent import CADAnalysisAgent
    from src.orchestrator import InMemoryDiagramStore, Orchestrator
    from src.preprocessing.pipeline import PreprocessingPipeline
    from src.tiling.tile_storage import LocalStorage
    from src.tools._store import configure_store

    tile_dir = Path("/tmp/cad-diagram-analyzer/tiles")
    store = InMemoryDiagramStore()
    storage = LocalStorage(tile_dir)
    configure_store(store)

    try:
        agent: Any = CADAnalysisAgent()
    except RuntimeError:
        agent = None

    # --- Try to build a real OCR + CV pipeline ---
    try:
        from src.preprocessing.cv_pipeline import CVPipeline
        from src.preprocessing.docai_client import DocumentAIClient
        from src.preprocessing.ocr import DocumentAIOCRExtractor

        project_id = os.environ.get("GCP_PROJECT_ID", "")
        location = os.environ.get("DOCUMENT_AI_LOCATION", "us")
        processor_id = os.environ.get("DOCUMENT_AI_PROCESSOR_ID", "")

        if not project_id or not processor_id:
            raise ValueError("GCP_PROJECT_ID or DOCUMENT_AI_PROCESSOR_ID not configured")

        client = DocumentAIClient(
            project_id=project_id,
            location=location,
            processor_id=processor_id,
        )
        ocr = DocumentAIOCRExtractor(client)
        cv = CVPipeline()
        pipeline = PreprocessingPipeline(ocr_extractor=ocr, cv_pipeline=cv)
        _log.info("Using real Document AI OCR + OpenCV CV pipeline")

    except Exception as exc:
        _log.warning("Falling back to no-op OCR/CV stubs: %s", exc)
        pipeline = _build_noop_pipeline()

    return Orchestrator(
        preprocessing_pipeline=pipeline,
        tile_storage=storage,
        store=store,
        agent=agent,
    )


def _build_noop_pipeline() -> Any:
    """Return a PreprocessingPipeline with no-op OCR and CV stubs."""
    from src.preprocessing.pipeline import PreprocessingPipeline

    class _NoOpOCR:
        async def extract(self, image: Any) -> list:  # noqa: ARG002
            return []

    class _NoOpCV:
        def run(self, image: Any) -> Any:  # noqa: ARG002
            from src.models.cv import CVResult
            return CVResult()

    return PreprocessingPipeline(
        ocr_extractor=_NoOpOCR(),  # type: ignore[arg-type]
        cv_pipeline=_NoOpCV(),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Module-level app (None when FastAPI absent, fully configured otherwise)
# ---------------------------------------------------------------------------

try:
    app = create_app()
except RuntimeError:  # pragma: no cover — FastAPI not installed
    app = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the uvicorn development server.

    Args:
        host: Bind address (default ``"0.0.0.0"``).
        port: TCP port to listen on (default ``8080``).

    Raises:
        RuntimeError: If ``fastapi`` or ``uvicorn`` are not installed.
    """
    if not _FASTAPI_AVAILABLE or app is None:
        raise RuntimeError(
            "fastapi and uvicorn are required to run the server. "
            "Run: pip install 'fastapi[standard]' uvicorn"
        )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    run_server()
