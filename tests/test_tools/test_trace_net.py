"""Tests for src/tools/trace_net.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.tools.trace_net import trace_net
from tests.test_tools.conftest import (
    DIAGRAM_ID,
    COMP_A_ID,
    COMP_B_ID,
    PIN_A_ID,
    PIN_B_ID,
    TRACE_ID,
)


# ---------------------------------------------------------------------------
# Happy-path: trace from source pin
# ---------------------------------------------------------------------------


def test_returns_diagram_id(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["diagram_id"] == DIAGRAM_ID


def test_returns_component_id(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["component_id"] == COMP_A_ID


def test_returns_pin(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["pin"] == PIN_A_ID


def test_connection_found(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["connection_count"] == 1
    assert len(result["connections"]) == 1


def test_connection_has_required_keys(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    conn = result["connections"][0]
    for key in (
        "trace_id",
        "connected_component_id",
        "connected_component_type",
        "connected_pin",
        "direction",
        "path",
    ):
        assert key in conn


def test_connection_trace_id(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["connections"][0]["trace_id"] == TRACE_ID


def test_connection_peer_component(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    conn = result["connections"][0]
    assert conn["connected_component_id"] == COMP_B_ID
    assert conn["connected_component_type"] == "capacitor"


def test_connection_direction_from(mock_store: MagicMock) -> None:
    """comp_a is the source in the trace → direction should be 'from'."""
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["connections"][0]["direction"] == "from"


def test_path_is_list_of_pairs(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    path = result["connections"][0]["path"]
    assert isinstance(path, list)
    assert all(len(pt) == 2 for pt in path)


# ---------------------------------------------------------------------------
# Tracing from the destination side
# ---------------------------------------------------------------------------


def test_connection_direction_to(mock_store: MagicMock) -> None:
    """comp_b is the destination — direction should be 'to'."""
    result = trace_net(DIAGRAM_ID, COMP_B_ID, PIN_B_ID)
    assert result["connection_count"] == 1
    assert result["connections"][0]["direction"] == "to"
    assert result["connections"][0]["connected_component_id"] == COMP_A_ID


# ---------------------------------------------------------------------------
# Empty pin: match all connections for the component
# ---------------------------------------------------------------------------


def test_empty_pin_returns_all_connections(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, "")
    assert result["connection_count"] == 1


def test_wrong_pin_returns_no_connections(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, "NO_SUCH_PIN")
    assert result["connection_count"] == 0
    assert result["connections"] == []


# ---------------------------------------------------------------------------
# trace_data_unavailable when no traces in metadata
# ---------------------------------------------------------------------------


def test_trace_data_unavailable_flag(mock_store: MagicMock) -> None:
    metadata = mock_store.get_metadata.return_value
    metadata.traces = []

    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["trace_data_unavailable"] is True
    assert result["connections"] == []
    assert result["connection_count"] == 0


def test_trace_data_available_flag_when_traces_exist(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["trace_data_unavailable"] is False


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_error_diagram_not_found(store_unknown_diagram: MagicMock) -> None:
    result = trace_net("bad-id", COMP_A_ID, PIN_A_ID)
    assert "error" in result
    assert "bad-id" in result["error"]


def test_error_component_not_found(mock_store: MagicMock) -> None:
    result = trace_net(DIAGRAM_ID, "no-such-comp", PIN_A_ID)
    assert "error" in result
    assert "no-such-comp" in result["error"]


# ---------------------------------------------------------------------------
# Peer component not in metadata (orphaned trace)
# ---------------------------------------------------------------------------


def test_unknown_peer_type_is_unknown(mock_store: MagicMock) -> None:
    """If a trace references a component_id not in metadata, type is 'unknown'."""
    metadata = mock_store.get_metadata.return_value
    for trace in metadata.traces:
        trace.to_component = "orphan-comp-id"

    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    conn = result["connections"][0]
    assert conn["connected_component_id"] == "orphan-comp-id"
    assert conn["connected_component_type"] == "unknown"
