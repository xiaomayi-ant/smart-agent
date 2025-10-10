from typing import Dict, Any, Optional, List
from langchain.tools import tool
from datetime import datetime, timezone

from ...services.graphiti_service import get_graphiti_client
try:
    from graphiti_core.nodes import EntityNode  # type: ignore
    from graphiti_core.edges import EntityEdge  # type: ignore
except Exception:
    EntityNode = None  # type: ignore
    EntityEdge = None  # type: ignore
import csv
import os
import re
from uuid import NAMESPACE_URL, uuid5


@tool
async def graphiti_search_tool(query: str,
                               center_node_uuid: Optional[str] = None,
                               limit: int = 10,
                               user_id: Optional[str] = None) -> Dict[str, Any]:
    """Search graph facts using Graphiti. Enforces user context via group_id if applicable."""
    try:
        # 只读放宽：当 user_id 为空时，仍允许执行搜索（不涉及写入）
        client = await get_graphiti_client()
        # Execute search (Graphiti will translate to Cypher under the hood)
        res = await client.search(query, center_node_uuid=center_node_uuid, num_results=limit)
        items = []
        try:
            for e in res:
                # Graphiti may return edges/facts list; normalize to dict
                items.append({
                    "text": getattr(e, "fact", ""),
                    "metadata": {
                        "source": "kg",
                        "edge_name": getattr(e, "name", None),
                        "source_uuid": getattr(e, "source_node_uuid", None),
                        "target_uuid": getattr(e, "target_node_uuid", None),
                    }
                })
        except Exception:
            pass
        return {"success": True, "data": items, "count": len(items)}
    except Exception as e:
        return {"success": False, "data": [], "message": str(e)}


@tool
async def graphiti_add_episode_tool(name: str,
                                    body: str,
                                    source: str = "message",
                                    reference_time: Optional[str] = None,
                                    user_id: Optional[str] = None) -> Dict[str, Any]:
    """Append an episode (event/message) into the graph for the current user context."""
    try:
        if not user_id:
            return {"success": False, "message": "missing user_id"}
        client = await get_graphiti_client()
        ts = datetime.now(timezone.utc)
        if reference_time:
            try:
                ts = datetime.fromisoformat(reference_time)
            except Exception:
                pass
        ep = await client.add_episode(
            name=name,
            episode_body=body,
            source=source,
            reference_time=ts,
            source_description=f"user:{user_id}",
        )
        return {"success": True, "uuid": getattr(ep, "uuid", None)}
    except Exception as e:
        return {"success": False, "message": str(e)}


