import logging
import re
import types as _types_module
from typing import Any, Union, get_args, get_origin

from pydantic import AnyHttpUrl, BaseModel
from pydantic.fields import FieldInfo
from wikibaseintegrator import WikibaseIntegrator, datatypes
from wikibaseintegrator.datatypes import BaseDataType
from wikibaseintegrator.entities import ItemEntity
from wikibaseintegrator.models import Claim, Snak
from wikibaseintegrator.models.references import Reference as WBIReference
from wikibaseintegrator.wbi_enums import ActionIfExists, WikibaseSnakType

from wbforms.datamodel.item import (
    CALENDAR_MODEL,
    WIKIBASE_ID,
    WIKIBASE_TYPE,
    Coordinate,
    ExtractedStatement,
    Statement,
    StatementBase,
    WikibaseReferenceBase,
    calendar_field_name,
)
from wbforms.wb_calendar import DEFAULT_CALENDAR_MODEL, normalize_calendar_model
from wbforms.wikibase import Wikibase

logger = logging.getLogger(__name__)


def get_statement_field_type(annotation) -> type[StatementBase] | None:
    """
    Return the StatementBase subclass if *annotation* is StatementBase, list[StatementBase],
    or Optional[StatementBase]; otherwise return None.
    """
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        if args and isinstance(args[0], type) and issubclass(args[0], StatementBase):
            return args[0]
    elif origin is Union or (hasattr(_types_module, "UnionType") and isinstance(annotation, _types_module.UnionType)):
        for arg in get_args(annotation):
            if isinstance(arg, type) and issubclass(arg, StatementBase):
                return arg
    elif isinstance(annotation, type) and issubclass(annotation, StatementBase):
        return annotation
    return None


def _get_schema_extra(field_metadata: FieldInfo) -> Any:
    """Return json_schema_extra (a loosely-typed mapping), or {} if absent.

    Returns ``Any`` because the contained property ids / wikibase types are
    schema-driven strings consumed by ``str``-typed helpers; the values are
    guaranteed present in the branches that use them.
    """
    extra = field_metadata.json_schema_extra
    return extra if isinstance(extra, dict) else {}


def _remove_property_claims(item: ItemEntity, prop_nr: str) -> None:
    """
    Remove every claim under ``prop_nr`` from ``item``.

    Works around a bug in WikibaseIntegrator's ``Claims.remove`` where it iterates over the
    internal list while mutating it, skipping every other no-id claim. We iterate a copy.
    Claims with an id (i.e. already persisted in Wikibase) are flagged removed; in-memory
    claims without an id are dropped from the internal list.
    """
    internal: dict = item.claims.claims
    if prop_nr not in internal:
        return
    for claim in list(internal[prop_nr]):
        if claim.id:
            claim.remove()
        else:
            internal[prop_nr].remove(claim)
    if not internal[prop_nr]:
        del internal[prop_nr]


def _statement_ids_equal(a: str | None, b: str | None) -> bool:
    """Compare two statement GUIDs case-insensitively.

    Wikibase treats statement GUIDs case-insensitively and different API surfaces present them
    in different case (the REST API upper-normalizes them; see Wikimedia T354262). New, unwritten
    claims have ``id is None`` and never match.
    """
    if a is None or b is None:
        return False
    return a.lower() == b.lower()


def _is_list_annotation(annotation) -> bool:
    """Return True if annotation is list[T] or list[T] | None (Optional list)."""
    origin = get_origin(annotation)
    if origin is list:
        return True
    if origin is Union or (hasattr(_types_module, "UnionType") and isinstance(annotation, _types_module.UnionType)):
        return any(get_origin(arg) is list for arg in get_args(annotation))
    return False


