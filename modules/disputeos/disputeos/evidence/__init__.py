"""Evidence provenance graph and contradiction detection exports."""

from disputeos.evidence.detector import detect_contradictions, detect_missing_evidence
from disputeos.evidence.graph import (
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    build_evidence_graph,
)

__all__ = [
    "EvidenceEdge",
    "EvidenceGraph",
    "EvidenceNode",
    "build_evidence_graph",
    "detect_contradictions",
    "detect_missing_evidence",
]
