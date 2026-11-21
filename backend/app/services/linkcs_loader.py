"""Loader for LinkCS scraped student/alumni datasets (.json or .csv) without persisting PII into Git."""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.db.repository import EdgeRecord, ProfileRecord
from app.services.graph_engine import normalize_association
from app.services.linkedin_parser import decode_csv_bytes, normalize_linkedin_url
from app.services.llm import deterministic_text_embedding


def extract_asso_name(raw: str) -> str:
    """Strip '[Role (Period)]' suffixes from LinkCS association/club entries."""
    cleaned = re.sub(r"\s*\[.*$", "", str(raw or "")).strip()
    return cleaned


def _split_semicolon_field(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    if not val:
        return []
    return [part.strip() for part in str(val).split(";") if part.strip()]


def _parse_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(str(val).strip())
    except ValueError:
        return None


def _dedupe_clean_assos(raw_items: list[str]) -> list[tuple[str, str]]:
    """Return list of (normalized_key, display_name) deduplicated preserving order."""
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for raw in raw_items:
        display = extract_asso_name(raw)
        key = normalize_association(display)
        if key and key not in seen:
            seen.add(key)
            result.append((key, display))
    return result


def _build_bio(biographie: str, raw_assos: list[str], raw_clubs: list[str]) -> Optional[str]:
    parts: list[str] = []
    bio_clean = biographie.strip()
    if bio_clean:
        parts.append(bio_clean)
    combined = [item.strip() for item in (raw_assos + raw_clubs) if item.strip()]
    if combined:
        parts.append("Engagements CS : " + " ; ".join(combined))
    text = " | ".join(parts).strip()
    if not text:
        return None
    if len(text) > 500:
        return text[:497].rstrip() + "..."
    return text


def _read_linkcs_rows(path: Path) -> list[dict[str, Any]]:
    raw_bytes = path.read_bytes()
    if path.suffix.lower() == ".json":
        data = json.loads(decode_csv_bytes(raw_bytes))
        if not isinstance(data, list):
            raise ValueError("Le fichier LinkCS JSON doit contenir une liste d'objets.")
        return [dict(item) for item in data if isinstance(item, dict)]

    text = decode_csv_bytes(raw_bytes)
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def load_linkcs_dataset(
    file_path: str | Path,
    *,
    include_demo_student: bool = True,
    compute_embeddings: bool = True,
    embedding_dim: int = 768,
    max_group_size: int = 80,
) -> tuple[list[ProfileRecord], list[EdgeRecord]]:
    """Parse a LinkCS .json or .csv export into ProfileRecords and INFERRED_ASSO EdgeRecords."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier LinkCS introuvable: {path}")

    rows = _read_linkcs_rows(path)
    profiles: list[ProfileRecord] = []
    seen_ids: set[str] = set()
    seen_linkedin: set[str] = set()

    # Inverted buckets mapping norm_asso_key -> (display_name, [profile_id, ...])
    official_buckets: dict[str, tuple[str, list[str]]] = {}
    club_buckets: dict[str, tuple[str, list[str]]] = {}

    for row in rows:
        full_name = str(row.get("nom_complet") or "").strip()
        if not full_name:
            first = str(row.get("prenom") or "").strip()
            last = str(row.get("nom") or "").strip()
            full_name = f"{first} {last}".strip()
        if not full_name:
            continue

        login = str(row.get("login") or "").strip()
        uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"linkcs.{login or full_name}"))
        if uid in seen_ids:
            continue
        seen_ids.add(uid)

        promo_year = _parse_int(row.get("promotion"))

        email_etud = str(row.get("email_etudiant") or "").strip()
        all_emails = _split_semicolon_field(row.get("tous_les_emails"))
        perso_emails = _split_semicolon_field(row.get("emails_perso"))
        email = email_etud or (all_emails[0] if all_emails else (perso_emails[0] if perso_emails else None))

        linkedin_url: Optional[str] = None
        socials = row.get("reseaux_sociaux")
        if isinstance(socials, list):
            for entry in socials:
                s = str(entry)
                if "linkedin.com" in s.lower():
                    candidate_url = normalize_linkedin_url(s)
                    if candidate_url and candidate_url not in seen_linkedin:
                        linkedin_url = candidate_url
                        seen_linkedin.add(candidate_url)
                    break

        raw_official = _split_semicolon_field(row.get("associations"))
        raw_clubs = _split_semicolon_field(row.get("clubs_et_groupes"))
        official_pairs = _dedupe_clean_assos(raw_official)
        club_pairs = _dedupe_clean_assos(raw_clubs)

        merged_assos: list[str] = []
        merged_keys: set[str] = set()
        for key, display in official_pairs + club_pairs:
            if key not in merged_keys:
                merged_keys.add(key)
                merged_assos.append(display)

        raw_categories = _split_semicolon_field(row.get("categories_assos"))
        passions: list[str] = []
        seen_passions: set[str] = set()
        for cat in raw_categories:
            k = cat.lower().strip()
            if k and k not in seen_passions:
                seen_passions.add(k)
                passions.append(cat.strip())

        bio = _build_bio(str(row.get("biographie") or ""), raw_official, raw_clubs)
        edu_entry: dict[str, Any] = {"school": "CentraleSupélec", "degree": "Diplôme d'ingénieur"}
        if promo_year is not None:
            edu_entry["end_year"] = promo_year

        profile = ProfileRecord(
            id=uid,
            full_name=full_name,
            email=email,
            linkedin_url=linkedin_url,
            promo_year=promo_year,
            current_role=None,
            current_company=None,
            sector=None,
            location=None,
            bio=bio,
            experiences=[],
            education=[edu_entry],
            associations=merged_assos,
            passions=passions,
            is_student=False,
            has_imported_linkedin=False,
            enrichment_source="LINKCS_DB",
            last_enriched_at=None,
        )
        profiles.append(profile)

        for key, display in official_pairs:
            bucket = official_buckets.setdefault(key, (display, []))
            bucket[1].append(uid)
        for key, display in club_pairs:
            bucket = club_buckets.setdefault(key, (display, []))
            bucket[1].append(uid)

    edges_map: dict[tuple[str, str, str], EdgeRecord] = {}

    def _connect_bucket(buckets: dict[str, tuple[str, list[str]]], prob: float, prefix: str) -> None:
        for _, (display_name, member_ids) in buckets.items():
            if len(member_ids) < 2 or len(member_ids) > max_group_size:
                continue
            reason = f"{prefix} {display_name} à CentraleSupélec"
            for i, id_a in enumerate(member_ids):
                for id_b in member_ids[i + 1 :]:
                    src, dst = (id_a, id_b) if id_a < id_b else (id_b, id_a)
                    key = (src, dst, "INFERRED_ASSO")
                    existing = edges_map.get(key)
                    if existing is None or prob > existing.probability:
                        edges_map[key] = EdgeRecord(
                            source_id=src,
                            target_id=dst,
                            edge_type="INFERRED_ASSO",
                            probability=prob,
                            reason=reason,
                        )

    _connect_bucket(official_buckets, 0.70, "Même asso")
    _connect_bucket(club_buckets, 0.60, "Même club")

    if include_demo_student:
        demo_assos = [
            "BDS",
            "ViaRézo",
            "Raid CentraleSupélec",
            "Club Tech",
            "Genius CentraleSupélec",
            "Club Voile",
        ]
        demo_student = ProfileRecord(
            id="11111111-1111-4111-8111-111111111111",
            full_name="Léo Bernard",
            email="leo.bernard@student-cs.fr",
            linkedin_url="https://www.linkedin.com/in/leo-bernard-cs",
            promo_year=2026,
            current_role="Élève-ingénieur 2A",
            current_company="CentraleSupélec",
            sector="Étudiant",
            location="Gif-sur-Yvette",
            bio="Étudiant 2A à CentraleSupélec (BDS, ViaRézo, Raid CentraleSupélec, Club Tech, Club Voile).",
            experiences=[],
            education=[{"school": "CentraleSupélec", "degree": "Diplôme d'ingénieur", "end_year": 2026}],
            associations=demo_assos,
            passions=["trail", "Sports et plein air", "Sciences et techniques", "Entreprise"],
            is_student=True,
            has_imported_linkedin=True,
            enrichment_source="BASE_DB",
            last_enriched_at=datetime.now(timezone.utc),
        )
        profiles.insert(0, demo_student)

        combined_buckets: dict[str, tuple[str, list[str]]] = {}
        for k, (disp, ids) in official_buckets.items():
            combined_buckets[k] = (disp, list(ids))
        for k, (disp, ids) in club_buckets.items():
            if k in combined_buckets:
                existing_disp, existing_ids = combined_buckets[k]
                merged_ids = list(dict.fromkeys(existing_ids + ids))
                combined_buckets[k] = (existing_disp, merged_ids)
            else:
                combined_buckets[k] = (disp, list(ids))

        for asso in demo_assos:
            norm_k = normalize_association(asso)
            bucket = combined_buckets.get(norm_k)
            if not bucket:
                continue
            disp_name, member_ids = bucket
            for rep_id in member_ids[:4]:
                src, dst = (demo_student.id, rep_id) if demo_student.id < rep_id else (rep_id, demo_student.id)
                key = (src, dst, "INFERRED_ASSO")
                edges_map.setdefault(
                    key,
                    EdgeRecord(
                        source_id=src,
                        target_id=dst,
                        edge_type="INFERRED_ASSO",
                        probability=0.65,
                        reason=f"Même asso {disp_name} à CentraleSupélec",
                    ),
                )

    if compute_embeddings:
        for prof in profiles:
            prof.embedding = deterministic_text_embedding(prof.searchable_text(), dim=embedding_dim)

    return profiles, list(edges_map.values())