def create_item_from_model(model: BaseModel, wbi: WikibaseIntegrator) -> ItemEntity:
    """
    Create ItemEntity from given object model
    :param model:
    :return:
    """
    item: ItemEntity = wbi.item.new()
    default_language = "de"

    field_name: str
    field_metadata: FieldInfo
    model_cls = type(model)
    for field_name, field_metadata in model.model_fields.items():
        field_value = getattr(model, field_name)
        if field_value is None:
            continue

        # Statement-reference field (list[ScholarSignature], etc.)
        stmt_type = get_statement_field_type(field_metadata.annotation)
        if stmt_type is not None:
            values = field_value if isinstance(field_value, list) else [field_value]
            for stmt in values:
                if stmt is not None:
                    claim = create_qualified_statement_from_model(stmt)
                    item.claims.add(claim, action_if_exists=ActionIfExists.FORCE_APPEND)
            continue

        extra = _get_schema_extra(field_metadata)
        if not extra:
            continue
        field_type = extra.get(WIKIBASE_TYPE)
        field_prop_id = extra.get(WIKIBASE_ID)
        if field_prop_id == "rdfs:label":
            item.labels.set(default_language, field_value)
        elif field_prop_id == "schema:description":
            item.descriptions.set(default_language, field_value)
        else:
            sources_field_name = f"{field_name}_sources"
            sources_value = (
                getattr(model, sources_field_name, None) if sources_field_name in model_cls.model_fields else None
            )
            is_list_field = isinstance(field_value, list)
            values = field_value if is_list_field else [field_value]
            claims = []
            for idx, value in enumerate(values):
                claim = get_claim(
                    prop_id=field_prop_id,
                    datatype=field_type,
                    value=value,
                    language=default_language,
                    calendarmodel=_calendar_model_for(model, field_name, extra, idx if is_list_field else None),
                )
                if claim is None:
                    continue
                if sources_value is not None:
                    if is_list_field:
                        block_models = sources_value[idx] if idx < len(sources_value) else None
                    else:
                        block_models = sources_value
                    _attach_reference_blocks(claim, block_models)
                claims.append(claim)
            # Multivalued direct properties need FORCE_APPEND so each claim coexists; for a single
            # value, the default REPLACE_ALL is correct (one claim per property).
            add_action = ActionIfExists.FORCE_APPEND if is_list_field else ActionIfExists.REPLACE_ALL
            for claim in claims:
                item.claims.add(claim, action_if_exists=add_action)
    return item


def update_item_from_model(model: BaseModel, item: ItemEntity):
    """
    Update ItemEntity from given object model
    :param model:
    :param item:
    :return:
    """
    default_language = "de"
    model_cls = type(model)
    for field_name in model.model_fields_set:
        field_value: Any = getattr(model, field_name)
        field_metadata: FieldInfo = model.model_fields.get(field_name)

        # Statement-reference field
        stmt_type = get_statement_field_type(field_metadata.annotation)
        if stmt_type is not None:
            subject_field = stmt_type.get_statement_subject(WIKIBASE_ID)
            subject_prop_id = stmt_type.model_fields[subject_field].json_schema_extra.get(WIKIBASE_ID)
            subject_prop_nr = Wikibase.get_entity_id(subject_prop_id)
            _remove_property_claims(item, subject_prop_nr)
            values = field_value if isinstance(field_value, list) else ([field_value] if field_value else [])
            for stmt in values:
                if stmt is not None:
                    claim = create_qualified_statement_from_model(stmt)
                    item.claims.add(claim, action_if_exists=ActionIfExists.FORCE_APPEND)
            continue

        extra = _get_schema_extra(field_metadata)
        if not extra:
            continue
        field_type = extra.get(WIKIBASE_TYPE)
        field_prop_id = extra.get(WIKIBASE_ID)
        if field_prop_id == "rdfs:label":
            if field_value is not None:
                item.labels.set(
                    default_language,
                    field_value,
                    action_if_exists=ActionIfExists.REPLACE_ALL,
                )
        elif field_prop_id == "schema:description":
            if field_value is not None:
                item.descriptions.set(
                    default_language,
                    field_value,
                    action_if_exists=ActionIfExists.REPLACE_ALL,
                )
        else:
            is_list = _is_list_annotation(field_metadata.annotation)
            prop_nr = Wikibase.get_entity_id(field_prop_id)
            if field_value is None:
                # Don't remove existing claims if the field is not set in the form
                # This preserves existing qualifiers and references
                continue
            values = field_value if isinstance(field_value, list) else [field_value]
            # Snapshot the calendar models already stored under this property before the
            # claims are replaced, so a date the user did not explicitly re-calendar keeps
            # the calendar it was saved with.
            stored_calendars = _stored_calendar_models(
                [c.mainsnak for c in (item.claims.get(prop_nr) or []) if not c.removed]
            )
            claims = []
            for idx, v in enumerate(values):
                explicit_calendar = _explicit_calendar_model(model, field_name, idx if is_list else None)
                claim = get_claim(
                    prop_id=field_prop_id,
                    datatype=field_type,
                    value=v,
                    language=default_language,
                    calendarmodel=explicit_calendar or normalize_calendar_model(extra.get(CALENDAR_MODEL)),
                )
                if c is not None
            ]
            prop_nr = Wikibase.get_entity_id(field_prop_id)

            if is_list:
                _remove_property_claims(item, prop_nr)
                for claim in claims:
                    item.claims.add(claim, action_if_exists=ActionIfExists.FORCE_APPEND)
            elif not claims:
                continue
            elif field_type == datatypes.MonolingualText.DTYPE:
                existing = item.claims.get(prop_nr)
                matched = next(
                    (c for c in existing if c.mainsnak.datavalue.get("value", {}).get("language") == default_language),
                    None,
                )
                if matched is not None:
                    matched.mainsnak = claims[0].mainsnak
                else:
                    item.claims.add(claims[0], action_if_exists=ActionIfExists.FORCE_APPEND)
            else:
                existing = item.claims.get(prop_nr)
                if existing:
                    existing[0].mainsnak = claims[0].mainsnak
                else:
                    item.claims.add(claims[0])

    # Second pass: re-attach direct-property references for every `<field>_sources` set on the model.
    for sources_field_name in model.model_fields_set:
        if not sources_field_name.endswith("_sources"):
            continue
        base_name = sources_field_name[: -len("_sources")]
        if not base_name or base_name not in model_cls.model_fields:
            continue
        base_metadata: FieldInfo = model_cls.model_fields[base_name]
        base_extra = _get_schema_extra(base_metadata)
        base_prop_id = base_extra.get(WIKIBASE_ID)
        if not base_prop_id or base_prop_id in {"rdf:subject", "rdfs:label", "schema:description"}:
            continue
        base_prop_nr = Wikibase.get_entity_id(base_prop_id)
        sources_value = getattr(model, sources_field_name) or []
        existing_claims = [c for c in (item.claims.get(base_prop_nr) or []) if not c.removed]
        if _is_list_annotation(base_metadata.annotation):
            for i, claim in enumerate(existing_claims):
                claim.references.clear()
                if i < len(sources_value):
                    _attach_reference_blocks(claim, sources_value[i])
        else:
            base_wb_type = base_extra.get(WIKIBASE_TYPE)
            if base_wb_type == datatypes.MonolingualText.DTYPE:
                target = next(
                    (
                        c
                        for c in existing_claims
                        if c.mainsnak.datavalue.get("value", {}).get("language") == default_language
                    ),
                    existing_claims[0] if existing_claims else None,
                )
            else:
                target = existing_claims[0] if existing_claims else None
            if target is not None:
                target.references.clear()
                _attach_reference_blocks(target, sources_value)


