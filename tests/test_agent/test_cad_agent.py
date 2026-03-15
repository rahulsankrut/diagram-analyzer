"""Integration tests for src/agent/cad_agent.py.

All ADK / Gemini API calls are replaced by lightweight mocks so the tests
run without network access and without google-adk installed.

Test coverage:
- Agent initialisation: all five tools are registered, system instruction set.
- analyze() wiring: runner is created, run() is called with correct args.
- Response extraction: final text is pulled from the event stream correctly.
- Mock tool call flow: a mock LLM triggers a real tool function and the result
  is visible in the captured response — verifying the DI seam works end-to-end.
- Error path: missing diagram raises nothing (the store already returns error
  dict from the tool; the agent just surfaces it as text).
"""

from __future__ import annotations

import src.tools._store as _store_module
import pytest
from unittest.mock import MagicMock, call

from PIL import Image

from src.agent.cad_agent import (
    SYSTEM_INSTRUCTION,
    CADAnalysisAgent,
    _collect_final_text,
)
from src.models.component import Component, Pin
from src.models.diagram import DiagramMetadata
from src.models.ocr import BoundingBox
from src.models.text_label import TextLabel
from src.models.tiling import Tile, TilePyramid
from src.models.title_block import TitleBlock
from src.models.trace import Trace
from src.tools._store import DiagramStore, configure_store

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

DIAGRAM_ID = "integ-diag-0001"
COMP_A_ID = "integ-comp-aaa"
COMP_B_ID = "integ-comp-bbb"
PIN_A_ID = "integ-pin-a-out"
PIN_B_ID = "integ-pin-b-in"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_metadata() -> DiagramMetadata:
    comp_a = Component(
        component_id=COMP_A_ID,
        component_type="resistor",
        value="100Ω",
        bbox=BoundingBox(x_min=0.12, y_min=0.25, x_max=0.28, y_max=0.37),
        pins=[Pin(pin_id=PIN_A_ID, name="OUT", position=(0.28, 0.31))],
        confidence=0.9,
    )
    comp_b = Component(
        component_id=COMP_B_ID,
        component_type="capacitor",
        value="10µF",
        bbox=BoundingBox(x_min=0.62, y_min=0.25, x_max=0.78, y_max=0.37),
        pins=[Pin(pin_id=PIN_B_ID, name="IN", position=(0.62, 0.31))],
        confidence=0.88,
    )
    label = TextLabel(
        text="R1",
        bbox=BoundingBox(x_min=0.16, y_min=0.28, x_max=0.24, y_max=0.34),
        confidence=0.95,
    )
    trace = Trace(
        trace_id="integ-trace-001",
        from_component=COMP_A_ID,
        from_pin=PIN_A_ID,
        to_component=COMP_B_ID,
        to_pin=PIN_B_ID,
        path=[(0.28, 0.31), (0.62, 0.31)],
    )
    title = TitleBlock(
        drawing_id="INTEG-001",
        title="Integration Test Schematic",
        revision="A",
    )
    return DiagramMetadata(
        diagram_id=DIAGRAM_ID,
        source_filename="integ_test.png",
        format="png",
        width_px=800,
        height_px=600,
        components=[comp_a, comp_b],
        text_labels=[label],
        traces=[trace],
        title_block=title,
    )


def _make_pyramid() -> TilePyramid:
    pyramid = TilePyramid(diagram_id=DIAGRAM_ID)
    pyramid.tiles.append(
        Tile(
            tile_id=f"{DIAGRAM_ID}_L0_R0_C0",
            level=0,
            row=0,
            col=0,
            bbox=BoundingBox(x_min=0.001, y_min=0.001, x_max=0.999, y_max=0.999),
        )
    )
    return pyramid


