"""Map detector prompts to internal categories, independent of provider enums."""

from app.errors import APIError

PROMPT_TO_INTERNAL = {
    "hat": "hat",
    "scarf": "scarf",
    "shoe": "shoes",
    "shoes": "shoes",
    "jacket": "outerwear",
    "coat": "outerwear",
    "shirt": "upper_body",
    "sweater": "upper_body",
    "trousers": "lower_body",
    "skirt": "lower_body",
    "dress": "full_body",
    "bag": "bag",
}

INTERNAL_LABELS = {
    "hat": "Hat",
    "scarf": "Scarf",
    "shoes": "Shoes",
    "outerwear": "Outerwear",
    "upper_body": "Upper body",
    "lower_body": "Lower body",
    "full_body": "Full body",
    "bag": "Bag",
}

ALLOWED_PROMPTS = (
    "hat",
    "scarf",
    "jacket",
    "coat",
    "shirt",
    "sweater",
    "trousers",
    "skirt",
    "dress",
    "shoe",
    "bag",
)


def normalize_prompt(value: str) -> str:
    return value.strip().lower()


def internal_category(prompt: str) -> str:
    key = normalize_prompt(prompt)
    if key not in PROMPT_TO_INTERNAL:
        raise APIError(400, "invalid_category", "Choose one of the listed clothing categories.")
    return PROMPT_TO_INTERNAL[key]


def label_for(category: str | None, *, origin: str = "inspiration") -> str:
    if not category:
        return "Original"
    label = INTERNAL_LABELS.get(category, category.replace("_", " ").title())
    if origin == "product":
        return f"{label} · product"
    return label
