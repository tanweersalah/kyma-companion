import json
from enum import StrEnum

from pydantic import BaseModel


class SourceType(StrEnum):
    """Enum for the documents source type."""

    GITHUB = "Github"


class DocumentsSource(BaseModel):
    """Model for the documents source."""

    name: str
    source_type: SourceType
    url: str
    include_files: list[str] | None = None
    exclude_files: list[str] | None = None
    filter_file_types: list[str] = ["md"]


def get_documents_sources(path: str) -> list[DocumentsSource]:
    """Reads the documents sources from the json file."""
    sources = []
    with open(path) as f:
        json_obj = json.load(f)
        for item in json_obj:
            sources.append(DocumentsSource(**item))
    return sources
