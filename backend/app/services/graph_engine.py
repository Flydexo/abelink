"""Probabilistic relationship graph engine powered by NetworkX and Dijkstra (-ln(p))."""

from __future__ import annotations

import math
import re
import threading
import unicodedata
from itertools import islice
from typing import Iterable, Optional

import networkx as nx

from app.db.repository import EdgeRecord, ProfileRecord
from app.schemas.search import ConnectionPath, GraphEdge, GraphNode, HopDetail

COMPANY_ALIASES: dict[str, str] = {
    "mistral": "mistral ai",
    "total": "totalenergies",
    "total energie": "totalenergies",
    "total energies": "totalenergies",
    "bnp": "bnp paribas",
    "bnpp": "bnp paribas",
    "socgen": "societe generale",
    "sg": "societe generale",
    "schneider": "schneider electric",
    "cs": "centralesupelec",
    "centrale supelec": "centralesupelec",
}

ASSO_ALIASES: dict[str, str] = {
    "jcs": "junior centralesupelec",
    "junior cs": "junior centralesupelec",
    "bureau des sports": "bds",
    "bureau des eleves": "bde",
}


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_company(name: Optional[str]) -> str:
    if not name:
        return ""
    cleaned = strip_accents(name).lower().strip()
    cleaned = re.sub(r"\b(sas|sarl|sa|inc|llc|ltd|group|france)\b", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return COMPANY_ALIASES.get(cleaned, cleaned)


def normalize_association(name: Optional[str]) -> str:
    if not name:
        return ""
    cleaned = strip_accents(name).lower().strip()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return ASSO_ALIASES.get(cleaned, cleaned)


def _parse_single_date(raw: Optional[str], *, is_end: bool = False) -> Optional[int]:
    """Convert date strings like '2022', '2022-03', 'Mar 2022', 'Present' into total months."""
    if not raw:
        return None
    text = strip_accents(str(raw)).strip().lower()
    if not text:
        return None
    if text in {"present", "aujourd'hui", "aujourdhui", "now", "current", "en cours"}:
        return 2026 * 12 + 11

    month_map = {
        "jan": 1, "janv": 1, "janvier": 1, "january": 1,
        "feb": 2, "fev": 2, "fevrier": 2, "february": 2,
        "mar": 3, "mars": 3, "march": 3,
        "apr": 4, "avr": 4, "avril": 4, "april": 4,
        "may": 5, "mai": 5,
        "jun": 6, "juin": 6, "june": 6,
        "jul": 7, "juil": 7, "juillet": 7, "july": 7,
        "aug": 8, "aou": 8, "aout": 8, "august": 8,
        "sep": 9, "sept": 9, "septembre": 9, "september": 9,
        "oct": 10, "octobre": 10, "october": 10,
        "nov": 11, "novembre": 11, "november": 11,
        "dec": 12, "decembre": 12, "december": 12,
    }

    ym = re.search(r"(\d{4})[-/](\d{1,2})", text)
    if ym:
        year, month = int(ym.group(1)), min(12, max(1, int(ym.group(2))))
        return year * 12 + month

    my = re.search(r"(\d{1,2})[-/](\d{4})", text)
    if my:
        month, year = min(12, max(1, int(my.group(1)))), int(my.group(2))
        return year * 12 + month

    year_match = re.search(r"(19\d{2}|20\d{2})", text)
    if not year_match:
        return None
    year = int(year_match.group(1))
    month = 12 if is_end else 1
    for word, m_num in month_map.items():
        if re.search(rf"\b{word}\b", text):
            month = m_num
            break
    return year * 12 + month


def parse_period_to_months(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: Optional[str] = None,
) -> Optional[tuple[int, int]]:
    """Return (start_months, end_months) inclusive interval."""
    s = _parse_single_date(start_date, is_end=False)
    e = _parse_single_date(end_date, is_end=True)

    if (s is None or e is None) and period:
        cleaned = period.replace("–", "-").replace("—", "-")
        parts = [p.strip() for p in cleaned.split("-") if p.strip()]
        if len(parts) >= 2:
            s = s if s is not None else _parse_single_date(parts[0], is_end=False)
            e = e if e is not None else _parse_single_date(parts[-1], is_end=True)
        elif len(parts) == 1:
            s = s if s is not None else _parse_single_date(parts[0], is_end=False)
            e = e if e is not None else _parse_single_date(parts[0], is_end=True)

    if s is None and e is None:
        return None
    if s is None:
        s = e
    if e is None:
        e = 2026 * 12 + 11
    if e < s:
        s, e = e, s
    return (s, e)


def _format_node_meta(attrs: dict) -> str:
    parts: list[str] = []
    if attrs.get("current_company"):
        parts.append(str(attrs["current_company"]))
    elif attrs.get("current_role"):
        parts.append(str(attrs["current_role"]))
    if attrs.get("promo_year"):
        parts.append(f"Promo {attrs['promo_year']}")
    return " · ".join(parts)


class GraphEngine:
    """Thread-safe in-memory NetworkX graph with parallel edge preservation and Dijkstra pathfinding."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._graph: nx.Graph = nx.Graph()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "nodes": self._graph.number_of_nodes(),
                "edges": self._graph.number_of_edges(),
            }

    def reload(self, profiles: Iterable[ProfileRecord], edges: Iterable[EdgeRecord]) -> None:
        """Atomically rebuild and swap the in-memory graph."""
        new_graph = nx.Graph()
        for profile in profiles:
            self._add_node_to_graph(new_graph, profile)
        for edge in edges:
            self._add_edge_to_graph(new_graph, edge)
        with self._lock:
            self._graph = new_graph

    def upsert_node(self, profile: ProfileRecord) -> None:
        with self._lock:
            self._add_node_to_graph(self._graph, profile)

    def upsert_edges(self, edges: Iterable[EdgeRecord]) -> None:
        with self._lock:
            for edge in edges:
                self._add_edge_to_graph(self._graph, edge)

    @staticmethod
    def _add_node_to_graph(graph: nx.Graph, profile: ProfileRecord) -> None:
        graph.add_node(
            profile.id,
            full_name=profile.full_name,
            promo_year=profile.promo_year,
            current_role=profile.current_role,
            current_company=profile.current_company,
            sector=profile.sector,
            photo_url=profile.photo_url,
            is_student=profile.is_student,
        )

    @staticmethod
    def _add_edge_to_graph(graph: nx.Graph, edge: EdgeRecord) -> None:
        if edge.source_id == edge.target_id:
            return
        prob = max(0.05, min(0.99, float(edge.probability)))

        if graph.has_edge(edge.source_id, edge.target_id):
            links: dict[str, dict] = dict(graph[edge.source_id][edge.target_id].get("links", {}))
        else:
            links = {}

        existing = links.get(edge.edge_type)
        if existing is None or prob >= existing["probability"]:
            links[edge.edge_type] = {"probability": prob, "reason": edge.reason}

        ordered = sorted(links.items(), key=lambda kv: kv[1]["probability"], reverse=True)
        best_type, best_info = ordered[0]
        best_prob = max(0.05, min(0.99, float(best_info["probability"])))
        secondary_reasons = [info["reason"] for _, info in ordered[1:]]

        graph.add_edge(
            edge.source_id,
            edge.target_id,
            links=links,
            edge_type=best_type,
            probability=best_prob,
            weight=-math.log(best_prob),
            reason=best_info["reason"],
            secondary_reasons=secondary_reasons,
        )

    def infer_edges_for_profile(
        self,
        profile: ProfileRecord,
        existing_profiles: Iterable[ProfileRecord],
    ) -> list[EdgeRecord]:
        """Infer company-overlap, association, and school-cohort edges for one profile."""
        inferred: list[EdgeRecord] = []

        my_exps: list[tuple[str, str, int, int]] = []
        for exp in profile.experiences:
            norm_comp = normalize_company(exp.get("company"))
            if not norm_comp:
                continue
            interval = parse_period_to_months(
                exp.get("start_date"),
                exp.get("end_date"),
                exp.get("period"),
            )
            if interval is not None:
                my_exps.append((norm_comp, exp.get("company", ""), interval[0], interval[1]))

        my_assos = {normalize_association(a): a for a in profile.associations if normalize_association(a)}

        for other in existing_profiles:
            if other.id == profile.id:
                continue
            src_id, dst_id = (profile.id, other.id) if profile.id < other.id else (other.id, profile.id)

            # 1. INFERRED_COMPANY (date overlap >= 1 month)
            best_company_edge: Optional[EdgeRecord] = None
            for norm_comp, display_comp, s1, e1 in my_exps:
                for o_exp in other.experiences:
                    if normalize_company(o_exp.get("company")) != norm_comp:
                        continue
                    o_int = parse_period_to_months(
                        o_exp.get("start_date"),
                        o_exp.get("end_date"),
                        o_exp.get("period"),
                    )
                    if o_int is None:
                        continue
                    overlap_start = max(s1, o_int[0])
                    overlap_end = min(e1, o_int[1])
                    overlap_months = overlap_end - overlap_start + 1
                    if overlap_months >= 1:
                        prob = round(min(0.75, 0.50 + 0.25 * min(overlap_months, 24) / 24.0), 4)
                        y_start = overlap_start // 12
                        y_end = overlap_end // 12
                        span = f"{y_start}" if y_start == y_end else f"{y_start}-{y_end}"
                        reason = f"Chevauchement chez {display_comp} ({span})"
                        if best_company_edge is None or prob > best_company_edge.probability:
                            best_company_edge = EdgeRecord(
                                source_id=src_id,
                                target_id=dst_id,
                                edge_type="INFERRED_COMPANY",
                                probability=prob,
                                reason=reason,
                            )
            if best_company_edge is not None:
                inferred.append(best_company_edge)

            # 2. INFERRED_ASSO (same student association + close cohorts <= 3 years)
            if my_assos and other.associations:
                other_assos = {normalize_association(a): a for a in other.associations if normalize_association(a)}
                shared_keys = set(my_assos.keys()) & set(other_assos.keys())
                promo_ok = (
                    profile.promo_year is None
                    or other.promo_year is None
                    or abs(profile.promo_year - other.promo_year) <= 3
                )
                if shared_keys and promo_ok:
                    shared_key = sorted(shared_keys)[0]
                    display_asso = my_assos[shared_key]
                    inferred.append(
                        EdgeRecord(
                            source_id=src_id,
                            target_id=dst_id,
                            edge_type="INFERRED_ASSO",
                            probability=0.65,
                            reason=f"Même asso {display_asso} à CentraleSupélec",
                        )
                    )

            # 3. INFERRED_SCHOOL (same CentraleSupélec cohort delta <= 1 year)
            if profile.promo_year is not None and other.promo_year is not None:
                if abs(profile.promo_year - other.promo_year) <= 1:
                    promo_label = (
                        str(profile.promo_year)
                        if profile.promo_year == other.promo_year
                        else f"{min(profile.promo_year, other.promo_year)}-{max(profile.promo_year, other.promo_year)}"
                    )
                    inferred.append(
                        EdgeRecord(
                            source_id=src_id,
                            target_id=dst_id,
                            edge_type="INFERRED_SCHOOL",
                            probability=0.35,
                            reason=f"Réseau CentraleSupélec (promo {promo_label})",
                        )
                    )

        return inferred

    def find_connection_paths(
        self,
        student_id: str,
        target_id: str,
        *,
        max_hops: int = 4,
        k_paths: int = 3,
    ) -> list[ConnectionPath]:
        """Find top-k highest-probability simple paths using Dijkstra / Yen (-ln(p))."""
        if student_id == target_id:
            return []

        with self._lock:
            if not self._graph.has_node(student_id) or not self._graph.has_node(target_id):
                return []

            results: list[ConnectionPath] = []
            try:
                generator = nx.shortest_simple_paths(
                    self._graph,
                    source=student_id,
                    target=target_id,
                    weight="weight",
                )
                # Inspect bounded number of candidate simple paths to respect max_hops
                for node_path in islice(generator, 40):
                    hop_count = len(node_path) - 1
                    if hop_count < 1 or hop_count > max_hops:
                        continue

                    hops: list[HopDetail] = []
                    total_weight = 0.0
                    for idx in range(hop_count):
                        u, v = node_path[idx], node_path[idx + 1]
                        edge_data = self._graph[u][v]
                        u_attrs = self._graph.nodes[u]
                        v_attrs = self._graph.nodes[v]
                        total_weight += float(edge_data["weight"])
                        hops.append(
                            HopDetail(
                                from_id=u,
                                from_name=u_attrs.get("full_name", u),
                                from_meta=_format_node_meta(u_attrs),
                                to_id=v,
                                to_name=v_attrs.get("full_name", v),
                                to_meta=_format_node_meta(v_attrs),
                                probability=round(float(edge_data["probability"]), 4),
                                edge_type=str(edge_data["edge_type"]),
                                reason=str(edge_data["reason"]),
                                secondary_reasons=list(edge_data.get("secondary_reasons", [])),
                            )
                        )

                    total_prob = round(math.exp(-total_weight), 4)
                    via = f"Via {hops[0].to_name}" if hop_count > 1 else f"Lien direct avec {hops[0].to_name}"
                    results.append(
                        ConnectionPath(
                            total_probability=total_prob,
                            hop_count=hop_count,
                            hops=hops,
                            summary_label=f"{via} ({hop_count} lien{'s' if hop_count > 1 else ''}, {total_prob:.0%})",
                        )
                    )
                    if len(results) >= k_paths:
                        break
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return []

            return results

    def get_neighborhood_ids(
        self,
        profile_id: str,
        *,
        max_hops: int = 2,
        exclude_ids: Optional[set[str]] = None,
    ) -> set[str]:
        """Return node IDs within 1..max_hops of profile_id without traversing exclude_ids."""
        blocked = exclude_ids or set()
        with self._lock:
            if not self._graph.has_node(profile_id):
                return set()
            visited: set[str] = {profile_id}
            frontier: set[str] = {profile_id}
            reached: set[str] = set()
            for _ in range(max(1, max_hops)):
                next_frontier: set[str] = set()
                for nid in frontier:
                    for nbr in self._graph.neighbors(nid):
                        if nbr in blocked or nbr in visited:
                            continue
                        visited.add(nbr)
                        reached.add(nbr)
                        next_frontier.add(nbr)
                frontier = next_frontier
                if not frontier:
                    break
            return reached

    def get_direct_neighbors(self, profile_id: str) -> list[tuple[str, float, str]]:
        """Return (neighbor_id, probability, reason) for direct edges, strongest first."""
        with self._lock:
            if not self._graph.has_node(profile_id):
                return []
            neighbors: list[tuple[str, float, str]] = []
            for neighbor_id in self._graph.neighbors(profile_id):
                edge_data = self._graph[profile_id][neighbor_id]
                neighbors.append(
                    (
                        str(neighbor_id),
                        round(float(edge_data.get("probability", 0.0)), 4),
                        str(edge_data.get("reason", "")),
                    )
                )
            neighbors.sort(key=lambda item: item[1], reverse=True)
            return neighbors

    def get_subgraph_for_paths(
        self,
        student_id: str,
        target_id: str,
        paths: list[ConnectionPath],
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Serialize nodes & edges for React Flow / react-force-graph visualization."""
        node_ids: list[str] = []
        seen_nodes: set[str] = set()
        seen_edges: dict[tuple[str, str], GraphEdge] = {}

        with self._lock:
            for path_idx, path in enumerate(paths):
                is_primary = path_idx == 0
                for hop in path.hops:
                    for nid in (hop.from_id, hop.to_id):
                        if nid not in seen_nodes:
                            seen_nodes.add(nid)
                            node_ids.append(nid)
                    pair = (hop.from_id, hop.to_id) if hop.from_id < hop.to_id else (hop.to_id, hop.from_id)
                    if pair not in seen_edges:
                        seen_edges[pair] = GraphEdge(
                            id=f"{hop.from_id}->{hop.to_id}",
                            source=hop.from_id,
                            target=hop.to_id,
                            edge_type=hop.edge_type,
                            probability=hop.probability,
                            reason=hop.reason,
                            secondary_reasons=hop.secondary_reasons,
                            is_primary=is_primary,
                        )
                    elif is_primary:
                        seen_edges[pair].is_primary = True

            nodes: list[GraphNode] = []
            for nid in node_ids:
                attrs = self._graph.nodes.get(nid, {})
                kind = "student" if nid == student_id else ("target" if nid == target_id else "hop")
                nodes.append(
                    GraphNode(
                        id=nid,
                        label=attrs.get("full_name", nid),
                        meta=_format_node_meta(attrs),
                        kind=kind,
                        promo_year=attrs.get("promo_year"),
                        company=attrs.get("current_company"),
                        role=attrs.get("current_role"),
                        photo_url=attrs.get("photo_url"),
                    )
                )
            return nodes, list(seen_edges.values())
