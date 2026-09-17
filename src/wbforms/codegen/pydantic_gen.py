"""Generate Pydantic models from a LinkML schema at runtime."""

from pathlib import Path
from typing import Any, get_origin

import yaml
from linkml_runtime.utils.schemaview import SchemaView
from pydantic import AnyHttpUrl, ConfigDict, Field, create_model
from wikibaseintegrator import datatypes
from wikibaseintegrator.wbi_enums import WikibaseSnakType

from wbforms.datamodel.item import (
    CALENDAR_FIELD_SUFFIX,
    CALENDAR_MODEL,
    WIKIBASE_ID,
    WIKIBASE_TYPE,
    WIKIDATA_ID,
    EntityBase,
    ExtractedStatement,
    ItemBase,
    ItemStatementSubjectType,
    Statement,
    WikibaseReferenceBase,
)
from wbforms.datamodel.utils import make_field_optional, make_partial_model
from wbforms.wb_calendar import normalize_calendar_model

WIKIBASE_REFERENCE_CLASS_NAME = "WikibaseReference"
SUPPORTS_REFERENCES_ANNOTATION = "supports_references"
#: Slot-level annotation naming the default calendar model of a `time` slot.
CALENDAR_MODEL_ANNOTATION = "calendar_model"
#: Schema-root annotation naming the default calendar model of every `time` slot.
DEFAULT_CALENDAR_MODEL_ANNOTATION = "default_calendar_model"

# Term slots an entity_item class may declare to control requiredness of the
# label/description inherited from EntityBase. Maps slot name → fixed sentinel.
ENTITY_TERM_SLOTS: dict[str, str] = {
    "label": "rdfs:label",
    "description": "schema:description",
}

RANGE_TO_PYTHON: dict[str, Any] = {
    "string": str,
    "integer": int,
    "anyuri": AnyHttpUrl,
    "item_statement_subject": ItemStatementSubjectType,
    "boolean": bool,
    "float": float,
    "uri": str,
}

WIKIBASE_DTYPE_MAP: dict[str, str] = {
    "item": datatypes.Item.DTYPE,
    "url": datatypes.URL.DTYPE,
    "monolingualtext": datatypes.MonolingualText.DTYPE,
    "string": datatypes.String.DTYPE,
    "external-id": datatypes.ExternalID.DTYPE,
    "quantity": datatypes.Quantity.DTYPE,
    "time": datatypes.Time.DTYPE,
}

PYTHON_BASE_INFO: dict[str, tuple[type, type]] = {
    "entity_item": (EntityBase, ItemBase),
    "extracted_statement": (ExtractedStatement, Statement),
    "wikibase_reference": (WikibaseReferenceBase, WikibaseReferenceBase),
}


def _ann_dict(annotations) -> dict[str, str]:
    """Convert any annotation container (dict, JsonObj, …) to a plain {key: value_str} dict."""
    if not annotations:
        return {}
    result: dict[str, str] = {}
    try:
        pairs: list[tuple[Any, Any]]
        if isinstance(annotations, dict):
            pairs = list(annotations.items())
        else:
            pairs = [(k, annotations[k]) for k in annotations]
        for k, v in pairs:
            result[str(k)] = v.value if hasattr(v, "value") else str(v)
    except Exception:
        pass
    return result


def _slot_annotations(view: SchemaView, slot_name: str, class_name: str, induced_slot) -> dict[str, str]:
    """Return merged annotations for a slot in a class.

    LinkML SchemaView.induced_slot replaces (does not merge) annotations when slot_usage is present.
    To get a true merge we start from the global slot definition's annotations and then layer the
    current class's slot_usage annotations on top (slot_usage wins on conflicts).
    """
    base_slot = view.get_slot(slot_name)
    anns: dict[str, str] = _ann_dict(base_slot.annotations) if base_slot else {}
    # Also include whatever the induced slot carries (handles inherited slot_usage from ancestors).
    anns.update(_ann_dict(induced_slot.annotations))
    cls_def = view.get_class(class_name)
    if cls_def and cls_def.slot_usage and slot_name in cls_def.slot_usage:
        su = cls_def.slot_usage[slot_name]
        if su.annotations:
            anns.update(_ann_dict(su.annotations))
    return anns


