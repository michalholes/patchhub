"""Tests for OpenLibrary author/title validation helpers."""

from __future__ import annotations

import asyncio
from typing import Any

from plugins.metadata_openlibrary.plugin import OpenLibraryPlugin


class _FakeOpenLibrary(OpenLibraryPlugin):
    def __init__(
        self,
        docs: list[dict[str, Any]],
        googlebooks_items: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.docs = docs
        self.googlebooks_items = googlebooks_items or []
        self.urls: list[str] = []
        self.googlebooks_queries: list[tuple[str, int]] = []

    async def _api_request(self, url: str) -> dict[str, Any]:
        self.urls.append(url)
        return {"docs": self.docs}

    async def _googlebooks_request(self, *, query: str, limit: int) -> dict[str, Any]:
        self.googlebooks_queries.append((query, limit))
        return {"items": self.googlebooks_items}


def test_validate_author_is_diacritics_safe_and_suppresses_noop_suggestion() -> None:
    plugin = _FakeOpenLibrary(
        docs=[
            {
                "author_name": [
                    "Jozef Ciger Hronsky",
                    "Jozef C\u00edger Hronsk\u00fd",
                ]
            }
        ]
    )

    result = asyncio.run(plugin.validate_author("Jozef Ciger Hronsky"))

    assert result == {
        "valid": True,
        "canonical": "Jozef Ciger Hronsky",
        "suggestion": None,
    }
    assert plugin.urls == [
        "https://openlibrary.org/search.json?author=Jozef+Ciger+Hronsky&limit=20"
    ]


def test_validate_book_is_diacritics_safe_and_lookup_returns_metadata() -> None:
    plugin = _FakeOpenLibrary(
        docs=[
            {
                "key": "/works/OL1W",
                "title": "P\u00edsali\u010dek",
                "author_name": ["Jozef C\u00edger Hronsk\u00fd"],
                "first_publish_year": 1934,
                "publisher": ["Matica"],
                "isbn": ["1234567890"],
                "language": ["slk"],
                "cover_i": 42,
                "subject": ["children"],
                "ebook_access": "borrowable",
            },
            {
                "key": "/works/OL2W",
                "title": "Ina Kniha",
                "author_name": ["Ina Autorka"],
            },
        ]
    )

    result = asyncio.run(plugin.validate_book("Jozef Ciger Hronsky", "Pisalicek"))
    metadata = asyncio.run(plugin.lookup_book("Jozef Ciger Hronsky", "Pisalicek"))

    assert result == {
        "valid": True,
        "canonical": {
            "author": "Jozef C\u00edger Hronsk\u00fd",
            "title": "P\u00edsali\u010dek",
        },
        "suggestion": None,
    }
    assert metadata == {
        "title": "P\u00edsali\u010dek",
        "authors": ["Jozef C\u00edger Hronsk\u00fd"],
        "author": "Jozef C\u00edger Hronsk\u00fd",
        "year": 1934,
        "publisher": "Matica",
        "isbn": "1234567890",
        "language": "slk",
        "cover_url": "https://covers.openlibrary.org/b/id/42-L.jpg",
        "subjects": ["children"],
        "ebook_access": "borrowable",
    }


def test_validate_book_returns_deterministic_suggestion() -> None:
    plugin = _FakeOpenLibrary(
        docs=[
            {
                "key": "/works/OL3W",
                "title": "Harry Potter and the Philosopher's Stone",
                "author_name": ["J. K. Rowling"],
            },
            {
                "key": "/works/OL4W",
                "title": "Harry Potter and the Chamber of Secrets",
                "author_name": ["J. K. Rowling"],
            },
        ]
    )

    result = asyncio.run(
        plugin.validate_book("J. K. Roling", "Harry Potter and the Philosopher Stone")
    )

    assert result == {
        "valid": False,
        "canonical": None,
        "suggestion": {
            "author": "J. K. Rowling",
            "title": "Harry Potter and the Philosopher's Stone",
        },
    }


def test_validate_book_uses_googlebooks_title_fallback_when_openlibrary_misses() -> None:
    plugin = _FakeOpenLibrary(
        docs=[],
        googlebooks_items=[
            {
                "id": "gb2",
                "volumeInfo": {
                    "title": "Harry Potter and the Chamber of Secrets",
                    "authors": ["J. K. Rowling"],
                },
            },
            {
                "id": "gb1",
                "volumeInfo": {
                    "title": "Harry Potter and the Philosopher's Stone",
                    "authors": ["J. K. Rowling"],
                },
            },
        ],
    )

    result = asyncio.run(
        plugin.validate_book("J. K. Rowling", "Harry Potter and the Philosopher Stone")
    )

    assert result == {
        "valid": False,
        "canonical": None,
        "suggestion": {
            "author": "J. K. Rowling",
            "title": "Harry Potter and the Philosopher's Stone",
        },
    }
    assert plugin.googlebooks_queries == [
        (
            "inauthor:J. K. Rowling+intitle:Harry Potter and the Philosopher Stone",
            20,
        )
    ]
