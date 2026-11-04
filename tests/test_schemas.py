import json

from autocut.models.export import SCHEMAS_DIR, build_schemas


def test_committed_schemas_match_models():
    """Se fallisce: `uv run autocut export-schemas` e committa schemas/."""
    for name, text in build_schemas().items():
        committed = (SCHEMAS_DIR / name).read_bytes().decode("utf-8")
        assert committed == text, f"{name} non aggiornato"


def test_schemas_are_open_for_extension():
    for text in build_schemas().values():
        schema = json.loads(text)
        assert "schema_version" in schema["properties"]
        assert schema.get("additionalProperties", True) is True
