from app.detection import _keep_highest_per_label


def test_same_shown_name_keeps_the_higher_score():
    items = [
        {"category_prompt": "scarf", "internal_category": "scarf", "confidence": 0.31},
        {"category_prompt": "scarf", "internal_category": "scarf", "confidence": 0.37},
        {"category_prompt": "scarf", "internal_category": "scarf", "confidence": 0.28},
        {"category_prompt": "shirt", "internal_category": "upper_body", "confidence": 0.21},
        {"category_prompt": "sweater", "internal_category": "upper_body", "confidence": 0.26},
        {"category_prompt": "trousers", "internal_category": "lower_body", "confidence": 0.26},
        {"category_prompt": "skirt", "internal_category": "lower_body", "confidence": 0.17},
    ]
    kept = _keep_highest_per_label(items)
    by_name = {item["internal_category"]: item for item in kept}
    assert set(by_name) == {"scarf", "upper_body", "lower_body"}
    assert by_name["scarf"]["confidence"] == 0.37
    assert by_name["upper_body"]["category_prompt"] == "sweater"
    assert by_name["lower_body"]["category_prompt"] == "trousers"
    assert [item["confidence"] for item in kept] == [0.37, 0.26, 0.26]
