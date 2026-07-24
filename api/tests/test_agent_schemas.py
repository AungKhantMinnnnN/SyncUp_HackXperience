"""Agent output validation — pure, no network, no DB. Confirms the schema the model
must conform to, and specifically that a model-emitted ID can never do anything: the
schema has no id-like field at all, and unknown fields are silently dropped rather
than accepted."""

import pytest
from pydantic import ValidationError

from app.features.resources.agent import InferredPackingItem, InferredPackingList


def test_valid_item_parses():
    item = InferredPackingItem(name="Projector", quantity=1, category="AV")
    assert item.name == "Projector"
    assert item.quantity == 1
    assert item.reasoning is None


def test_valid_list_parses():
    raw = '{"items": [{"name": "Projector", "quantity": 1}, {"name": "Chair", "quantity": 50}]}'
    parsed = InferredPackingList.model_validate_json(raw)
    assert len(parsed.items) == 2
    assert parsed.items[0].name == "Projector"


def test_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        InferredPackingItem(quantity=1)  # missing name


def test_unknown_fields_are_dropped_not_trusted():
    # A model that tries to emit its own "resource_id" or "id" must not be able to —
    # there's no such field on the schema, and extras are silently ignored rather
    # than smuggled through as an attribute.
    item = InferredPackingItem(name="Projector", quantity=1, id="fake-id-from-model", resource_id="also-fake")
    assert not hasattr(item, "id")
    assert not hasattr(item, "resource_id")


def test_estimated_unit_cost_is_optional():
    item = InferredPackingItem(name="Extension cord", quantity=2)
    assert item.estimated_unit_cost is None
