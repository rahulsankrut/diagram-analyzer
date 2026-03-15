"""Tests for the semantic Trace model."""

import pytest
from pydantic import ValidationError

from src.models.trace import Trace


class TestTrace:
    def test_valid_creation(self) -> None:
        trace = Trace(
            from_component="comp-a",
            from_pin="pin-out",
            to_component="comp-b",
            to_pin="pin-in",
        )
        assert trace.from_component == "comp-a"
        assert trace.to_component == "comp-b"
        assert trace.path == []

    def test_auto_uuid_trace_id(self) -> None:
        t1 = Trace(from_component="a", from_pin="1", to_component="b", to_pin="2")
        t2 = Trace(from_component="a", from_pin="1", to_component="b", to_pin="2")
        assert t1.trace_id != t2.trace_id
        assert len(t1.trace_id) == 36

    def test_explicit_trace_id(self) -> None:
        trace = Trace(
            trace_id="my-trace-id",
            from_component="a",
            from_pin="1",
            to_component="b",
            to_pin="2",
        )
        assert trace.trace_id == "my-trace-id"

    def test_path_with_waypoints(self) -> None:
        path = [(0.2, 0.3), (0.4, 0.3), (0.6, 0.3)]
        trace = Trace(
            from_component="c1",
            from_pin="OUT",
            to_component="c2",
            to_pin="IN",
            path=path,
        )
        assert len(trace.path) == 3
        assert trace.path[0] == pytest.approx((0.2, 0.3))

    def test_empty_path_is_valid(self) -> None:
        trace = Trace(from_component="a", from_pin="p1", to_component="b", to_pin="p2")
        assert trace.path == []

    def test_missing_from_component_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Trace(from_pin="1", to_component="b", to_pin="2")  # type: ignore[call-arg]

    def test_missing_to_pin_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Trace(from_component="a", from_pin="1", to_component="b")  # type: ignore[call-arg]

    def test_to_dict_structure(self) -> None:
        trace = Trace(
            from_component="c1",
            from_pin="OUT",
            to_component="c2",
            to_pin="IN",
            path=[(0.1, 0.2), (0.5, 0.2)],
        )
        d = trace.to_dict()
        assert "trace_id" in d
        assert d["from_component"] == "c1"
        assert d["from_pin"] == "OUT"
        assert d["to_component"] == "c2"
        assert d["to_pin"] == "IN"
        assert "path" in d

    def test_to_dict_path_is_list_of_lists(self) -> None:
        # model_dump(mode='json') converts tuples to lists
        trace = Trace(
            from_component="a",
            from_pin="1",
            to_component="b",
            to_pin="2",
            path=[(0.1, 0.2), (0.5, 0.6)],
        )
        d = trace.to_dict()
        assert d["path"] == [[0.1, 0.2], [0.5, 0.6]]

    def test_serialization_roundtrip(self) -> None:
        original = Trace(
            from_component="motor-1",
            from_pin="terminal-A",
            to_component="vfd-1",
            to_pin="output-U",
            path=[(0.3, 0.4), (0.5, 0.4), (0.7, 0.4)],
        )
        restored = Trace.model_validate_json(original.model_dump_json())
        assert restored == original
