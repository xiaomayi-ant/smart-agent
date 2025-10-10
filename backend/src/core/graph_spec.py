"""
Lightweight export of the current LangGraph specification for visualization.
This module intentionally avoids importing heavy runtime dependencies.
"""
from typing import Dict, Any
import os


def export_graph_spec() -> Dict[str, Any]:
    nodes = [
        "intent_slot_detect",
        "detect_intent",
        "collect_base_data",
        "planner",
        "set_barrier",
        "Orchestrator",
        "SQL_Subgraph",
        "Vector_Subgraph",
        "KG_Subgraph",
        "aggregate_normalize_optional",
        "response_writer",
        "simple_response",
        "END",
    ]

    edges = [
        {"from": "intent_slot_detect", "to": "detect_intent", "type": "edge"},
        {"from": "detect_intent", "to": "collect_base_data", "type": "edge"},

        # Conditional routing after collect_base_data
        {"from": "collect_base_data", "to": "planner", "type": "conditional", "label": "has tool_calls"},
        {"from": "collect_base_data", "to": "simple_response", "type": "conditional", "label": "no tool_calls"},

        # Planner/Orchestrator fan-out (Send via conditional edges)
        {"from": "planner", "to": "set_barrier", "type": "edge"},
        {"from": "set_barrier", "to": "Orchestrator", "type": "edge"},

        # Orchestrator dispatches to subgraphs (conditional)
        {"from": "Orchestrator", "to": "SQL_Subgraph", "type": "conditional", "label": "maybe"},
        {"from": "Orchestrator", "to": "KG_Subgraph", "type": "conditional", "label": "maybe"},
        {"from": "Orchestrator", "to": "Vector_Subgraph", "type": "conditional", "label": "maybe"},

        # Subgraphs return to aggregator
        {"from": "SQL_Subgraph", "to": "aggregate_normalize_optional", "type": "edge"},
        {"from": "KG_Subgraph", "to": "aggregate_normalize_optional", "type": "edge"},
        {"from": "Vector_Subgraph", "to": "aggregate_normalize_optional", "type": "edge"},

        # Aggregation routing
        {"from": "aggregate_normalize_optional", "to": "Orchestrator", "type": "conditional", "label": "more"},
        {"from": "aggregate_normalize_optional", "to": "response_writer", "type": "conditional", "label": "fast"},
        {"from": "aggregate_normalize_optional", "to": "response_writer", "type": "conditional", "label": "done"},

        # Simple response path
        {"from": "simple_response", "to": "END", "type": "edge"},
    ]

    return {"nodes": nodes, "edges": edges}


def to_mermaid(spec: Dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    for e in spec.get("edges", []):
        src = e.get("from"); dst = e.get("to"); t = e.get("type", "edge"); label = e.get("label")
        if t == "conditional" and label:
            lines.append(f"  {src} -->|{label}| {dst}")
        else:
            lines.append(f"  {src} --> {dst}")
    return "\n".join(lines)


if __name__ == "__main__":
    spec = export_graph_spec()
    mermaid = to_mermaid(spec)
    # Write to backend/graph.mmd regardless of CWD
    here = os.path.dirname(__file__)  # .../backend/src/core
    backend_dir = os.path.abspath(os.path.join(here, "..", ".."))  # .../backend
    out_path = os.path.join(backend_dir, "graph.mmd")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(mermaid + "\n")
    print(f"Mermaid written to {out_path}")