_WB_TIME_RE = re.compile(r"^[+-](\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$")


def _infer_time_precision(time_str: str) -> int:
    """
    Infer the Wikibase time precision from a `±YYYY-MM-DDTHH:MM:SSZ` string.

    Zeros in the lower slots encode lower precision: `+2020-00-00T00:00:00Z` is year
    precision (9), `+2020-05-00T00:00:00Z` is month (10), `+2020-05-20T00:00:00Z` is
    day (11). Day is the finest precision currently supported by WikibaseIntegrator,
    so sub-day fields are ignored. Falls back to day precision when the input
    doesn't match the expected format.
    """
    if not isinstance(time_str, str):
        return 11
    m = _WB_TIME_RE.match(time_str)
    if not m:
        logger.debug("Time value %r does not match Wikibase format; using day precision", time_str)
        return 11
    _, month, day, _, _, _ = m.groups()
    if month == "00" and day == "00":
        return 9
    if day == "00":
        return 10
    return 11


def get_snak_calendar_model(snak: Snak) -> str | None:
    """Return the calendar model IRI of a `time` snak, or None for any other datatype."""
    if snak.datatype != datatypes.Time.DTYPE:
        return None
    datavalue = snak.datavalue or {}
    return (datavalue.get("value") or {}).get("calendarmodel")


def _explicit_calendar_model(model: BaseModel, field_name: str, index: int | None = None) -> str | None:
    """Calendar model the *model* explicitly carries for ``field_name``, if any.

    Only fields the caller actually provided count (``model_fields_set``): an absent
    sibling means "keep whatever is stored", not "reset to the default". For a
    multivalued slot the sibling is positional, mirroring ``<slot>_sources``.
    """
    sibling = calendar_field_name(field_name)
    if sibling not in type(model).model_fields or sibling not in model.model_fields_set:
        return None
    value = getattr(model, sibling, None)
    if isinstance(value, list):
        if index is None or index >= len(value):
            return None
        value = value[index]
    return normalize_calendar_model(value)


def _calendar_model_for(model: BaseModel, field_name: str, extra: Any, index: int | None = None) -> str | None:
    """Calendar model to write: explicit model value, else the schema-declared slot default."""
    return _explicit_calendar_model(model, field_name, index) or normalize_calendar_model(extra.get(CALENDAR_MODEL))


def _stored_calendar_models(snaks: list[Snak]) -> list[tuple[str | None, str | None]]:
    """(time string, calendar model) pairs of the given `time` snaks."""
    stored: list[tuple[str | None, str | None]] = []
    for snak in snaks:
        if snak.datatype != datatypes.Time.DTYPE:
            continue
        value = (snak.datavalue or {}).get("value") or {}
        stored.append((value.get("time"), value.get("calendarmodel")))
    return stored