def _is_statement_subject(anns: dict[str, str]) -> bool:
    val = anns.get("wikibase_id", "")
    parts = val.split("/")
    return len(parts) >= 2 and parts[-2] == "statement"


def _truthy(val) -> bool:
    """Treat True and the string 'true' (any case) as truthy. Everything else is falsy."""
    return val is True or (isinstance(val, str) and val.lower() == "true")


def _class_needs_wikibase_reference(view: SchemaView, cls) -> bool:
    """A class depends on WikibaseReference when it (a) opts in at class level, or
    (b) opts in any of its slots via slot_usage/slot annotations."""
    if _truthy(_ann_dict(cls.annotations).get(SUPPORTS_REFERENCES_ANNOTATION)):
        return True
    for slot_name in cls.slots or []:
        induced = view.induced_slot(slot_name, cls.name)
        anns = _slot_annotations(view, slot_name, cls.name, induced)
        if _truthy(anns.get(SUPPORTS_REFERENCES_ANNOTATION)):
            return True
    return False


def _is_time_slot(anns: dict[str, str]) -> bool:
    """True if the slot maps to the Wikibase `time` datatype."""
    wb_type = anns.get("wikibase_type")
    if not wb_type:
        return False
    return WIKIBASE_DTYPE_MAP.get(wb_type, wb_type) == datatypes.Time.DTYPE


def _build_field_def(
    slot,
    anns: dict[str, str],
    is_required: bool,
    is_stmt_subject: bool,
    models: dict,
    schema_calendar_model: str | None = None,
) -> tuple[Any, Any]:
    """Return (python_type, FieldInfo) for a single slot."""
    range_name = slot.range or "string"

    # Check if range refers to a generated schema class (statement-reference field)
    if range_name in models and range_name not in RANGE_TO_PYTHON:
        stmt_cls: Any = models[range_name]
        if slot.multivalued:
            return list[stmt_cls], Field(default_factory=list)
        else:
            return stmt_cls | None, Field(default=None)

    py_type: Any = RANGE_TO_PYTHON.get(range_name, str)

    if slot.multivalued:
        py_type = list[py_type]

    extra: dict[str, Any] = {}
    if wikibase_id := anns.get("wikibase_id"):
        extra[WIKIBASE_ID] = wikibase_id
    if wd_id := anns.get("wikidata_id"):
        extra[WIKIDATA_ID] = wd_id
    if wb_type := anns.get("wikibase_type"):
        extra[WIKIBASE_TYPE] = WIKIBASE_DTYPE_MAP.get(wb_type, wb_type)
    if _is_time_slot(anns):
        # Slot annotation wins over the schema-root default; both may be a bare QID.
        calendar_model = normalize_calendar_model(anns.get(CALENDAR_MODEL_ANNOTATION) or schema_calendar_model or None)
        if calendar_model:
            extra[CALENDAR_MODEL] = calendar_model

    field_kwargs: dict[str, Any] = {}
    if extra:
        field_kwargs["json_schema_extra"] = extra
    if slot.pattern:
        field_kwargs["pattern"] = slot.pattern

    if is_stmt_subject:
        default: Any = WikibaseSnakType.UNKNOWN_VALUE.value
        return py_type, Field(default=default, **field_kwargs)
    elif is_required:
        return py_type, Field(default=..., **field_kwargs)
    elif get_origin(py_type) is list:
        # Multivalued optional: keep as list[T] with empty-list default (not list[T] | None)
        return py_type, Field(default_factory=list, **field_kwargs)
    else:
        return py_type | None, Field(default=None, **field_kwargs)


