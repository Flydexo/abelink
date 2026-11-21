"""Read the v1 export_import_bundle.py JSON format one record at a time."""

import json
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from io import TextIOWrapper
from math import isfinite
from uuid import UUID

from pydantic import ConfigDict, TypeAdapter

from app.db.repository import EdgeRecord, ProfileRecord
from app.schemas.profile import Education, Experience

READ_CHARS = 64 * 1024
MAX_RECORD_CHARS = 2 * 1024 * 1024
JSON_WHITESPACE = re.compile(r"[ \t\r\n]*")


class BundleProfile(ProfileRecord):
    __pydantic_config__ = ConfigDict(extra="forbid")


class BundleEdge(EdgeRecord):
    __pydantic_config__ = ConfigDict(extra="forbid")


PROFILE = TypeAdapter(BundleProfile)
EDGE = TypeAdapter(BundleEdge)


class BundleError(ValueError):
    """A safe error to show without exposing any record content."""


def reject_constant(_value: str) -> None:
    raise BundleError("Le fichier contient une valeur JSON non valide.")


class BundleReader:
    def __init__(self, stream: TextIOWrapper):
        self.stream = stream
        self.decoder = json.JSONDecoder(parse_constant=reject_constant)
        self.buffer = ""
        self.position = 0

    def _fill(self) -> bool:
        chunk = self.stream.read(READ_CHARS)
        self.buffer = self.buffer[self.position:] + chunk
        self.position = 0
        return bool(chunk)

    def _peek(self) -> str:
        while True:
            self.position = JSON_WHITESPACE.match(self.buffer, self.position).end()
            if self.position < len(self.buffer):
                return self.buffer[self.position]
            if not self._fill():
                return ""

    def _expect(self, char: str) -> None:
        if self._peek() != char:
            raise BundleError("Le fichier doit être un export Abelink JSON v1 valide.")
        self.position += 1

    def _value(self):
        self._peek()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.position)
            except json.JSONDecodeError:
                if len(self.buffer) - self.position >= MAX_RECORD_CHARS or not self._fill():
                    raise BundleError("Le fichier contient du JSON invalide ou une entrée trop volumineuse.") from None
            else:
                if end - self.position > MAX_RECORD_CHARS:
                    raise BundleError("Une entrée du fichier est trop volumineuse.")
                self.position = end
                return value

    def _field(self, name: str) -> None:
        if self._peek() != '"' or self._value() != name:
            raise BundleError("Structure inattendue : utilisez le fichier JSON original exporté par Abelink.")
        self._expect(":")

    def _records(self, name: str) -> Iterator[dict]:
        self._field(name)
        self._expect("[")
        if self._peek() != "]":
            while True:
                if self._peek() != "{":
                    raise BundleError(f"La liste {name} doit uniquement contenir des objets.")
                yield self._value()
                if self._peek() != ",":
                    break
                self.position += 1
        self._expect("]")

    def records(self) -> Iterator[ProfileRecord | EdgeRecord]:
        try:
            self._expect("{")
            self._field("version")
            if self._peek() != "1":
                raise BundleError("Seuls les exports Abelink v1 sont pris en charge.")
            self.position += 1
            self._expect(",")
            for index, values in enumerate(self._records("profiles"), 1):
                try:
                    yield parse_profile(values)
                except (ValueError, TypeError, OverflowError):
                    raise BundleError(f"Profil {index} : champs invalides dans l’export Abelink.") from None
            self._expect(",")
            for index, values in enumerate(self._records("edges"), 1):
                try:
                    yield parse_edge(values)
                except (ValueError, TypeError, OverflowError):
                    raise BundleError(f"Relation {index} : champs invalides dans l’export Abelink.") from None
            self._expect("}")
            if self._peek():
                raise BundleError("Données inattendues après la fin de l’export Abelink.")
        except (UnicodeError, RecursionError):
            raise BundleError("Le fichier doit contenir du JSON UTF-8 valide.") from None


def parse_profile(values: dict) -> ProfileRecord:
    if (stamp := values.get("last_enriched_at")) is not None:
        if not isinstance(stamp, str):
            raise ValueError
        parsed = datetime.fromisoformat(stamp)
        values["last_enriched_at"] = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    for key in ("is_student", "has_imported_linkedin"):
        if key in values and type(values[key]) is not bool:
            raise ValueError
    profile = PROFILE.validate_python(values)
    profile.id = str(UUID(profile.id))
    if not profile.full_name.strip():
        raise ValueError
    for experience in profile.experiences:
        Experience.model_validate(experience)
    for education in profile.education:
        Education.model_validate(education)
    if profile.embedding is not None and (
        len(profile.embedding) != 768 or not all(isfinite(value) and abs(value) <= 3.4028234663852886e38 for value in profile.embedding)
    ):
        raise ValueError
    return profile


def parse_edge(values: dict) -> EdgeRecord:
    if type(values.get("probability")) not in (int, float):
        raise ValueError
    edge = EDGE.validate_python(values)
    edge.source_id = str(UUID(edge.source_id))
    edge.target_id = str(UUID(edge.target_id))
    if edge.id is not None:
        edge.id = str(UUID(edge.id))
    if edge.source_id == edge.target_id or not 0.05 <= edge.probability <= 0.99 or not edge.edge_type.strip():
        raise ValueError
    return edge