@pytest.fixture()
def configured_store() -> MagicMock:
    """Provide a mock store pre-loaded with integration-test diagram data."""
    store = MagicMock(spec=DiagramStore)
    store.get_metadata.return_value = _make_metadata()
    store.get_pyramid.return_value = _make_pyramid()
    store.load_tile_image.return_value = Image.new("RGB", (256, 256), color="white")
    store.load_original_image.return_value = Image.new("RGB", (800, 600), color="white")
    configure_store(store)
    yield store
    _store_module._instance = None


@pytest.fixture()
def mock_types() -> MagicMock:
    """A MagicMock replacing google.genai.types."""
    return MagicMock()


@pytest.fixture()
def mock_agent_cls() -> MagicMock:
    """A MagicMock replacing the LlmAgent class constructor."""
    return MagicMock()


@pytest.fixture()
def mock_runner_cls() -> MagicMock:
    """A MagicMock replacing the InMemoryRunner class constructor."""
    runner_instance = MagicMock()
    # run() returns a single 'final answer' event by default
    event = MagicMock()
    event.content.parts = [MagicMock(text="Agent analysis complete.")]
    runner_instance.run.return_value = iter([event])

    runner_cls = MagicMock(return_value=runner_instance)
    runner_cls._instance = runner_instance  # expose for assertions
    return runner_cls


@pytest.fixture()
def agent(
    mock_agent_cls: MagicMock,
    mock_runner_cls: MagicMock,
    mock_types: MagicMock,
) -> CADAnalysisAgent:
    """CADAnalysisAgent wired with all mocks; no real ADK or Gemini calls."""
    return CADAnalysisAgent(
        _agent_cls=mock_agent_cls,
        _runner_cls=mock_runner_cls,
        _types_mod=mock_types,
    )


# ---------------------------------------------------------------------------
# Initialisation tests
# ---------------------------------------------------------------------------


def test_agent_registers_all_five_tools(
    agent: CADAnalysisAgent,
    mock_agent_cls: MagicMock,
) -> None:
    """LlmAgent constructor receives exactly five tool functions."""
    _, kwargs = mock_agent_cls.call_args
    tools = kwargs["tools"]
    assert len(tools) == 5


def test_agent_tools_are_callable(agent: CADAnalysisAgent) -> None:
    """Every registered tool is a callable (not wrapped in any ADK class)."""
    for tool in agent.tools:
        assert callable(tool), f"Expected callable, got {type(tool)}"


def test_agent_tool_names(agent: CADAnalysisAgent) -> None:
    """All five expected tool names are present."""
    names = {fn.__name__ for fn in agent.tools}
    assert names == {
        "get_overview",
        "inspect_zone",
        "inspect_component",
        "search_text",
        "trace_net",
    }


def test_agent_receives_system_instruction(
    agent: CADAnalysisAgent,
    mock_agent_cls: MagicMock,
) -> None:
    """LlmAgent is created with the canonical SYSTEM_INSTRUCTION."""
    _, kwargs = mock_agent_cls.call_args
    assert kwargs["instruction"] == SYSTEM_INSTRUCTION


def test_system_instruction_contains_workflow_steps(agent: CADAnalysisAgent) -> None:
    """System instruction mentions all five tool names."""
    for fn_name in ("get_overview", "inspect_zone", "inspect_component",
                    "search_text", "trace_net"):
        assert fn_name in agent.system_instruction


def test_agent_name_is_set(agent: CADAnalysisAgent, mock_agent_cls: MagicMock) -> None:
    """LlmAgent receives a non-empty name."""
    _, kwargs = mock_agent_cls.call_args
    assert kwargs.get("name")


def test_model_default(mock_types: MagicMock) -> None:
    """Default model is 'gemini-2.5-flash'."""
    from src.agent.cad_agent import DEFAULT_MODEL

    captured = MagicMock()
    CADAnalysisAgent(_agent_cls=captured, _runner_cls=MagicMock(), _types_mod=mock_types)
    _, kwargs = captured.call_args
    assert kwargs["model"] == DEFAULT_MODEL


