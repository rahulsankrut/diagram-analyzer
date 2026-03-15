#!/usr/bin/env python3
"""Quick local test harness for the CAD Diagram Analyzer.

Runs the full pipeline (ingest → preprocess → tile → agent) on a local image
file and prints the agent's response.  No GCP credentials are required for
the pre-processing stages (a no-op OCR stub is used); the agent stage needs
a valid GOOGLE_API_KEY or Vertex AI ADC.

Usage::

    python scripts/test_local.py ./sample_schematic.png "What components are in this circuit?"

    # Custom model and tile directory:
    python scripts/test_local.py ./schematic.png "List all resistors" \\
        --model gemini-2.0-flash \\
        --tile-dir /tmp/my-tiles

Exit codes:
    0  Success
    1  Input error (file not found, missing question, …)
    2  Pipeline or agent error
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="test_local.py",
        description="Run the CAD Diagram Analyzer on a local image file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "image_path",
        type=Path,
        help="Path to the diagram image (PNG, TIFF, or JPEG).",
    )
    parser.add_argument(
        "question",
        help='Natural-language question, e.g. "What components are in this circuit?"',
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        metavar="MODEL",
        help="Gemini model ID to use (default: gemini-2.5-flash).",
    )
    parser.add_argument(
        "--tile-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Directory to store generated tile images.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser


def _setup_logging(verbose: bool) -> None:
    import logging

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    _setup_logging(args.verbose)

    # --- Validate inputs ------------------------------------------------

    if not args.image_path.exists():
        print(
            f"Error: image file not found: {args.image_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.question.strip():
        print("Error: question must not be empty.", file=sys.stderr)
        sys.exit(1)

    # --- Late import (keeps --help fast) --------------------------------

    from src.orchestrator import Orchestrator

    # --- Build orchestrator ---------------------------------------------

    print(f"Building pipeline (model: {args.model})…")
    orch = Orchestrator.create_local(
        tile_dir=args.tile_dir,
        model=args.model,
    )

    if orch._agent is None:
        print(
            "\nError: google-adk is not installed — the agent cannot run.\n"
            "Install it with:\n"
            "    pip install 'google-cloud-aiplatform[adk,agent-engines]' google-genai",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Run pipeline ---------------------------------------------------

    print(f"Ingesting {args.image_path.name}…")
    t0 = time.perf_counter()

    try:
        response = orch.analyze(args.image_path, args.question)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\nError during analysis: {exc}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(2)

    elapsed = time.perf_counter() - t0

    # --- Print result ---------------------------------------------------

    print(f"\nAnalysis complete ({elapsed:.1f}s)")
    print("=" * 60)
    print(response)
    print("=" * 60)


if __name__ == "__main__":
    main()
