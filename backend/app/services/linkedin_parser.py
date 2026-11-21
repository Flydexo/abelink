"""Robust parser for official LinkedIn export archives (.zip or Connections.csv)."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from app.db.repository import ProfileRecord
from app.schemas.profile import Education, Experience
from app.services.graph_engine import normalize_company, strip_accents


@dataclass
class LinkedInConnection:
    first_name: str
    last_name: str
    full_name: str
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    connected_on: Optional[str] = None


@dataclass
class ParsedLinkedInArchive:
    connections: list[LinkedInConnection] = field(default_factory=list)
    experiences: list[Experience] = field(default_factory=list)
    educations: list[Education] = field(default_factory=list)
    promo_year_inferred: Optional[int] = None
    full_name_inferred: Optional[str] = None
    headline_inferred: Optional[str] = None


def decode_csv_bytes(data: bytes) -> str:
    """Decode CSV bytes trying UTF-8 BOM, UTF-8, CP1252, and Latin-1."""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def normalize_linkedin_url(url: Optional[str]) -> Optional[str]:
    """Canonicalize a LinkedIn profile URL to https://www.linkedin.com/in/<slug>."""
    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw.lstrip("/")
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if not host:
        return None
    path = parsed.path.rstrip("/")
    match = re.search(r"/in/([^/]+)", path, flags=re.IGNORECASE)
    if match:
        slug = match.group(1).strip().lower()
        return f"https://www.linkedin.com/in/{slug}"
    if "linkedin.com" in host:
        return f"https://www.linkedin.com{path.lower()}"
    return f"{parsed.scheme.lower()}://{host}{path}"


def _norm_header(cell: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(cell).lower()).strip()


