"""SuggestedAction accepts both shapes: tagged objects from the new tool
schema, and bare strings from old games' stored turns and code fallbacks."""

from app.schemas import StructuredResponse


def test_bare_strings_and_tagged_objects_both_validate():
    response = StructuredResponse(
        narrative="The dark presses in.",
        location="The Ruined Gate",
        exits={},
        visible_npcs=[],
        suggested_actions=[
            "Look around",
            {"text": "Read the runes", "character": "Mira"},
        ],
    )
    assert response.suggested_actions[0].text == "Look around"
    assert response.suggested_actions[0].character is None
    assert response.suggested_actions[1].character == "Mira"
    # Serialized shape is always the tagged object — the frontend's string
    # branch only exists for JSON stored before this feature.
    assert response.model_dump()["suggested_actions"][0] == {
        "text": "Look around",
        "character": None,
    }