def test_custom_model_forwarded(mock_types: MagicMock) -> None:
    """Non-default model string is forwarded to LlmAgent."""
    captured = MagicMock()
    CADAnalysisAgent(
        "gemini-2.0-flash",
        _agent_cls=captured,
        _runner_cls=MagicMock(),
        _types_mod=mock_types,
    )
    _, kwargs = captured.call_args
    assert kwargs["model"] == "gemini-2.0-flash"


def test_runtime_error_when_adk_absent(mock_types: MagicMock) -> None:
    """Passing _agent_cls=None simulates ADK not installed."""
    with pytest.raises(RuntimeError, match="google-adk"):
        CADAnalysisAgent(_agent_cls=None, _runner_cls=MagicMock(), _types_mod=mock_types)


# ---------------------------------------------------------------------------
# analyze() wiring tests
# ---------------------------------------------------------------------------


def test_analyze_creates_runner(
    agent: CADAnalysisAgent,
    mock_runner_cls: MagicMock,
    configured_store: MagicMock,
) -> None:
    """analyze() instantiates InMemoryRunner with the agent object."""
    agent.analyze(DIAGRAM_ID, "Summarise this schematic.")
    mock_runner_cls.assert_called_once()
    _, kwargs = mock_runner_cls.call_args
    assert kwargs.get("agent") is not None


def test_analyze_calls_runner_run(
    agent: CADAnalysisAgent,
    mock_runner_cls: MagicMock,
    configured_store: MagicMock,
) -> None:
    """analyze() calls runner.run() exactly once."""
    agent.analyze(DIAGRAM_ID, "What components are present?")
    mock_runner_cls._instance.run.assert_called_once()


def test_analyze_passes_user_id(
    agent: CADAnalysisAgent,
    mock_runner_cls: MagicMock,
    configured_store: MagicMock,
) -> None:
    """analyze() forwards the user_id to runner.run()."""
    agent.analyze(DIAGRAM_ID, "query", user_id="engineer-42")
    _, kwargs = mock_runner_cls._instance.run.call_args
    assert kwargs["user_id"] == "engineer-42"


def test_analyze_embeds_diagram_id_in_content(
    agent: CADAnalysisAgent,
    mock_runner_cls: MagicMock,
    mock_types: MagicMock,
    configured_store: MagicMock,
) -> None:
    """The diagram_id is embedded in the Content object passed to runner.run()."""
    agent.analyze(DIAGRAM_ID, "List all components.")
    # mock_types.Part was called with text containing the diagram_id
    part_calls = mock_types.Part.call_args_list
    assert any(DIAGRAM_ID in str(c) for c in part_calls)


def test_analyze_returns_text_from_event(
    agent: CADAnalysisAgent,
    configured_store: MagicMock,
) -> None:
    """analyze() returns the text extracted from the mock event stream."""
    result = agent.analyze(DIAGRAM_ID, "Summarise this schematic.")
    assert result == "Agent analysis complete."


def test_analyze_returns_empty_string_for_no_text_events(
    agent: CADAnalysisAgent,
    mock_runner_cls: MagicMock,
    configured_store: MagicMock,
) -> None:
    """analyze() returns '' when event stream has no text-bearing events."""
    empty_event = MagicMock()
    empty_event.content = None
    mock_runner_cls._instance.run.return_value = iter([empty_event])

    result = agent.analyze(DIAGRAM_ID, "query")
    assert result == ""


def test_analyze_unique_session_ids(
    agent: CADAnalysisAgent,
    mock_runner_cls: MagicMock,
    configured_store: MagicMock,
) -> None:
    """Each analyze() call without an explicit session_id generates a unique one."""
    agent.analyze(DIAGRAM_ID, "q1")
    agent.analyze(DIAGRAM_ID, "q2")

    calls = mock_runner_cls._instance.run.call_args_list
    sid1 = calls[0][1]["session_id"]
    sid2 = calls[1][1]["session_id"]
    assert sid1 != sid2