def _build_term_field_def(slot_name: str, induced, anns: dict[str, str], class_name: str) -> tuple[Any, Any]:
    """Return (python_type, FieldInfo) for a declared `label`/`description` term slot.

    Declaring the slot lets the schema decide requiredness via `required:`; the Wikibase
    mapping stays fixed to the term sentinel (labels/descriptions are terms, not claims).
    """
    sentinel = ENTITY_TERM_SLOTS[slot_name]
    wikibase_id = anns.get("wikibase_id")
    if wikibase_id and wikibase_id != sentinel:
        raise ValueError(
            f"{class_name}.{slot_name}: the {slot_name} slot maps to {sentinel} and "
            f"must not carry a wikibase_id annotation ({wikibase_id!r})"
        )
    if induced.multivalued:
        raise ValueError(f"{class_name}.{slot_name}: the {slot_name} slot must not be multivalued")

    field_kwargs: dict[str, Any] = {"json_schema_extra": {WIKIBASE_ID: sentinel}}
    if induced.pattern:
        field_kwargs["pattern"] = induced.pattern
    if induced.description:
        field_kwargs["description"] = str(induced.description)

    if induced.required:
        return str, Field(default=..., **field_kwargs)
    return str | None, Field(default=None, **field_kwargs)


def _topological_order(view: SchemaView) -> list[str]:
    """Return class names in dependency order (parents and slot-range classes before dependents)."""
    visited: set[str] = set()
    result: list[str] = []
    all_class_names: set[str] = set(view.all_classes().keys())

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        cls = view.get_class(name)
        if cls is None:
            return
        if cls.is_a:
            visit(cls.is_a)
        # Treat slot ranges that are schema classes as dependencies
        for slot_name in cls.slots or []:
            slot_def = view.get_slot(slot_name)
            if slot_def and slot_def.range in all_class_names:
                visit(slot_def.range)
        # supports_references opt-in (class-level or slot-level) induces a dependency on WikibaseReference
        if _class_needs_wikibase_reference(view, cls) and WIKIBASE_REFERENCE_CLASS_NAME in all_class_names:
            visit(WIKIBASE_REFERENCE_CLASS_NAME)
        result.append(name)

    for name in view.all_classes():
        visit(name)
    return result