def _normalize_col(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[ \-]+", "_", s)
    s = re.sub(r"[^\w]+", "_", s)
    return s.strip("_")


def _stable_uuid_for_node(group_id: str, labels: list[str], business_key: str) -> str:
    key = f"{group_id}::{':'.join(sorted(set(labels)))}::{business_key}"
    return str(uuid5(NAMESPACE_URL, key))


def _stable_uuid_for_edge(group_id: str, src_uuid: str, edge_name: str, tgt_uuid: str, fact: str | None, include_fact: bool) -> str:
    if include_fact:
        key = f"{group_id}::{src_uuid}::{edge_name}::{tgt_uuid}::{fact or ''}"
    else:
        key = f"{group_id}::{src_uuid}::{edge_name}::{tgt_uuid}"
    return str(uuid5(NAMESPACE_URL, key))


@tool
async def graphiti_add_entity_tool(name: str,
                                   labels: list[str],
                                   group_id: str,
                                   uuid_value: Optional[str] = None,
                                   attributes: Optional[dict] = None,
                                   user_id: Optional[str] = None) -> Dict[str, Any]:
    """Create or upsert an entity node in the user's namespace."""
    try:
        if not user_id:
            return {"success": False, "message": "missing user_id"}
        if EntityNode is None:
            return {"success": False, "message": "graphiti_core not available"}
        client = await get_graphiti_client()
        node_uuid = uuid_value or _stable_uuid_for_node(group_id, labels, name)
        now = datetime.now(timezone.utc)
        node = EntityNode(
            uuid=node_uuid,
            name=name,
            group_id=group_id,
            labels=labels,
            name_embedding=[0.0],
            created_at=now,
            summary="",
            attributes=attributes or {},
        )
        await node.save(client.driver)  # type: ignore
        return {"success": True, "uuid": node_uuid}
    except Exception as e:
        return {"success": False, "message": str(e)}


@tool
async def graphiti_add_edge_tool(source_uuid: str,
                                 target_uuid: str,
                                 name: str,
                                 group_id: str,
                                 fact: Optional[str] = None,
                                 attributes: Optional[dict] = None,
                                 include_fact_in_uuid: bool = False,
                                 user_id: Optional[str] = None) -> Dict[str, Any]:
    """Create or upsert a relation edge between two existing (or to-be-created) nodes."""
    try:
        if not user_id:
            return {"success": False, "message": "missing user_id"}
        if EntityEdge is None:
            return {"success": False, "message": "graphiti_core not available"}
        client = await get_graphiti_client()
        now = datetime.now(timezone.utc)
        edge_uuid = _stable_uuid_for_edge(group_id, source_uuid, name, target_uuid, fact, include_fact_in_uuid)
        edge = EntityEdge(
            uuid=edge_uuid,
            group_id=group_id,
            source_node_uuid=source_uuid,
            target_node_uuid=target_uuid,
            name=name,
            fact=fact or "",
            fact_embedding=[0.0],
            episodes=[],
            created_at=now,
            expired_at=None,
            valid_at=None,
            invalid_at=None,
            attributes=attributes or {},
        )
        await edge.save(client.driver)  # type: ignore
        return {"success": True, "uuid": edge_uuid}
    except Exception as e:
        return {"success": False, "message": str(e)}


def _resolve_csv_from_file_id(file_id: Optional[str], user_id: Optional[str]) -> Optional[str]:
    """Placeholder resolver: prefer direct file_path in tool args. If not provided, implement your own mapping.
    Return absolute path if resolvable, else None.
    """
    return None


@tool
async def graphiti_ingest_detect_tool(file_path: Optional[str] = None,
                                      file_id: Optional[str] = None,
                                      max_preview: int = 20,
                                      user_id: Optional[str] = None) -> Dict[str, Any]:
    """Detect CSV schema and propose a plan. Returns preview rows and warnings. Does not write."""
    try:
        if not user_id:
            return {"success": False, "message": "missing user_id"}
        path = file_path or _resolve_csv_from_file_id(file_id, user_id)
        if not path or not os.path.exists(path):
            return {"success": False, "message": "csv not found (provide file_path or resolvable file_id)"}
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            norm_headers = [_normalize_col(h) for h in headers]
            # endpoint heuristics
            nh = set(norm_headers)
            edge = ("source_uuid" in nh and "target_uuid" in nh) or ("source_name" in nh and "target_name" in nh)
            plan: Dict[str, Any]
            if edge:
                plan = {
                    "mode": "edge",
                    "source_uuid_col": "source_uuid" if "source_uuid" in nh else None,
                    "target_uuid_col": "target_uuid" if "target_uuid" in nh else None,
                    "source_name_col": "source_name" if "source_name" in nh else None,
                    "target_name_col": "target_name" if "target_name" in nh else None,
                    "edge_name_col": "edge_name" if "edge_name" in nh else None,
                    "fact_col": "fact" if "fact" in nh else None,
                    "source_labels": ["Entity"],
                    "target_labels": ["Entity"],
                    "ensure_nodes": True,
                    "edge_versioned": False,
                }
            else:
                plan = {
                    "mode": "node",
                    "uuid_col": "uuid" if "uuid" in nh else None,
                    "name_col": "name" if "name" in nh else None,
                    "created_at_col": "created_at" if "created_at" in nh else None,
                    "primary_key_col": None,
                    "labels": ["Entity"],
                }
            preview: List[Dict[str, Any]] = []
            for i, row in enumerate(reader):
                if i >= max_preview:
                    break
                norm_row = { _normalize_col(k): v for k, v in row.items() }
                if plan["mode"] == "edge":
                    preview.append({
                        "source_uuid": norm_row.get(plan.get("source_uuid_col") or ""),
                        "source_name": norm_row.get(plan.get("source_name_col") or ""),
                        "edge_name": norm_row.get(plan.get("edge_name_col") or "") or "RELATES_TO",
                        "target_uuid": norm_row.get(plan.get("target_uuid_col") or ""),
                        "target_name": norm_row.get(plan.get("target_name_col") or ""),
                        "fact": norm_row.get(plan.get("fact_col") or ""),
                    })
                else:
                    preview.append({
                        "uuid": norm_row.get(plan.get("uuid_col") or ""),
                        "name": norm_row.get(plan.get("name_col") or ""),
                    })
            stats = {"totalRows": i + 1 if 'i' in locals() else 0, "previewRows": len(preview)}
            return {"success": True, "plan": plan, "preview": preview, "stats": stats}
    except Exception as e:
        return {"success": False, "message": str(e)}


@tool
async def graphiti_ingest_commit_tool(group_id: str,
                                      file_path: Optional[str] = None,
                                      file_id: Optional[str] = None,
                                      plan: Optional[dict] = None,
                                      user_id: Optional[str] = None) -> Dict[str, Any]:
    """Execute CSV ingest according to plan. Supports node or edge ingestion. Returns counts."""
    try:
        if not user_id:
            return {"success": False, "message": "missing user_id"}
        if EntityNode is None or EntityEdge is None:
            return {"success": False, "message": "graphiti_core not available"}
        if not plan or not isinstance(plan, dict):
            return {"success": False, "message": "missing plan"}
        path = file_path or _resolve_csv_from_file_id(file_id, user_id)
        if not path or not os.path.exists(path):
            return {"success": False, "message": "csv not found (provide file_path or resolvable file_id)"}
        client = await get_graphiti_client()
        inserted_nodes = 0
        inserted_edges = 0
        skipped = 0
        errors: List[Dict[str, Any]] = []
        mode = (plan.get("mode") or "node").lower()
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            norm_map = {h: _normalize_col(h) for h in headers}
            for row_idx, row in enumerate(reader, start=1):
                try:
                    norm_row = { norm_map.get(k, _normalize_col(k)): v for k, v in row.items() }
                    if mode == "edge":
                        src_uuid = (norm_row.get(plan.get("source_uuid_col") or "") or "").strip()
                        tgt_uuid = (norm_row.get(plan.get("target_uuid_col") or "") or "").strip()
                        src_name = (norm_row.get(plan.get("source_name_col") or "") or "").strip()
                        tgt_name = (norm_row.get(plan.get("target_name_col") or "") or "").strip()
                        if not src_uuid:
                            if not src_name:
                                raise ValueError("missing source endpoint")
                            src_uuid = _stable_uuid_for_node(group_id, plan.get("source_labels") or ["Entity"], src_name)
                        if not tgt_uuid:
                            if not tgt_name:
                                raise ValueError("missing target endpoint")
                            tgt_uuid = _stable_uuid_for_node(group_id, plan.get("target_labels") or ["Entity"], tgt_name)
                        # ensure nodes if requested
                        if bool(plan.get("ensure_nodes", True)):
                            now = datetime.now(timezone.utc)
                            src_node = EntityNode(uuid=src_uuid, name=src_name or src_uuid, group_id=group_id, labels=plan.get("source_labels") or ["Entity"], name_embedding=[0.0], created_at=now, summary="", attributes={})
                            tgt_node = EntityNode(uuid=tgt_uuid, name=tgt_name or tgt_uuid, group_id=group_id, labels=plan.get("target_labels") or ["Entity"], name_embedding=[0.0], created_at=now, summary="", attributes={})
                            await src_node.save(client.driver)  # type: ignore
                            await tgt_node.save(client.driver)  # type: ignore
                        edge_name = (norm_row.get(plan.get("edge_name_col") or "") or "RELATES_TO").strip()
                        fact = (norm_row.get(plan.get("fact_col") or "") or "").strip()
                        edge_uuid = _stable_uuid_for_edge(group_id, src_uuid, edge_name, tgt_uuid, fact, bool(plan.get("edge_versioned", False)))
                        now = datetime.now(timezone.utc)
                        edge = EntityEdge(uuid=edge_uuid, group_id=group_id, source_node_uuid=src_uuid, target_node_uuid=tgt_uuid, name=edge_name, fact=fact, fact_embedding=[0.0], episodes=[], created_at=now, expired_at=None, valid_at=None, invalid_at=None, attributes={})
                        await edge.save(client.driver)  # type: ignore
                        inserted_edges += 1
                    else:
                        name = (norm_row.get(plan.get("name_col") or "name") or "").strip()
                        if not name:
                            skipped += 1
                            continue
                        uuid_value = (norm_row.get(plan.get("uuid_col") or "") or "").strip() or _stable_uuid_for_node(group_id, plan.get("labels") or ["Entity"], name)
                        created_at = datetime.now(timezone.utc)
                        node = EntityNode(uuid=uuid_value, name=name, group_id=group_id, labels=plan.get("labels") or ["Entity"], name_embedding=[0.0], created_at=created_at, summary="", attributes={})
                        await node.save(client.driver)  # type: ignore
                        inserted_nodes += 1
                except Exception as row_err:
                    errors.append({"line": row_idx, "msg": str(row_err)})
        return {"success": True, "insertedNodes": inserted_nodes, "insertedEdges": inserted_edges, "skipped": skipped, "errors": errors}
    except Exception as e:
        return {"success": False, "message": str(e)}


