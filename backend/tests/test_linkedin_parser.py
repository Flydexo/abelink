"""Unit tests for LinkedIn archive (.zip / .csv) parsing and matching."""

import io
import zipfile

from app.db.repository import ProfileRecord
from app.services.linkedin_parser import (
    build_profile_lookup_indexes,
    match_connection_to_profile,
    normalize_linkedin_url,
    parse_linkedin_archive,
)


def _make_sample_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # LinkedIn Connections.csv with 3 disclaimer lines + UTF-8 BOM
        connections_csv = (
            "\ufeffNotes:\n"
            "\"When exporting your connections, some fields may be omitted.\"\n"
            "\n"
            "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
            "Thomas,Leroy,https://fr.linkedin.com/in/thomas-leroy/?trk=nav_type,thomas@ekimetrics.com,Ekimetrics,Data Scientist,12 Jan 2025\n"
            "Alice,Martin,,alice@mistral.ai,Mistral AI,Lead ML Engineer,03 Feb 2025\n"
            "Jean,Dupont,,,Ambiguous Corp,Engineer,04 Feb 2025\n"
        )
        positions_csv = (
            "Company Name,Title,Description,Location,Started On,Finished On\n"
            "Ekimetrics,Stagiaire Data,Data science,Paris,Jun 2025,Sep 2025\n"
        )
        education_csv = (
            "School Name,Start Date,End Date,Notes,Degree Name,Activities and Societies\n"
            "CentraleSupélec,2023,2026,,Diplôme d'ingénieur,BDS\n"
        )
        zf.writestr("LinkedInExport/Connections.csv", connections_csv.encode("utf-8"))
        zf.writestr("LinkedInExport/Positions.csv", positions_csv.encode("utf-8"))
        zf.writestr("LinkedInExport/Education.csv", education_csv.encode("utf-8"))
        zf.writestr("__MACOSX/._Connections.csv", b"junk")
    return buf.getvalue()


def test_normalize_linkedin_url():
    assert (
        normalize_linkedin_url("https://fr.linkedin.com/in/Alice-Martin/?utm_source=share#top")
        == "https://www.linkedin.com/in/alice-martin"
    )
    assert normalize_linkedin_url("linkedin.com/in/leo-bernard/") == "https://www.linkedin.com/in/leo-bernard"
    assert normalize_linkedin_url("   ") is None


def test_parse_linkedin_zip_with_preamble_bom_and_nested_files():
    parsed = parse_linkedin_archive(_make_sample_zip(), filename="Basic_LinkedInDataExport.zip")
    assert len(parsed.connections) == 3
    assert parsed.connections[0].full_name == "Thomas Leroy"
    assert parsed.connections[0].linkedin_url == "https://www.linkedin.com/in/thomas-leroy"
    assert len(parsed.experiences) == 1
    assert parsed.experiences[0].company == "Ekimetrics"
    assert len(parsed.educations) == 1
    assert parsed.promo_year_inferred == 2026


def test_parse_standalone_connections_csv_with_cp1252():
    csv_text = (
        "Notes:\n"
        "Export LinkedIn\n\n"
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        "Léa,Benoit,https://www.linkedin.com/in/lea-benoit/,lea@engie.com,Engie,Chargée de projet,2024\n"
    ).encode("cp1252")
    parsed = parse_linkedin_archive(csv_text, filename="Connections.csv")
    assert len(parsed.connections) == 1
    assert parsed.connections[0].full_name == "Léa Benoit"
    assert parsed.connections[0].linkedin_url == "https://www.linkedin.com/in/lea-benoit"


def test_match_connection_exact_url_and_ambiguous_fallback():
    profiles = [
        ProfileRecord(
            id="p_thomas",
            full_name="Thomas Leroy",
            linkedin_url="https://www.linkedin.com/in/thomas-leroy",
            current_company="Ekimetrics",
        ),
        ProfileRecord(
            id="p_alice",
            full_name="Alice Martin",
            linkedin_url=None,
            current_company="Mistral AI",
        ),
        ProfileRecord(id="p_dup1", full_name="Jean Dupont", current_company="Ambiguous Corp"),
        ProfileRecord(id="p_dup2", full_name="Jean Dupont", current_company="Ambiguous Corp"),
    ]
    by_url, by_name_company = build_profile_lookup_indexes(profiles)
    parsed = parse_linkedin_archive(_make_sample_zip(), filename="export.zip")

    m0 = match_connection_to_profile(parsed.connections[0], by_url, by_name_company)
    m1 = match_connection_to_profile(parsed.connections[1], by_url, by_name_company)
    m2 = match_connection_to_profile(parsed.connections[2], by_url, by_name_company)

    assert m0 is not None and m0.id == "p_thomas"
    assert m1 is not None and m1.id == "p_alice"
    # Ambiguous (2 profiles with same name & company) must NOT guess
    assert m2 is None
