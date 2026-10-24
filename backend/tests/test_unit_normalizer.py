from app.utils.unit_normalizer import normalize_items


class TestNormalizeItems:
    def test_notes_appended(self):
        items = [{"unit": "100 м2", "quantity": 0.1, "notes": "важно"}]
        result = normalize_items(items)
        assert result[0]["unit"] == "м2"
        assert "важно" in result[0]["notes"]
        assert "нормализована" in result[0]["notes"]

    def test_no_change_for_normal_unit(self):
        items = [{"unit": "м2", "quantity": 5.0}]
        result = normalize_items(items)
        assert result[0]["unit"] == "м2"
        assert result[0]["quantity"] == 5.0
        assert "notes" not in result[0]

    def test_original_not_mutated(self):
        original = [{"unit": "100 м2", "quantity": 0.1}]
        normalize_items(original)
        assert original[0]["unit"] == "100 м2"