def _inherit_calendar_model(claim: Claim, stored: list[tuple[str | None, str | None]], single_valued: bool) -> None:
    """Carry a previously stored calendar model over onto a freshly built `time` claim.

    Wikibase writes replace whole snaks, so without this a re-submitted (or merely
    corrected) Julian date would silently come back as the default Gregorian.

    A single-valued slot has exactly one predecessor, so its calendar carries over even
    when the date itself changes — correcting the day of a Julian date keeps it Julian.
    Multivalued slots are removed and rebuilt wholesale, leaving no reliable positional
    identity, so those are matched on the time string and otherwise keep the default.
    """
    if claim.mainsnak.datatype != datatypes.Time.DTYPE or not stored:
        return
    if single_valued:
        inherited = stored[0][1]
    else:
        time_str = ((claim.mainsnak.datavalue or {}).get("value") or {}).get("time")
        inherited = next((cal for t, cal in stored if t == time_str), None)
    if inherited:
        claim.mainsnak.datavalue["value"]["calendarmodel"] = inherited


def get_claim(
    prop_id: str,
    datatype: str,
    value: Any,
    language: str | None = None,
    calendarmodel: str | None = None,
) -> Claim | None:
    """
    Get claim
    :param prop_id:
    :param datatype:
    :param value:
    :param language:
    :param calendarmodel: calendar model (QID or IRI) for `time` values; ignored otherwise
    :return:
    """
    if language is None:
        language = "de"
    if value is None:
        return None
    prop_nr = Wikibase.get_entity_id(prop_id)
    claim = None
    match datatype:
        case datatypes.MonolingualText.DTYPE:
            claim = datatypes.MonolingualText(language=language, text=value, prop_nr=prop_nr)
        case datatypes.Item.DTYPE:
            claim = datatypes.Item(value=value, prop_nr=prop_nr)
        case datatypes.URL.DTYPE:
            if isinstance(value, AnyHttpUrl):
                value = str(value)
            claim = datatypes.URL(value=value, prop_nr=prop_nr)
        case datatypes.String.DTYPE:
            claim = datatypes.String(value=str(value), prop_nr=prop_nr)
        case datatypes.Time.DTYPE:
            claim = datatypes.Time(
                time=value,
                precision=_infer_time_precision(value),
                prop_nr=prop_nr,
                calendarmodel=normalize_calendar_model(calendarmodel) or DEFAULT_CALENDAR_MODEL,
            )
        case datatypes.ExternalID.DTYPE:
            claim = datatypes.ExternalID(value=value, prop_nr=prop_nr)
        case datatypes.Quantity.DTYPE:
            claim = datatypes.Quantity(amount=value, prop_nr=prop_nr)
        case datatypes.GlobeCoordinate.DTYPE:
            if isinstance(value, Coordinate):
                claim = datatypes.GlobeCoordinate(longitude=value.longitude, latitude=value.latitude, prop_nr=prop_nr)
            else:
                logger.debug("Value is not a Coordinate object → ignoring in claim creation")
    return claim


def get_snak_value(snak: Snak) -> Any:
    value = None
    match snak.datatype:
        case datatypes.MonolingualText.DTYPE:
            value = snak.datavalue["value"]["text"]
        case datatypes.Item.DTYPE:
            value = snak.datavalue["value"]["id"]
        case datatypes.URL.DTYPE:
            value = snak.datavalue["value"]
        case datatypes.ExternalID.DTYPE:
            value = snak.datavalue["value"]
        case datatypes.String.DTYPE:
            value = snak.datavalue["value"]
        case datatypes.Time.DTYPE:
            value = snak.datavalue["value"].get("time")
        case datatypes.Quantity.DTYPE:
            value = snak.datavalue["value"].get("amount")
    return value


