"""In-memory tests for Wikibase calendar-model handling.

Regression coverage for the bug where editing *any* field on an item rewrote its
date claims from Julian to Gregorian, plus the schema-declared default and the
per-field `<slot>_calendar` override.

No Wikibase network calls are made: every test operates on in-memory ItemEntity
objects, following the style of tests/test_wbgenerator_direct_references.py.
"""

from pathlib import Path

from wikibaseintegrator import WikibaseIntegrator, datatypes
from wikibaseintegrator.wbi_enums import ActionIfExists

from wbforms.codegen.pydantic_gen import generate_models
from wbforms.wb_calendar import GREGORIAN_CALENDAR_MODEL, JULIAN_CALENDAR_MODEL
from wbforms.wbgenerator import (
    create_item_from_model,
    get_claim,
    get_model_from_item,
    update_item_from_model,
    update_qualified_statement_from_model,
)

GREGORIAN = GREGORIAN_CALENDAR_MODEL
JULIAN = JULIAN_CALENDAR_MODEL

_BOILERPLATE = """
id: https://example.org/schema/test-calendar
name: test_calendar
description: Test schema for Wikibase calendar models

prefixes:
  linkml: https://w3id.org/linkml/

default_range: string

imports:
  - linkml:types

types:
  item_statement_subject:
    uri: xsd:string
    base: str
    description: "QID or Wikibase somevalue sentinel"
"""

_SLOTS_AND_CLASSES = """
slots:
  label:
    range: string
    required: false
  description:
    range: string
    required: false

  nickname:
    range: string
    annotations:
      wikibase_id: "https://example.org/prop/direct/P100"
      wikibase_type: string

  date_of_birth:
    range: string
    annotations:
      wikibase_id: "https://example.org/prop/direct/P77"
      wikibase_type: time

  date_of_death:
    range: string
    annotations:
      wikibase_id: "https://example.org/prop/direct/P38"
      wikibase_type: time
      calendar_model: "Q1985786"

  event_dates:
    range: string
    multivalued: true
    annotations:
      wikibase_id: "https://example.org/prop/direct/P99"
      wikibase_type: time

  member_of:
    range: item_statement_subject
    annotations:
      wikibase_id: "https://example.org/prop/statement/P200"
      wikibase_type: item

  begin_date:
    range: string
    annotations:
      wikibase_id: "https://example.org/prop/qualifier/P49"
      wikibase_type: time

  retrieved:
    range: string
    annotations:
      wikibase_id: "https://example.org/prop/reference/P24"
      wikibase_type: time

  memberships:
    range: Membership
    multivalued: true
    inlined_as_list: true

classes:
  Person:
    annotations:
      python_base: entity_item
    slots:
      - label
      - description
      - nickname
      - date_of_birth
      - date_of_death
      - event_dates
      - memberships
    slot_usage:
      date_of_birth:
        annotations:
          supports_references: true

  Membership:
    annotations:
      python_base: extracted_statement
      supports_references: true
    slots:
      - member_of
      - begin_date

  WikibaseReference:
    annotations:
      python_base: wikibase_reference
    slots:
      - retrieved
"""

_SCHEMA = _BOILERPLATE + _SLOTS_AND_CLASSES

# Same schema, but with a schema-level default calendar model.
_SCHEMA_WITH_SCHEMA_DEFAULT = (
    _BOILERPLATE
    + """
annotations:
  default_calendar_model: "Q1985786"
"""
    + _SLOTS_AND_CLASSES
)


def _generate(tmp_path: Path, schema_yaml: str = _SCHEMA) -> dict[str, type]:
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(schema_yaml, encoding="utf-8")
    return generate_models(schema_file)


def _cal(claim) -> str:
    """Calendar model of a claim's (or snak's) time datavalue."""
    snak = getattr(claim, "mainsnak", claim)
    return snak.datavalue["value"]["calendarmodel"]


def _julian_person_item(dob: str = "+1750-03-12T00:00:00Z"):
    """An item as it comes back from Wikibase: a Julian date_of_birth plus a nickname."""
    item = WikibaseIntegrator().item.new()
    item.labels.set("en", "Anna")
    item.claims.add(datatypes.String(value="Ann", prop_nr="P100"))
    item.claims.add(datatypes.Time(time=dob, precision=11, prop_nr="P77", calendarmodel=JULIAN))
    return item


# --- get_claim ---------------------------------------------------------------


def test_get_claim_defaults_to_gregorian():
    claim = get_claim(prop_id="P77", datatype=datatypes.Time.DTYPE, value="+2020-05-20T00:00:00Z")
    assert _cal(claim) == GREGORIAN