def _parse_csv_with_header_detection(
    text: str,
    known_headers: set[str],
    min_matches: int = 2,
) -> list[dict[str, str]]:
    """Skip LinkedIn disclaimer/Notes lines and parse CSV starting at the real header row."""
    if not text.strip():
        return []
    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    header_idx: Optional[int] = None
    for idx, row in enumerate(rows[:15]):
        norm_cells = {_norm_header(c) for c in row if c and c.strip()}
        if len(norm_cells & known_headers) >= min_matches:
            header_idx = idx
            break
    if header_idx is None:
        return []

    headers = [_norm_header(h) for h in rows[header_idx]]
    records: list[dict[str, str]] = []
    for row in rows[header_idx + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        item: dict[str, str] = {}
        for col_idx, header in enumerate(headers):
            if not header:
                continue
            item[header] = row[col_idx].strip() if col_idx < len(row) else ""
        records.append(item)
    return records


def _pick(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        val = row.get(key, "")
        if val and val.strip():
            return val.strip()
    return ""


def _extract_year(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    m = re.search(r"(19\d{2}|20\d{2})", raw)
    return int(m.group(1)) if m else None


def parse_connections_csv(data: bytes) -> list[LinkedInConnection]:
    text = decode_csv_bytes(data)
    known = {
        "first name", "last name", "url", "email address", "company", "position", "connected on",
        "prenom", "nom", "adresse e-mail", "entreprise", "poste", "date de connexion",
    }
    rows = _parse_csv_with_header_detection(text, known, min_matches=2)
    connections: list[LinkedInConnection] = []
    for row in rows:
        first = _pick(row, "first name", "prenom")
        last = _pick(row, "last name", "nom")
        full = f"{first} {last}".strip()
        if not full:
            continue
        connections.append(
            LinkedInConnection(
                first_name=first,
                last_name=last,
                full_name=full,
                linkedin_url=normalize_linkedin_url(_pick(row, "url", "profile url", "linkedin url")),
                email=_pick(row, "email address", "adresse e-mail") or None,
                company=_pick(row, "company", "entreprise") or None,
                position=_pick(row, "position", "poste", "title") or None,
                connected_on=_pick(row, "connected on", "date de connexion") or None,
            )
        )
    return connections


def parse_positions_csv(data: bytes) -> list[Experience]:
    text = decode_csv_bytes(data)
    known = {
        "company name", "title", "started on", "finished on",
        "nom de l'entreprise", "poste", "date de debut", "date de fin",
    }
    rows = _parse_csv_with_header_detection(text, known, min_matches=2)
    experiences: list[Experience] = []
    for row in rows:
        company = _pick(row, "company name", "nom de l'entreprise", "company")
        role = _pick(row, "title", "poste", "position")
        if not company and not role:
            continue
        start_date = _pick(row, "started on", "date de debut") or None
        end_date = _pick(row, "finished on", "date de fin") or None
        period = None
        if start_date or end_date:
            period = f"{start_date or '?'} - {end_date or 'Present'}"
        experiences.append(
            Experience(
                company=company or "Entreprise inconnue",
                role=role or "Membre",
                start_date=start_date,
                end_date=end_date,
                period=period,
            )
        )
    return experiences


def parse_education_csv(data: bytes) -> tuple[list[Education], Optional[int]]:
    text = decode_csv_bytes(data)
    known = {
        "school name", "degree name", "start date", "end date",
        "nom de l'ecole", "diplome", "date de debut", "date de fin",
    }
    rows = _parse_csv_with_header_detection(text, known, min_matches=2)
    educations: list[Education] = []
    promo_year: Optional[int] = None
    for row in rows:
        school = _pick(row, "school name", "nom de l'ecole", "school")
        if not school:
            continue
        degree = _pick(row, "degree name", "diplome", "degree") or None
        start_year = _extract_year(_pick(row, "start date", "date de debut"))
        end_year = _extract_year(_pick(row, "end date", "date de fin"))
        educations.append(
            Education(
                school=school,
                degree=degree,
                start_year=start_year,
                end_year=end_year,
            )
        )
        school_norm = strip_accents(school).lower()
        if ("centralesupelec" in school_norm or "centrale" in school_norm or "supelec" in school_norm) and end_year:
            promo_year = end_year
    return educations, promo_year


def parse_linkedin_archive(file_bytes: bytes, filename: str = "archive.zip") -> ParsedLinkedInArchive:
    """Parse an official LinkedIn ZIP archive or standalone Connections.csv."""
    result = ParsedLinkedInArchive()
    lower_name = (filename or "").lower()

    is_zip = lower_name.endswith(".zip") or file_bytes[:4] == b"PK\x03\x04"
    if not is_zip:
        result.connections = parse_connections_csv(file_bytes)
        return result

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        members: dict[str, str] = {}
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            basename = name.rsplit("/", 1)[-1]
            if basename.startswith("._") or "__MACOSX" in name:
                continue
            members[basename.lower()] = name

        if "connections.csv" in members:
            result.connections = parse_connections_csv(zf.read(members["connections.csv"]))
        if "positions.csv" in members:
            result.experiences = parse_positions_csv(zf.read(members["positions.csv"]))
        if "education.csv" in members:
            edus, promo = parse_education_csv(zf.read(members["education.csv"]))
            result.educations = edus
            result.promo_year_inferred = promo
        if "profile.csv" in members:
            prof_rows = _parse_csv_with_header_detection(
                decode_csv_bytes(zf.read(members["profile.csv"])),
                {"first name", "last name", "headline", "prenom", "nom"},
                min_matches=2,
            )
            if prof_rows:
                first = _pick(prof_rows[0], "first name", "prenom")
                last = _pick(prof_rows[0], "last name", "nom")
                full = f"{first} {last}".strip()
                if full:
                    result.full_name_inferred = full
                result.headline_inferred = _pick(prof_rows[0], "headline", "titre") or None

    return result


def build_profile_lookup_indexes(
    profiles: list[ProfileRecord],
) -> tuple[dict[str, ProfileRecord], dict[tuple[str, str], list[ProfileRecord]]]:
    """Build exact URL index and (normalized_name, normalized_company) index."""
    by_url: dict[str, ProfileRecord] = {}
    by_name_company: dict[tuple[str, str], list[ProfileRecord]] = {}

    for prof in profiles:
        norm_url = normalize_linkedin_url(prof.linkedin_url)
        if norm_url:
            by_url[norm_url] = prof
        norm_name = re.sub(r"\s+", " ", strip_accents(prof.full_name).lower()).strip()
        norm_comp = normalize_company(prof.current_company)
        if norm_name and norm_comp:
            by_name_company.setdefault((norm_name, norm_comp), []).append(prof)

    return by_url, by_name_company


def match_connection_to_profile(
    conn: LinkedInConnection,
    by_url: dict[str, ProfileRecord],
    by_name_company: dict[tuple[str, str], list[ProfileRecord]],
) -> Optional[ProfileRecord]:
    """Match a LinkedIn contact by canonical URL first, then unambiguous (name, company)."""
    if conn.linkedin_url and conn.linkedin_url in by_url:
        return by_url[conn.linkedin_url]

    norm_name = re.sub(r"\s+", " ", strip_accents(conn.full_name).lower()).strip()
    norm_comp = normalize_company(conn.company)
    if norm_name and norm_comp:
        candidates = by_name_company.get((norm_name, norm_comp), [])
        if len(candidates) == 1:
            return candidates[0]
    return None