def get_model_from_item(item: ItemEntity, model: type[BaseModel]) -> BaseModel:
    """
    Get model from given item entity
    :param item:
    :param model:
    :return:
    """
    default_language = "de"
    field_name: str
    field_metadata: FieldInfo
    record: dict[str, Any] = {}
    for field_name, field_metadata in model.model_fields.items():
        # Statement-reference field (list[ScholarSignature], etc.)
        stmt_type = get_statement_field_type(field_metadata.annotation)
        if stmt_type is not None:
            statements = get_models_from_qualified_statement(item, stmt_type)
            if _is_list_annotation(field_metadata.annotation):
                record[field_name] = statements
            elif statements:
                record[field_name] = statements[0]
            continue

        extra = _get_schema_extra(field_metadata)
        if not extra:
            continue
        field_prop_id = extra.get(WIKIBASE_ID)
        field_value = None
        if field_prop_id == "rdf:subject":
            field_value = item.id
        elif field_prop_id == "rdfs:label":
            label = item.labels.get(default_language) or item.labels.get("en")
            if label is not None:
                field_value = label.value
        elif field_prop_id == "schema:description":
            description = item.descriptions.get(default_language) or item.descriptions.get("en")
            if description is not None:
                field_value = description.value
        else:
            prop_nr = Wikibase.get_entity_id(field_prop_id)
            field_type = extra.get(WIKIBASE_TYPE)
            claims: list[Claim] = [c for c in item.claims.get(prop_nr) if not c.removed]
            sources_field_name = f"{field_name}_sources"
            sources_field = model.model_fields.get(sources_field_name)
            ref_cls = _wikibase_reference_class(sources_field) if sources_field is not None else None
            cal_field_name = calendar_field_name(field_name)
            has_cal_field = cal_field_name in model.model_fields
            if _is_list_annotation(field_metadata.annotation):
                values = [get_snak_value(claim.mainsnak) for claim in claims]
                values = [value for value in values if value is not None]
                field_value = values
                if ref_cls is not None:
                    record[sources_field_name] = [_extract_reference_records(c, ref_cls) for c in claims]
                if has_cal_field:
                    record[cal_field_name] = [
                        get_snak_calendar_model(c.mainsnak) or DEFAULT_CALENDAR_MODEL for c in claims
                    ]
            else:
                if field_type == datatypes.MonolingualText.DTYPE:
                    claim = next(
                        (
                            c
                            for c in claims
                            if c.mainsnak.datavalue.get("value", {}).get("language") == default_language
                        ),
                        claims[0] if claims else None,
                    )
                else:
                    claim = claims[0] if claims else None
                if claim is not None:
                    field_value = get_snak_value(claim.mainsnak)
                    if has_cal_field:
                        record[cal_field_name] = get_snak_calendar_model(claim.mainsnak)
                if ref_cls is not None:
                    record[sources_field_name] = _extract_reference_records(claim, ref_cls) if claim else []
        if field_value is not None:
            record[field_name] = field_value
    return model.model_validate(record)


def get_models_from_qualified_statement[T: StatementBase](item: ItemEntity, model: type[T]) -> list[T]:
    """
    Get list of qualified statement objects from given item entity
    ToDo: Report failed model creations and return the successful once along with the list of failure ids
    :param item:
    :param model:
    :return:
    """
    subject_field = model.get_statement_subject(WIKIBASE_ID)
    subject_prop_id = model.model_fields.get(subject_field).json_schema_extra.get(WIKIBASE_ID)
    subject_prop_nr = Wikibase.get_entity_id(subject_prop_id)
    claims: list[Claim] = item.claims.get(subject_prop_nr)
    statements: list[StatementBase] = []
    for claim in claims:
        model_obj = get_model_from_qualified_statement(claim, model)
        if model_obj is not None:
            statements.append(model_obj)
    return statements


def get_model_from_qualified_statement(claim: Claim, model: type[StatementBase]) -> StatementBase | None:
    """
    Get model from given claim entity
    :param claim:
    :param model:
    :return:
    """
    record = {}
    subject_field = model.get_statement_subject(WIKIBASE_ID)
    if claim.mainsnak.snaktype is WikibaseSnakType.UNKNOWN_VALUE:
        record[subject_field] = WikibaseSnakType.UNKNOWN_VALUE.value
    elif claim.mainsnak.snaktype is WikibaseSnakType.NO_VALUE:
        record[subject_field] = WikibaseSnakType.NO_VALUE.value
    else:
        record[subject_field] = get_snak_value(claim.mainsnak)
        subject_cal_field = calendar_field_name(subject_field)
        if subject_cal_field in model.model_fields:
            record[subject_cal_field] = get_snak_calendar_model(claim.mainsnak)
    if issubclass(model, Statement):
        record["statement_id"] = claim.id
    qualifier_fields = model.get_qualifier_fields(WIKIBASE_ID)
    for qualifier_field in qualifier_fields:
        field_metadata: FieldInfo = model.model_fields.get(qualifier_field)
        field_prop_id = field_metadata.json_schema_extra.get(WIKIBASE_ID)
        field_prop_nr = Wikibase.get_entity_id(field_prop_id)
        if field_prop_nr is None:
            continue
        else:
            qualifier: list[Snak] = claim.qualifiers.get(field_prop_nr)
            if qualifier is None or len(qualifier) == 0:
                continue
            elif _is_list_annotation(field_metadata.annotation):
                values = [get_snak_value(snak) for snak in qualifier]
                record[qualifier_field] = values
                cal_field = calendar_field_name(qualifier_field)
                if cal_field in model.model_fields:
                    record[cal_field] = [get_snak_calendar_model(snak) or DEFAULT_CALENDAR_MODEL for snak in qualifier]
            else:
                if len(qualifier) > 1:
                    logger.debug(
                        f"Statement {claim.id} has multiple qualifier values for {field_prop_nr} but the model only "
                        f"supports one value"
                    )
                record[qualifier_field] = get_snak_value(qualifier[0])
                cal_field = calendar_field_name(qualifier_field)
                if cal_field in model.model_fields:
                    record[cal_field] = get_snak_calendar_model(qualifier[0])
    sources = populate_references_from_claim(claim, model)
    if sources is not None:
        record["sources"] = sources
    model_obj = model.model_validate(record)
    return model_obj


