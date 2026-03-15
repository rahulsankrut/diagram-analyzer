# CAD Diagram Analyzer

Agentic application that ingests complex CAD diagrams (electrical schematics, P&IDs, etc.) and makes them comprehensible to a multimodal LLM through a multi-resolution tiling and tool-augmented reasoning pipeline.

## Quick Start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
python -m src.agent.server
```

See `CLAUDE.md` for full documentation.
