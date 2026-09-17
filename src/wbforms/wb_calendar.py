"""Wikibase calendar models.

Wikibase stores every time value together with a calendar model IRI. Only two are
in practical use, and both are addressed by their *Wikidata* IRI even on other
Wikibase instances (FactGrid, wikibase.cloud, …) — the calendar model is part of
the Wikibase data model itself, not of the local entity namespace.

Values are stored and transported as the full IRI, which is what Wikibase returns.
Bare QIDs are accepted as input (from schema annotations and from the form) and
normalized on the way in.
"""

GREGORIAN_CALENDAR_MODEL = "http://www.wikidata.org/entity/Q1985727"
JULIAN_CALENDAR_MODEL = "http://www.wikidata.org/entity/Q1985786"

#: Applied to new time values when neither the model nor the schema says otherwise.
DEFAULT_CALENDAR_MODEL = GREGORIAN_CALENDAR_MODEL

#: QID → IRI for the calendar models Wikibase supports, in the order the form offers them.
SUPPORTED_CALENDAR_MODELS: dict[str, str] = {
    "Q1985727": GREGORIAN_CALENDAR_MODEL,
    "Q1985786": JULIAN_CALENDAR_MODEL,
}

#: QID → i18n key, consumed by the frontend calendar selector.
CALENDAR_MODEL_LABEL_KEYS: dict[str, str] = {
    "Q1985727": "calendar_gregorian",
    "Q1985786": "calendar_julian",
}


def normalize_calendar_model(value: str | None) -> str | None:
    """Return the full calendar model IRI for *value*, or None if it is empty.

    Accepts a bare QID (``Q1985786``) or an already-qualified IRI. Unknown QIDs are
    expanded against the Wikidata entity namespace rather than rejected, so a
    Wikibase instance with an exotic calendar model still round-trips; unknown IRIs
    are passed through untouched.
    """
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith("Q"):
        return SUPPORTED_CALENDAR_MODELS.get(value, f"http://www.wikidata.org/entity/{value}")
    return value


def calendar_model_qid(value: str | None) -> str | None:
    """Return the bare QID for a calendar model IRI (or QID), or None if empty."""
    if not value:
        return None
    return value.rstrip("/").split("/")[-1] or None


def calendar_model_options() -> list[dict[str, str]]:
    """Calendar choices for the form metadata endpoint."""
    return [
        {"qid": qid, "iri": iri, "label_key": CALENDAR_MODEL_LABEL_KEYS[qid]}
        for qid, iri in SUPPORTED_CALENDAR_MODELS.items()
    ]