def add_statement_from_model(item: ItemEntity, model: StatementBase):
    """
    Add model as statement to given item
    :param item:
    :param model:
    :return:
    """
    existing_statement = get_item_statement_by_model(item, model)
    if existing_statement is not None:
        raise ValueError(f"Statement already exists ({existing_statement}) ")
    claim = create_qualified_statement_from_model(model)
    item.claims.add(claim, action_if_exists=ActionIfExists.FORCE_APPEND)


def get_item_statement_by_model(
    item: ItemEntity,
    model: StatementBase,
    target_model: type[StatementBase | Statement] | None = None,
) -> StatementBase | Statement | None:
    """
    Get statement id from given item or None if the model is not a claim of the item
    :param target_model:
    :param item:
    :param model:
    :return:
    """
    if target_model is None:
        target_model = model.__class__
    statements = get_models_from_qualified_statement(item, target_model)
    for statement in statements:
        if statement == model:
            return statement
    return None


def get_item_statement_by_id(item: ItemEntity, statement_id: str, target_model: type[Statement]) -> Statement | None:
    """
    Get model object by statement_id from given item or None if the model is not a claim of the item
    :param item:
    :param statement_id:
    :param target_model:
    :return:
    """
    statements = get_models_from_qualified_statement(item, target_model)
    for statement in statements:
        if _statement_ids_equal(statement.statement_id, statement_id):
            return statement
    return None


def create_qualified_statement_from_model(model: StatementBase) -> Claim:
    subject_field = model.get_statement_subject(WIKIBASE_ID)
    subject_prop_id = model.model_fields.get(subject_field).json_schema_extra.get(WIKIBASE_ID)
    subject_prop_nr = Wikibase.get_entity_id(subject_prop_id)
    claim: Claim
    subject_val = getattr(model, subject_field)
    if subject_val == WikibaseSnakType.UNKNOWN_VALUE.value:
        claim = BaseDataType(prop_nr=subject_prop_nr, snaktype=WikibaseSnakType.UNKNOWN_VALUE)
    elif subject_val == WikibaseSnakType.NO_VALUE.value:
        claim = BaseDataType(prop_nr=subject_prop_nr, snaktype=WikibaseSnakType.NO_VALUE)
    else:
        subject_extra = _get_schema_extra(model.model_fields.get(subject_field))
        claim = get_claim(
            prop_id=subject_prop_nr,
            datatype=subject_extra.get(WIKIBASE_TYPE),
            value=subject_val,
            calendarmodel=_calendar_model_for(model, subject_field, subject_extra),
        )
    add_qualifier_values_to_statement(claim, model)
    add_references_to_statement(claim, model)
    return claim