def test_get_claim_accepts_explicit_calendar_qid():
    claim = get_claim(
        prop_id="P77",
        datatype=datatypes.Time.DTYPE,
        value="+1750-03-12T00:00:00Z",
        calendarmodel="Q1985786",
    )
    assert _cal(claim) == JULIAN


def test_get_claim_accepts_explicit_calendar_iri():
    claim = get_claim(
        prop_id="P77",
        datatype=datatypes.Time.DTYPE,
        value="+1750-03-12T00:00:00Z",
        calendarmodel=JULIAN,
    )
    assert _cal(claim) == JULIAN


# --- The reported bug: updating an item must not change stored calendars -----


def test_untouched_date_keeps_julian(tmp_path):
    """Editing only the nickname leaves the date claim entirely alone."""
    models = _generate(tmp_path)
    item = _julian_person_item()
    update_item_from_model(models["PersonUpdate"](nickname="Annie"), item)
    assert _cal(item.claims.get("P77")[0]) == JULIAN


def test_resubmitted_unchanged_date_keeps_julian(tmp_path):
    """The form POSTs every non-empty field back, so the date is in model_fields_set
    even when the user only touched the nickname. Its calendar must survive."""
    models = _generate(tmp_path)
    item = _julian_person_item()
    update_item_from_model(
        models["PersonUpdate"](nickname="Annie", date_of_birth="+1750-03-12T00:00:00Z"),
        item,
    )
    assert _cal(item.claims.get("P77")[0]) == JULIAN


def test_changing_the_date_value_keeps_julian(tmp_path):
    """Correcting the day of a Julian date keeps it Julian."""
    models = _generate(tmp_path)
    item = _julian_person_item()
    update_item_from_model(models["PersonUpdate"](date_of_birth="+1750-03-13T00:00:00Z"), item)
    claim = item.claims.get("P77")[0]
    assert claim.mainsnak.datavalue["value"]["time"] == "+1750-03-13T00:00:00Z"
    assert _cal(claim) == JULIAN


# --- Round-trip through the model -------------------------------------------


def test_read_exposes_calendar_model(tmp_path):
    models = _generate(tmp_path)
    item = _julian_person_item()
    person = get_model_from_item(item, models["Person"])
    assert person.date_of_birth == "+1750-03-12T00:00:00Z"
    assert person.date_of_birth_calendar == JULIAN


def test_round_trip_preserves_julian(tmp_path):
    """Read the item into a model and write the model straight back."""
    models = _generate(tmp_path)
    item = _julian_person_item()
    person = get_model_from_item(item, models["Person"])
    update_item_from_model(models["PersonUpdate"](**person.model_dump(exclude_none=True)), item)
    assert _cal(item.claims.get("P77")[0]) == JULIAN


def test_explicit_calendar_change_is_applied(tmp_path):
    """An explicit selector change in the form must win over preservation."""
    models = _generate(tmp_path)
    item = _julian_person_item()
    update_item_from_model(
        models["PersonUpdate"](date_of_birth="+1750-03-12T00:00:00Z", date_of_birth_calendar=GREGORIAN),
        item,
    )
    assert _cal(item.claims.get("P77")[0]) == GREGORIAN


def test_create_uses_explicit_calendar(tmp_path):
    models = _generate(tmp_path)
    person = models["PersonCreate"](
        label="Anna",
        date_of_birth="+1750-03-12T00:00:00Z",
        date_of_birth_calendar="Q1985786",
    )
    item = create_item_from_model(person, WikibaseIntegrator())
    assert _cal(item.claims.get("P77")[0]) == JULIAN


# --- Mixed calendars within one item ----------------------------------------


def test_mixed_calendars_within_item_preserved(tmp_path):
    models = _generate(tmp_path)
    item = _julian_person_item()
    item.claims.add(datatypes.Time(time="+1812-11-04T00:00:00Z", precision=11, prop_nr="P38", calendarmodel=GREGORIAN))
    update_item_from_model(
        models["PersonUpdate"](
            nickname="Annie",
            date_of_birth="+1750-03-12T00:00:00Z",
            date_of_death="+1812-11-04T00:00:00Z",
        ),
        item,
    )
    assert _cal(item.claims.get("P77")[0]) == JULIAN
    assert _cal(item.claims.get("P38")[0]) == GREGORIAN


