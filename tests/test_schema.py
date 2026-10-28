import json, pathlib
A = pathlib.Path(__file__).resolve().parents[1] / ".actor"

def test_every_input_field_has_description():
    s = json.loads((A / "input_schema.json").read_text())
    for k, v in s["properties"].items():
        assert v.get("description"), k

def test_pricing_events():
    ev = json.loads((A / "pay_per_event.json").read_text())["events"]
    assert {"file-normalized", "audio-minute"} <= set(ev)


def test_billing_grace():
    from src.core import billable_minutes as b
    assert b(None) == 1 and b(60.4) == 1 and b(60.5) == 1 and b(60.6) == 2 and b(3600.3) == 60 and b(121) == 3
