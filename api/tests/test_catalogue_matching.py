"""Catalogue name resolution — pure, no DB. Resource() objects here are never
persisted; match_by_name() only reads their .name attribute in memory."""

from app.features.resources.service import match_by_name
from app.models.resources import Resource


def _catalogue() -> list[Resource]:
    return [
        Resource(name="Projector", category="AV", quantity_total=1, exclusive=True),
        Resource(name="Wireless mic", category="AV", quantity_total=4),
        Resource(name="Folding chair", category="furniture", quantity_total=120),
    ]


def test_exact_match():
    resource = match_by_name(_catalogue(), "Projector")
    assert resource is not None
    assert resource.name == "Projector"


def test_case_insensitive_match():
    resource = match_by_name(_catalogue(), "PROJECTOR")
    assert resource is not None
    assert resource.name == "Projector"


def test_no_match_returns_none():
    assert match_by_name(_catalogue(), "Bouncy castle") is None


def test_empty_catalogue_returns_none():
    assert match_by_name([], "Projector") is None