def generate_models(schema_path: Path) -> dict[str, type]:
    """Parse the LinkML schema and return a dict of generated Pydantic model classes."""
    raw = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    raw.pop("endpoints", None)
    schema_calendar_model = _ann_dict(raw.get("annotations")).get(DEFAULT_CALENDAR_MODEL_ANNOTATION)
    view = SchemaView(yaml.dump(raw))
    models: dict[str, type] = {}

    for class_name in _topological_order(view):
        cls_def = view.get_class(class_name)
        if cls_def is None:
            continue

        python_base_key = _ann_dict(cls_def.annotations).get("python_base")
        parent_name = cls_def.is_a

        if python_base_key is None and parent_name:
            parent_def = view.get_class(parent_name)
            if parent_def:
                python_base_key = _ann_dict(parent_def.annotations).get("python_base")

        if python_base_key not in PYTHON_BASE_INFO:
            continue

        root_base_cls, read_extra_cls = PYTHON_BASE_INFO[python_base_key]

        if parent_name and f"{parent_name}Base" in models:
            base_cls = models[f"{parent_name}Base"]
        else:
            base_cls = root_base_cls

        own_slots_ordered: list[str] = list(cls_def.slots or [])
        own_slots_set = set(own_slots_ordered)
        slot_usage_only: list[str] = [s for s in (cls_def.slot_usage or {}) if s not in own_slots_set]
        slots_to_gen = own_slots_ordered + slot_usage_only

        field_defs: dict[str, tuple[Any, Any]] = {}
        ref_cls: Any = models.get(WIKIBASE_REFERENCE_CLASS_NAME)
        for slot_name in slots_to_gen:
            induced = view.induced_slot(slot_name, class_name)
            anns = _slot_annotations(view, slot_name, class_name, induced)

            # Declared label/description term slot: overrides the required field
            # inherited from EntityBase so the schema controls requiredness.
            if python_base_key == "entity_item" and slot_name in ENTITY_TERM_SLOTS:
                field_defs[slot_name] = _build_term_field_def(slot_name, induced, anns, class_name)
                continue

            is_req = bool(induced.required)
            is_stmt_subj = _is_statement_subject(anns)
            if is_stmt_subj:
                is_req = False

            py_type, field_info = _build_field_def(induced, anns, is_req, is_stmt_subj, models, schema_calendar_model)
            field_defs[slot_name] = (py_type, field_info)

            # Time slots: pair the slot with a sibling `<slot>_calendar` field carrying the
            # per-value calendar model, so an existing Julian date survives a round-trip and
            # the form can override it. For multivalued slots the sibling is positional.
            if _is_time_slot(anns):
                if induced.multivalued:
                    field_defs[f"{slot_name}{CALENDAR_FIELD_SUFFIX}"] = (
                        list[str],
                        Field(default_factory=list),
                    )
                else:
                    field_defs[f"{slot_name}{CALENDAR_FIELD_SUFFIX}"] = (str | None, Field(default=None))

            # Slot-level supports_references: pair the slot with a sibling `<slot>_sources` field.
            if _truthy(anns.get(SUPPORTS_REFERENCES_ANNOTATION)) and ref_cls is not None:
                sources_type: Any = list[list[ref_cls]] if induced.multivalued else list[ref_cls]
                field_defs[f"{slot_name}_sources"] = (sources_type, Field(default_factory=list))

        # Class-level supports_references opt-in: a flat `sources: list[WikibaseReference]` per row.
        if _truthy(_ann_dict(cls_def.annotations).get(SUPPORTS_REFERENCES_ANNOTATION)) and ref_cls is not None:
            field_defs["sources"] = (list[ref_cls], Field(default_factory=list))

        model_title = _ann_dict(cls_def.annotations).get("model_title")
        _raw_enforce = _ann_dict(cls_def.annotations).get("enforce_unknown_stmt_name", False)
        enforce_stmt_name = _raw_enforce is True or (isinstance(_raw_enforce, str) and _raw_enforce.lower() == "true")
        if model_title or enforce_stmt_name:
            extra_attrs: dict = {"__module__": "wbforms.codegen"}
            if model_title:
                extra_attrs["model_config"] = ConfigDict(title=model_title)
            if enforce_stmt_name:
                extra_attrs["_enforce_unknown_stmt_name"] = True
            base_cls = type(f"_{class_name}Configured", (base_cls,), extra_attrs)

        base_model = create_model(
            f"{class_name}Base",
            __base__=base_cls,
            __module__="wbforms.codegen",
            **field_defs,
        )

        create_model_cls = create_model(
            f"{class_name}Create",
            __base__=base_model,
            __module__="wbforms.codegen",
        )

        update_model = make_partial_model(create_model_cls, f"{class_name}Update")

        # The read model is lenient: required fields are loosened to `T | None = None`
        # so partial items (missing mandatory values) can still be loaded into the form.
        # Requiredness stays enforced on the Create model.
        lenient_overrides = {
            name: make_field_optional(finfo) for name, finfo in base_model.model_fields.items() if finfo.is_required()
        }
        read_model = create_model(
            class_name,
            __base__=(base_model, read_extra_cls),
            __module__="wbforms.codegen",
            **lenient_overrides,
        )

        models[f"{class_name}Base"] = base_model
        models[f"{class_name}Create"] = create_model_cls
        models[f"{class_name}Update"] = update_model
        models[class_name] = read_model

    return models