def test_multivalued_time_keeps_per_value_calendars(tmp_path):
    """List-valued time slots are removed and rebuilt; calendars are matched by time string."""
    models = _generate(tmp_path)
    item = WikibaseIntegrator().item.new()
    item.labels.set("en", "Anna")
    for time_str, cal in (("+1750-03-12T00:00:00Z", JULIAN), ("+1812-11-04T00:00:00Z", GREGORIAN)):
        item.claims.add(
            datatypes.Time(time=time_str, precision=11, prop_nr="P99", calendarmodel=cal),
            action_if_exists=ActionIfExists.FORCE_APPEND,
        )
    update_item_from_model(
        models["PersonUpdate"](event_dates=["+1750-03-12T00:00:00Z", "+1812-11-04T00:00:00Z"]),
        item,
    )
    live = [c for c in item.claims.get("P99") if not c.removed]
    assert [_cal(c) for c in live] == [JULIAN, GREGORIAN]


# --- Qualifiers and references ----------------------------------------------


def test_qualifier_calendar_round_trip(tmp_path):
    models = _generate(tmp_path)
    membership = models["Membership"](
        statement_id="Q1$aaaa",
        member_of="Q5",
        begin_date="+1750-03-12T00:00:00Z",
        begin_date_calendar="Q1985786",
    )
    person = models["PersonCreate"](label="Anna", memberships=[membership])
    item = create_item_from_model(person, WikibaseIntegrator())
    claim = item.claims.get("P200")[0]
    assert _cal(claim.qualifiers.get("P49")[0]) == JULIAN

    # The read model requires a statement id, which only exists once Wikibase has
    # persisted the claim; stand one in so the in-memory item can be read back.
    claim.id = "Q1$aaaa"
    back = get_model_from_item(item, models["Person"])
    assert back.memberships[0].begin_date_calendar == JULIAN


def test_qualifier_calendar_preserved_on_statement_update(tmp_path):
    models = _generate(tmp_path)
    membership = models["Membership"](
        statement_id="Q1$aaaa",
        member_of="Q5",
        begin_date="+1750-03-12T00:00:00Z",
        begin_date_calendar="Q1985786",
    )
    person = models["PersonCreate"](label="Anna", memberships=[membership])
    item = create_item_from_model(person, WikibaseIntegrator())
    claim = item.claims.get("P200")[0]
    claim.id = "Q1$aaaa"

    update_qualified_statement_from_model(
        item,
        "Q1$aaaa",
        models["MembershipUpdate"](member_of="Q5", begin_date="+1750-03-12T00:00:00Z"),
    )
    assert _cal(item.claims.get("P200")[0].qualifiers.get("P49")[0]) == JULIAN


def test_reference_snak_calendar_round_trip(tmp_path):
    models = _generate(tmp_path)
    person = models["PersonCreate"](
        label="Anna",
        date_of_birth="+1750-03-12T00:00:00Z",
        date_of_birth_sources=[
            models["WikibaseReference"](retrieved="+1750-03-12T00:00:00Z", retrieved_calendar="Q1985786")
        ],
    )
    item = create_item_from_model(person, WikibaseIntegrator())
    block = item.claims.get("P77")[0].references.references[0]
    assert _cal(block.snaks.snaks["P24"][0]) == JULIAN

    back = get_model_from_item(item, models["Person"])
    assert back.date_of_birth_sources[0].retrieved_calendar == JULIAN


# --- Schema-declared defaults ------------------------------------------------


def test_slot_annotation_sets_default_calendar(tmp_path):
    """date_of_death declares calendar_model: Q1985786 in the schema."""
    models = _generate(tmp_path)
    person = models["PersonCreate"](label="Anna", date_of_death="+1812-11-04T00:00:00Z")
    item = create_item_from_model(person, WikibaseIntegrator())
    assert _cal(item.claims.get("P38")[0]) == JULIAN


def test_slot_without_annotation_defaults_to_gregorian(tmp_path):
    models = _generate(tmp_path)
    person = models["PersonCreate"](label="Anna", date_of_birth="+1750-03-12T00:00:00Z")
    item = create_item_from_model(person, WikibaseIntegrator())
    assert _cal(item.claims.get("P77")[0]) == GREGORIAN


def test_schema_level_default_calendar_model(tmp_path):
    """The schema root can set the default for every time slot that has no annotation."""
    models = _generate(tmp_path, _SCHEMA_WITH_SCHEMA_DEFAULT)
    person = models["PersonCreate"](label="Anna", date_of_birth="+1750-03-12T00:00:00Z")
    item = create_item_from_model(person, WikibaseIntegrator())
    assert _cal(item.claims.get("P77")[0]) == JULIAN
