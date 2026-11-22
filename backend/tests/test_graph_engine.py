"""Unit tests for probabilistic GraphEngine (Dijkstra -ln(p), parallel links, inference)."""

import math

from app.db.repository import EdgeRecord, ProfileRecord
from app.services.graph_engine import GraphEngine


def test_dijkstra_prefers_higher_probability_over_fewer_hops():
    engine = GraphEngine()
    profiles = [
        ProfileRecord(id="student_leo", full_name="Léo Bernard", is_student=True),
        ProfileRecord(id="alumni_thomas", full_name="Thomas Leroy"),
        ProfileRecord(id="alumni_claire", full_name="Claire Moreau"),
        ProfileRecord(id="alumni_sarah", full_name="Sarah Cohen"),
        ProfileRecord(id="alumni_alice", full_name="Alice Martin"),
    ]
    edges = [
        # 3-hop path: 0.95 * 0.55 * 0.72 = 0.3762
        EdgeRecord("student_leo", "alumni_thomas", "EXPLICIT_LINKEDIN", 0.95, "Connexion LinkedIn directe"),
        EdgeRecord("alumni_thomas", "alumni_claire", "INFERRED_ASSO", 0.55, "Même asso BDS"),
        EdgeRecord("alumni_claire", "alumni_alice", "INFERRED_COMPANY", 0.72, "Chevauchement chez Doctolib"),
        # 2-hop path: 0.35 * 0.60 = 0.2100
        EdgeRecord("student_leo", "alumni_sarah", "INFERRED_SCHOOL", 0.35, "Réseau CentraleSupélec"),
        EdgeRecord("alumni_sarah", "alumni_alice", "INFERRED_ASSO", 0.60, "Même asso Junior CentraleSupélec"),
    ]
    engine.reload(profiles, edges)

    paths = engine.find_connection_paths("student_leo", "alumni_alice", max_hops=4, k_paths=3)
    assert len(paths) == 2

    best = paths[0]
    alt = paths[1]
    assert best.hop_count == 3
    assert math.isclose(best.total_probability, 0.95 * 0.55 * 0.72, rel_tol=1e-3)
    assert [h.to_id for h in best.hops] == ["alumni_thomas", "alumni_claire", "alumni_alice"]
    assert best.hops[0].reason == "Connexion LinkedIn directe"

    assert alt.hop_count == 2
    assert math.isclose(alt.total_probability, 0.35 * 0.60, rel_tol=1e-3)


def test_parallel_edges_preserve_strongest_link_and_secondary_reasons():
    engine = GraphEngine()
    p1 = ProfileRecord(id="a", full_name="Léo")
    p2 = ProfileRecord(id="b", full_name="Thomas")
    # Weak edge added after strong edge must not overwrite 0.95!
    engine.reload(
        [p1, p2],
        [
            EdgeRecord("a", "b", "EXPLICIT_LINKEDIN", 0.95, "Connexion LinkedIn directe"),
            EdgeRecord("a", "b", "INFERRED_SCHOOL", 0.35, "Réseau CentraleSupélec (promo 2023)"),
        ],
    )

    paths = engine.find_connection_paths("a", "b")
    assert len(paths) == 1
    hop = paths[0].hops[0]
    assert hop.probability == 0.95
    assert hop.edge_type == "EXPLICIT_LINKEDIN"
    assert hop.reason == "Connexion LinkedIn directe"
    assert "Réseau CentraleSupélec (promo 2023)" in hop.secondary_reasons


def test_max_hops_filters_out_longer_paths():
    engine = GraphEngine()
    profiles = [ProfileRecord(id=str(i), full_name=f"User {i}") for i in range(5)]
    edges = [
        EdgeRecord("0", "1", "EXPLICIT_LINKEDIN", 0.95, "hop1"),
        EdgeRecord("1", "2", "EXPLICIT_LINKEDIN", 0.95, "hop2"),
        EdgeRecord("2", "3", "EXPLICIT_LINKEDIN", 0.95, "hop3"),
        EdgeRecord("3", "4", "EXPLICIT_LINKEDIN", 0.95, "hop4"),
    ]
    engine.reload(profiles, edges)

    assert engine.find_connection_paths("0", "4", max_hops=3) == []
    assert len(engine.find_connection_paths("0", "4", max_hops=4)) == 1


def test_infer_edges_for_profile_company_asso_and_school():
    engine = GraphEngine()
    claire = ProfileRecord(
        id="claire",
        full_name="Claire Moreau",
        promo_year=2019,
        experiences=[{"company": "Doctolib", "role": "PM", "start_date": "2019-10", "end_date": "2023-06"}],
        associations=["BDS"],
    )
    alice = ProfileRecord(
        id="alice",
        full_name="Alice Martin",
        promo_year=2020,
        experiences=[{"company": "Doctolib SAS", "role": "ML Engineer", "start_date": "2020-06", "end_date": "2023-04"}],
        associations=["BDS"],
    )
    unrelated = ProfileRecord(
        id="unrelated",
        full_name="Pierre Dupuis",
        promo_year=2010,
        experiences=[{"company": "Doctolib", "role": "Dev", "start_date": "2015-01", "end_date": "2018-01"}],
        associations=["BDS"],
    )

    inferred = engine.infer_edges_for_profile(claire, [alice, unrelated])
    by_type = {(e.source_id, e.target_id, e.edge_type): e for e in inferred}

    assert ("alice", "claire", "INFERRED_COMPANY") in by_type
    assert by_type[("alice", "claire", "INFERRED_COMPANY")].probability == 0.75
    assert ("alice", "claire", "INFERRED_ASSO") in by_type
    assert by_type[("alice", "claire", "INFERRED_ASSO")].probability == 0.65
    assert ("alice", "claire", "INFERRED_SCHOOL") in by_type
    assert by_type[("alice", "claire", "INFERRED_SCHOOL")].probability == 0.35

    # No company overlap and promo delta > 3 with `unrelated`
    assert not any(e.source_id == "unrelated" or e.target_id == "unrelated" for e in inferred)