def _wikibase_reference_class(field_info: FieldInfo) -> type[WikibaseReferenceBase] | None:
    """
    Return the WikibaseReference subclass referenced by a `*_sources` field's annotation,
    handling both `list[Ref]` (single-valued slot) and `list[list[Ref]]` (multivalued slot).
    Also unwraps `Optional[...]` introduced by partial Update models.
    """
    ann = field_info.annotation
    if get_origin(ann) is Union or (hasattr(_types_module, "UnionType") and isinstance(ann, _types_module.UnionType)):
        non_none = [a for a in get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            ann = non_none[0]
    if get_origin(ann) is not list:
        return None
    args = get_args(ann)
    if not args:
        return None
    inner = args[0]
    if isinstance(inner, type) and issubclass(inner, WikibaseReferenceBase):
        return inner
    if get_origin(inner) is list:
        inner_args = get_args(inner)
        if inner_args and isinstance(inner_args[0], type) and issubclass(inner_args[0], WikibaseReferenceBase):
            return inner_args[0]
    return None


def _build_reference_block(ref_model: WikibaseReferenceBase) -> WBIReference | None:
    """Build one WBIReference block from a WikibaseReference instance. Returns None if empty."""
    ref_block = WBIReference()
    for ref_field in ref_model.get_reference_fields(WIKIBASE_ID):
        value = getattr(ref_model, ref_field, None)
        if value is None:
            continue
        meta = type(ref_model).model_fields[ref_field]
        extra = _get_schema_extra(meta)
        snak_claim = get_claim(
            prop_id=extra.get(WIKIBASE_ID),
            datatype=extra.get(WIKIBASE_TYPE),
            value=value,
            calendarmodel=_calendar_model_for(ref_model, ref_field, extra),
        )
        if snak_claim is not None:
            ref_block.add(snak_claim)
    return ref_block if len(ref_block) > 0 else None


def _attach_reference_blocks(claim: Claim, ref_models: list[WikibaseReferenceBase] | None) -> None:
    """Append non-empty reference blocks built from the given WikibaseReference instances to claim.references."""
    if not ref_models:
        return
    for ref_model in ref_models:
        block = _build_reference_block(ref_model)
        if block is not None:
            claim.references.add(block)


def _extract_reference_records(claim: Claim, ref_cls: type[WikibaseReferenceBase]) -> list[dict]:
    """Build the list of source dicts from claim.references suitable for ``model_validate``."""
    sources: list[dict] = []
    for ref_block in claim.references:
        block_record: dict = {}
        for ref_field in ref_cls.get_reference_fields(WIKIBASE_ID):
            meta = ref_cls.model_fields[ref_field]
            extra = meta.json_schema_extra if isinstance(meta.json_schema_extra, dict) else {}
            prop_id = extra.get(WIKIBASE_ID)
            prop_nr = Wikibase.get_entity_id(prop_id) if prop_id else None
            if prop_nr is None:
                continue
            snaks = ref_block.snaks.get(prop_nr)
            if not snaks:
                continue
            block_record[ref_field] = get_snak_value(snaks[0])
            cal_field = calendar_field_name(ref_field)
            if cal_field in ref_cls.model_fields:
                block_record[cal_field] = get_snak_calendar_model(snaks[0])
        if block_record:
            sources.append(block_record)
    return sources


def add_references_to_statement(claim: Claim, model: StatementBase) -> None:
    """Attach Wikibase reference blocks (claim.references) from a statement model's ``sources`` field."""
    _attach_reference_blocks(claim, getattr(model, "sources", None))


def populate_references_from_claim(claim: Claim, model_cls: type[StatementBase]) -> list[dict] | None:
    """
    Build the list of source dicts (suitable for record["sources"]) from claim.references.
    Returns None if model_cls has no sources field.
    """
    sources_field = model_cls.model_fields.get("sources")
    if sources_field is None:
        return None
    ref_cls = _wikibase_reference_class(sources_field)
    if ref_cls is None:
        return None
    return _extract_reference_records(claim, ref_cls)


def add_qualifier_values_to_statement(
    claim: Claim,
    model: StatementBase,
    stored_calendars: dict[str, list[tuple[str | None, str | None]]] | None = None,
):
    """
    Add the qualifier values of the given model to the given claim
    :param claim:
    :param model:
    :param stored_calendars: calendar models of the qualifier snaks this call replaces,
        keyed by property number — see ``_inherit_calendar_model``
    :return:
    """
    qualifier_fields = model.get_qualifier_fields(WIKIBASE_ID)
    for qualifier_field in qualifier_fields:
        qualifier_metadata: FieldInfo = model.model_fields.get(qualifier_field)
        extra = _get_schema_extra(qualifier_metadata)
        qualifier_prop_id = extra.get(WIKIBASE_ID)
        qualifier_type = extra.get(WIKIBASE_TYPE)
        qualifier_prop_nr = Wikibase.get_entity_id(qualifier_prop_id)
        qualifiers = []
        if qualifier_prop_nr is None or getattr(model, qualifier_field) is None:
            continue
        elif isinstance(getattr(model, qualifier_field), list):
            qualifier_values = getattr(model, qualifier_field)
            is_list = True
        else:
            qualifier_values = [getattr(model, qualifier_field)]
            is_list = False
        stored = (stored_calendars or {}).get(qualifier_prop_nr, [])
        for idx, value in enumerate(qualifier_values):
            explicit_calendar = _explicit_calendar_model(model, qualifier_field, idx if is_list else None)
            qualifier = get_claim(
                prop_id=qualifier_prop_nr,
                datatype=qualifier_type,
                value=value,
                calendarmodel=explicit_calendar or normalize_calendar_model(extra.get(CALENDAR_MODEL)),
            )
            if qualifier is not None and explicit_calendar is None:
                _inherit_calendar_model(qualifier, stored, single_valued=not is_list)
            qualifiers.append(qualifier)
        for snak in qualifiers:
            if snak is not None:
                claim.qualifiers.add(snak, action_if_exists=ActionIfExists.FORCE_APPEND)


def delete_property_statement_by_id(item: ItemEntity, statement_id: str, model_type: type[Statement]) -> bool:
    """
    Delete statement from given item
    :param item:
    :param statement_id:
    :param model_type:
    :return: True if the statement was deleted otherwise False if the statement was not found
    """
    subject_field = model_type.get_statement_subject(WIKIBASE_ID)
    subject_prop_id = model_type.model_fields.get(subject_field).json_schema_extra.get(WIKIBASE_ID)
    subject_prop_nr = Wikibase.get_entity_id(subject_prop_id)
    for claim in item.claims.get(subject_prop_nr):
        if _statement_ids_equal(claim.id, statement_id):
            claim.remove()
            return True
    return False


def delete_statement_by_matching_model(item: ItemEntity, model: StatementBase) -> bool:
    """
    Delete statement that matches given model
    :param item:
    :param model:
    :return:
    """
    subject_field = model.get_statement_subject(WIKIBASE_ID)
    subject_prop_id = model.model_fields.get(subject_field).json_schema_extra.get(WIKIBASE_ID)
    subject_prop_nr = Wikibase.get_entity_id(subject_prop_id)
    for claim in item.claims.get(subject_prop_nr):
        claim_model = get_model_from_qualified_statement(claim, model.__class__)
        if claim_model == model:
            claim.remove()
            return True
    return False


class StatementNotFoundError(LookupError):
    """Raised when a statement_id does not match any claim on the target item.

    Carries the offending id and the ids that *were* present so the API layer can
    surface an actionable 404 (rather than an opaque 500).
    """

    def __init__(self, statement_id: str, available_ids: list[str | None]):
        self.statement_id = statement_id
        self.available_ids = list(available_ids)
        super().__init__(f"Statement {statement_id!r} not found on item; available statement ids: {self.available_ids}")


def get_calim_by_statement_id(item: ItemEntity, statement_id: str) -> Claim | None:
    """
    Get claim from given statement id
    :param item:
    :param statement_id:
    :return:
    """
    for claim in item.claims:
        if _statement_ids_equal(claim.id, statement_id):
            return claim
    return None


def update_qualified_statement_from_model(item: ItemEntity, statement_id: str, model: StatementBase):
    """
    Update the statement with the given model
    :param statement_id:
    :param item:
    :param model:
    :return:
    """
    claim = get_calim_by_statement_id(item, statement_id)
    if claim is None:
        raise StatementNotFoundError(statement_id, [c.id for c in item.claims])
    statement_object_field = model.get_statement_subject(WIKIBASE_ID)
    statement_object_value = getattr(model, statement_object_field)
    statement_metadata = model.model_fields.get(statement_object_field)
    statement_extra = _get_schema_extra(statement_metadata)
    statement_prop_id = statement_extra.get(WIKIBASE_ID)
    statement_prop_nr = Wikibase.get_entity_id(statement_prop_id)
    statement_type = statement_extra.get(WIKIBASE_TYPE)
    if statement_object_value is not None:
        if (
            issubclass(model.__class__, ExtractedStatement)
            and statement_object_value == WikibaseSnakType.UNKNOWN_VALUE.value
        ):
            new_mainsnak = BaseDataType(prop_nr=statement_prop_nr, snaktype=WikibaseSnakType.UNKNOWN_VALUE)
        elif (
            issubclass(model.__class__, ExtractedStatement)
            and statement_object_value == WikibaseSnakType.NO_VALUE.value
        ):
            new_mainsnak = BaseDataType(prop_nr=statement_prop_nr, snaktype=WikibaseSnakType.NO_VALUE)
        else:
            explicit_calendar = _explicit_calendar_model(model, statement_object_field)
            stored = _stored_calendar_models([claim.mainsnak])
            new_mainsnak = get_claim(
                prop_id=statement_prop_id,
                datatype=statement_type,
                value=statement_object_value,
                calendarmodel=explicit_calendar or normalize_calendar_model(statement_extra.get(CALENDAR_MODEL)),
            )
            if explicit_calendar is None:
                _inherit_calendar_model(new_mainsnak, stored, single_valued=True)
        claim.mainsnak = new_mainsnak.mainsnak
    qualifier_fields = model.get_qualifier_fields(WIKIBASE_ID)
    stored_qualifier_calendars: dict[str, list[tuple[str | None, str | None]]] = {}
    for model_field in model.model_fields_set:
        if model_field not in qualifier_fields:
            continue
        qualifier_metadata = model.model_fields.get(model_field)
        qualifier_prop_id = _get_schema_extra(qualifier_metadata).get(WIKIBASE_ID)
        qualifier_prop_nr = Wikibase.get_entity_id(qualifier_prop_id)
        existing_snaks = list(claim.qualifiers.get(qualifier_prop_nr))
        stored_qualifier_calendars[qualifier_prop_nr] = _stored_calendar_models(existing_snaks)
        # remove existing values (iterate a copy: Qualifiers.remove mutates the
        # internal list returned by .get(), same WBI bug worked around in
        # _remove_property_claims above)
        for qualifier_snak in existing_snaks:
            claim.qualifiers.remove(qualifier_snak)
    add_qualifier_values_to_statement(claim, model, stored_qualifier_calendars)
    if "sources" in model.model_fields_set:
        # Reference blocks are replaced wholesale: clear and re-add from model.sources.
        claim.references.clear()
        add_references_to_statement(claim, model)