def test_analyze_explicit_session_id_respected(
    agent: CADAnalysisAgent,
    mock_runner_cls: MagicMock,
    configured_store: MagicMock,
) -> None:
    """When session_id is provided it is forwarded unchanged."""
    agent.analyze(DIAGRAM_ID, "query", session_id="my-session-99")
    _, kwargs = mock_runner_cls._instance.run.call_args
    assert kwargs["session_id"] == "my-session-99"


# ---------------------------------------------------------------------------
# _collect_final_text unit tests
# ---------------------------------------------------------------------------


def test_collect_final_text_single_event() -> None:
    event = MagicMock()
    event.content.parts = [MagicMock(text="Hello from agent")]
    assert _collect_final_text([event]) == "Hello from agent"


def test_collect_final_text_last_text_wins() -> None:
    """When multiple events carry text, the last non-empty one is returned."""
    e1 = MagicMock()
    e1.content.parts = [MagicMock(text="First")]
    e2 = MagicMock()
    e2.content.parts = [MagicMock(text="Final answer")]
    assert _collect_final_text([e1, e2]) == "Final answer"


def test_collect_final_text_skips_none_content() -> None:
    e_null = MagicMock()
    e_null.content = None
    e_text = MagicMock()
    e_text.content.parts = [MagicMock(text="Result")]
    assert _collect_final_text([e_null, e_text]) == "Result"


def test_collect_final_text_skips_none_text() -> None:
    event = MagicMock()
    event.content.parts = [MagicMock(text=None), MagicMock(text="Good")]
    assert _collect_final_text([event]) == "Good"


def test_collect_final_text_empty_stream() -> None:
    assert _collect_final_text([]) == ""


# ---------------------------------------------------------------------------
# Mock tool-call flow integration test
# ---------------------------------------------------------------------------


def test_mock_tool_call_flows_through(configured_store: MagicMock) -> None:
    """A tool triggered by the mock LLM executes against the real store.

    Scenario:
      1. The mock 'LLM' decides to call ``get_overview(diagram_id=DIAGRAM_ID)``.
      2. The test's custom runner calls the real tool function directly,
         simulating what the ADK framework would do during a function-calling
         turn.
      3. The real tool reads from the configured store and returns a dict.
      4. The runner packages the result into a mock event.
      5. analyze() extracts the text and returns it.

    This verifies that the DI seam (store → tool → runner → analyze) is
    fully wired and that the tool functions are live callables, not stubs.
    """
    from src.tools.get_overview import get_overview

    captured: dict = {}

    class _SimulatedRunner:
        """Runner that mimics one LLM tool-call turn without the real ADK."""

        def __init__(self, *, agent: object) -> None:
            pass

        def run(self, *, user_id: str, session_id: str, new_message: object) -> list:
            # Step 1: 'LLM' decides to call get_overview
            tool_result = get_overview(DIAGRAM_ID)
            captured.update(tool_result)

            # Step 2: 'LLM' produces its final response based on the result
            count = tool_result.get("component_count", 0)
            event = MagicMock()
            event.content.parts = [
                MagicMock(text=f"Diagram has {count} components.")
            ]
            return [event]

    agent = CADAnalysisAgent(
        _agent_cls=MagicMock(),
        _runner_cls=_SimulatedRunner,
        _types_mod=MagicMock(),
    )

    response = agent.analyze(DIAGRAM_ID, "How many components are in this diagram?")

    # Tool was called and returned real data from the configured mock store
    assert captured["diagram_id"] == DIAGRAM_ID
    assert captured["component_count"] == 2
    assert captured["component_types"] == {"resistor": 1, "capacitor": 1}
    assert captured["title_block"]["drawing_id"] == "INTEG-001"

    # Agent response reflects the tool result
    assert "2" in response
    assert "components" in response.lower()
