import json

import pytest

from app.services.experiments import parse_design


def _payload(data_to_collect):
    return json.dumps({
        "experiments": [{
            "title": "Paid pilot",
            "objective": "Test willingness to pay",
            "method": "Offer a paid pilot",
            "success_criteria": "At least 5 paid signups",
            "failure_criteria": "No paid signups",
            "data_to_collect": data_to_collect,
        }]
    })


def test_structured_measurement_fields_are_normalized_and_persistable():
    result = parse_design(_payload([
        {"field": "paid_signups", "description": "Number of people who paid", "unit": "people"},
        {"field": "repeat_orders", "description": "Orders placed again", "unit": "orders"},
    ]))
    fields = json.loads(result[0]["data_to_collect"])
    assert fields[0]["field"] == "paid_signups"
    assert fields[1]["unit"] == "orders"


def test_legacy_measurement_text_remains_backward_compatible():
    result = parse_design(_payload("Paid signups and repeat orders"))
    assert result[0]["data_to_collect"] == "Paid signups and repeat orders"


def test_invalid_structured_measurement_fails_closed():
    with pytest.raises((TypeError, ValueError)):
        parse_design(_payload([{"description": "Missing field name"}]))
