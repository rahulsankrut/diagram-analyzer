"""Firestore adapter — thin async wrapper around google-cloud-firestore."""

from __future__ import annotations

import types
from typing import Any

# Lazy import so the module can be loaded (and mocked in tests) without the
# GCP SDK installed.  The SimpleNamespace stub keeps the module-level name
# ``firestore`` patchable by unittest.mock.patch.
try:
    from google.cloud import firestore  # type: ignore[import]
except ImportError:
    firestore = types.SimpleNamespace(AsyncClient=None)  # type: ignore[assignment]


class FirestoreAdapter:
    """Thin wrapper around the async Firestore client.

    Scoped to a single Firestore collection so callers never pass collection
    names directly (reduces typo-induced bugs).

    Args:
        collection: Firestore collection name (e.g. ``"diagrams"``).
        project_id: GCP project ID. Inferred from ADC when omitted.
        database: Firestore database ID. Defaults to ``"(default)"``.
        client: Injected async client for testing. Created from ADC if omitted.
    """

    def __init__(
        self,
        collection: str,
        project_id: str | None = None,
        database: str = "(default)",
        client: Any = None,
    ) -> None:
        self._collection = collection
        self._client: firestore.AsyncClient = client or firestore.AsyncClient(
            project=project_id,
            database=database,
        )

    async def save_document(self, doc_id: str, data: dict[str, Any]) -> str:
        """Create or overwrite a document.

        Args:
            doc_id: Document identifier within the collection.
            data: Serializable dict to persist.

        Returns:
            The document ID (same as ``doc_id``).
        """
        doc_ref = self._client.collection(self._collection).document(doc_id)
        await doc_ref.set(data)
        return doc_id

    async def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Retrieve a document by ID.

        Args:
            doc_id: Document identifier within the collection.

        Returns:
            Document data dict, or ``None`` if the document does not exist.
        """
        doc_ref = self._client.collection(self._collection).document(doc_id)
        snapshot = await doc_ref.get()
        if not snapshot.exists:
            return None
        return snapshot.to_dict()  # type: ignore[return-value]

    async def update_document(self, doc_id: str, data: dict[str, Any]) -> None:
        """Merge-update specific fields in an existing document.

        Args:
            doc_id: Document identifier within the collection.
            data: Fields to update (non-listed fields are preserved).
        """
        doc_ref = self._client.collection(self._collection).document(doc_id)
        await doc_ref.update(data)
