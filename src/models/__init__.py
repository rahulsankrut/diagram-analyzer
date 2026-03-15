"""Public re-exports for the models package.

Supports both direct module imports and package-level imports:

    from src.models.diagram import DiagramMetadata   # direct
    from src.models import DiagramMetadata            # via __init__
"""

from src.models.analysis import AnalysisResult, BOMEntry, NetlistEntry
from src.models.component import Component, Pin
from src.models.cv import CVResult, DetectedLine, Symbol
from src.models.diagram import DiagramMetadata, IngestionRequest, IngestionResult
from src.models.ocr import BoundingBox, OCRElement, OCRResult
from src.models.text_label import TextLabel
from src.models.tiling import Tile, TileLevel, TilePyramid, TilingManifest
from src.models.title_block import TitleBlock
from src.models.trace import Trace

__all__ = [
    # ocr
    "BoundingBox",
    "OCRElement",
    "OCRResult",
    # component
    "Pin",
    "Component",
    # text_label
    "TextLabel",
    # trace (semantic)
    "Trace",
    # cv (raw detection)
    "Symbol",
    "DetectedLine",
    "CVResult",
    # title_block
    "TitleBlock",
    # diagram
    "DiagramMetadata",
    "IngestionRequest",
    "IngestionResult",
    # tiling
    "TileLevel",
    "Tile",
    "TilePyramid",
    "TilingManifest",
    # analysis
    "AnalysisResult",
    "BOMEntry",
    "NetlistEntry",
]
