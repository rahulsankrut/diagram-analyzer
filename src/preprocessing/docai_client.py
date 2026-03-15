"""Thin async adapter wrapping the Google Cloud Document AI client.

Isolates the Document AI SDK behind a narrow interface so callers can be
tested by injecting a mock instead of hitting the real API.

Expected response dict structure (matches Document AI proto-plus serialization)::

    {
        "text": "R1\\nR2\\n",
        "pages": [
            {
                "page_number": 1,
                "tokens": [
                    {
                        "layout": {
                            "text_anchor": {
                                "text_segments": [
                                    {"start_index": "0", "end_index": "2"}
                                ]
                            },
                            "confidence": 0.95,
                            "bounding_poly": {
                                "normalized_vertices": [
                                    {"x": 0.1, "y": 0.2},
                                    {"x": 0.3, "y": 0.2},
                                    {"x": 0.3, "y": 0.4},
                                    {"x": 0.1, "y": 0.4},
                                ]
                            },
                        }
                    }
                ],
            }
        ],
    }
"""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Only imported for type checking; not needed at runtime in test environments
    # where google-cloud-documentai may not be installed.
    pass


class DocumentAIClient:
    """Thin async wrapper around the Google Cloud Document AI processing API.

    The Google Cloud Document AI SDK (``google-cloud-documentai``) is imported
    lazily inside :meth:`__init__` so that this module can be imported — and
    mocked in tests — without the SDK being installed in the environment.

    Args:
        project_id: GCP project ID (e.g. ``"my-project"``).
        location: Processor location, e.g. ``"us"`` or ``"eu"``.
        processor_id: Document AI processor resource ID.
    """

    def __init__(self, project_id: str, location: str, processor_id: str) -> None:
        # Lazy import: only needed when constructing a real client
        from google.cloud import documentai_v1 as documentai  # noqa: PLC0415

        self._project_id = project_id
        self._location = location
        self._processor_id = processor_id
        self._documentai = documentai
        self._client = documentai.DocumentProcessorServiceClient(
            client_options={"api_endpoint": f"{location}-documentai.googleapis.com"}
        )
        self._processor_name = self._client.processor_path(
            project_id, location, processor_id
        )

    async def process_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
    ) -> dict[str, Any]:
        """Send image bytes to Document AI and return the raw response as a dict.

        The Document AI client is synchronous; this method offloads the blocking
        call to a thread pool so the caller can ``await`` it without blocking the
        event loop.

        Args:
            image_bytes: Raw image bytes (PNG, JPEG, TIFF, or PDF).
            mime_type: MIME type string, e.g. ``"image/png"`` or ``"image/tiff"``.

        Returns:
            Document AI ``Document`` serialized to a plain Python dict.

        Raises:
            google.api_core.exceptions.GoogleAPICallError: On any API failure.
        """
        documentai = self._documentai
        raw_document = documentai.RawDocument(
            content=image_bytes, mime_type=mime_type
        )
        request = documentai.ProcessRequest(
            name=self._processor_name, raw_document=raw_document
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            functools.partial(self._client.process_document, request=request),
        )
        return type(response.document).to_dict(response.document)
