"""Frontend routes: schema metadata endpoint, entity-search proxy, and SPA shell."""

from pathlib import Path
from typing import get_args
import html
import re

import httpx
import yaml
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from wikibaseintegrator import datatypes

from wbforms.codegen import get_models
from wbforms.codegen.endpoints import derive_endpoints
from wbforms.datamodel.item import (
    CALENDAR_FIELD_SUFFIX,
    CALENDAR_MODEL,
    WIKIBASE_ID,
    WIKIBASE_TYPE,
    StatementBase,
    WikibaseReferenceBase,
    calendar_field_name,
)
from wbforms.settings import get_settings
from wbforms.wb_calendar import DEFAULT_CALENDAR_MODEL, calendar_model_options
from wbforms.wbgenerator import _is_list_annotation, _wikibase_reference_class, get_statement_field_type

_STATIC_DIR = Path(__file__).parent.parent / "static"

router = APIRouter()

_SKIP_FIELDS = {"qid", "statement_id", "sources"}
_INTERNAL_WB_IDS = {"rdf:subject", "rdfs:label", "schema:description"}

# Cache für das geladene Schema
_schema_cache: dict | None = None


def _get_schema() -> dict:
    """Lade und cache das LinkML Schema aus der Datei."""
    global _schema_cache
    if _schema_cache is None:
        schema_path = get_settings().schema_path
        _schema_cache = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    return _schema_cache


def _wikibase_type(field_info) -> str | None:
    extra = field_info.json_schema_extra
    if not isinstance(extra, dict):
        return None
    return extra.get(WIKIBASE_TYPE)


def _label(name: str) -> str:
    return name.replace("_", " ").title()


def _get_localized_label(slot_name: str, language: str = "de") -> str:
    """Hole das lokalisierte Label für einen Slot aus dem Schema.
    
    Falls der Slot local_names definiert hat, wird das Label für die
    angegebene Sprache zurückgegeben. Falls nicht, wird ein generisches
    Label aus dem Slot-Namen erstellt.
    """
    schema = _get_schema()

    # Suche nach dem Slot in den Slots des Schemas
    slots = schema.get("slots", {})
    if slot_name in slots:
        slot_def = slots[slot_name]
        local_names = slot_def.get("local_names", {})
        if local_names:
            # Versuche, das Label für die gewünschte Sprache zu finden
            lang_names = local_names.get(language, {})
            if lang_names:
                return lang_names.get("local_name_value", _label(slot_name))
            # Fallback: versuche englisch
            en_names = local_names.get("en", {})
            if en_names:
                return en_names.get("local_name_value", _label(slot_name))
            # Fallback: nehme den ersten verfügbaren lokalen Namen
            for lang_data in local_names.values():
                if isinstance(lang_data, dict) and "local_name_value" in lang_data:
                    return lang_data["local_name_value"]

    # Fallback: generisches Label aus dem Slot-Namen
    return _label(slot_name)


def _strict_variant(cls: type, all_models: dict) -> type:
    """Resolve a lenient read model to its strict Create variant so the form
    metadata reports the schema's requiredness, not the read model's leniency."""
    return all_models.get(f"{cls.__name__}Create", cls)


def _build_statement_fields(stmt_cls: type[StatementBase], language: str = "en") -> list[dict]:
    subject_field_name = stmt_cls.get_statement_subject(WIKIBASE_ID)
    fields = []
    for fname, finfo in stmt_cls.model_fields.items():
        if fname in _SKIP_FIELDS:
            continue
        # `<X>_calendar` companions are rendered alongside their base field, not as separate inputs.
        if fname.endswith(CALENDAR_FIELD_SUFFIX):
            continue
        extra = finfo.json_schema_extra if isinstance(finfo.json_schema_extra, dict) else {}
        wb_id = extra.get(WIKIBASE_ID, "")
        if wb_id in _INTERNAL_WB_IDS:
            continue
        entry = {
            "name": fname,
            "label": _get_localized_label(fname, language),
            "wikibase_type": _wikibase_type(finfo),
            "field_type": "list" if _is_list_annotation(finfo.annotation) else "single",
            "required": finfo.is_required(),
        }
        # Include default_value from json_schema_extra
        if "default_value" in extra:
            entry["default_value"] = extra["default_value"]
        # Include the full json_schema_extra as annotations for debugging and future use
        if extra:
            entry["annotations"] = extra
        if fname == subject_field_name:
            entry["is_subject"] = True
        if fname == "object_named_as":
            entry["is_object_named_as"] = True
        fields.append(entry)
    return fields


def _reference_class_for(stmt_cls: type[StatementBase]) -> type[WikibaseReferenceBase] | None:
    """Return the WikibaseReference subclass attached via the `sources` field, or None."""
    sources_field = stmt_cls.model_fields.get("sources")
    if sources_field is None:
        return None
    for arg in get_args(sources_field.annotation):
        if isinstance(arg, type) and issubclass(arg, WikibaseReferenceBase):
            return arg
    return None


def _build_reference_fields(ref_cls: type[WikibaseReferenceBase], language: str = "en") -> list[dict]:
    """Return frontend field descriptors for a WikibaseReference inner class."""
    fields = []
    for fname in ref_cls.get_reference_fields(WIKIBASE_ID):
        finfo = ref_cls.model_fields[fname]
        extra = finfo.json_schema_extra if isinstance(finfo.json_schema_extra, dict) else {}
        field_desc = {
            "name": fname,
            "label": _get_localized_label(fname, language),
            "wikibase_type": _wikibase_type(finfo),
            "field_type": "list" if _is_list_annotation(finfo.annotation) else "single",
            "required": finfo.is_required(),
        }
        # Include default_value from json_schema_extra
        if "default_value" in extra:
            field_desc["default_value"] = extra["default_value"]
        # Include the full json_schema_extra as annotations for debugging and future use
        if extra:
            field_desc["annotations"] = extra
        fields.append(field_desc)
    return fields


def _build_entity_schema(
    entity_name: str,
    model_cls: type[BaseModel],
    all_models: dict,
    endpoints: list[dict],
    language: str = "en",
) -> dict:
    fields: list[dict] = []

    # Always expose label and description as top-level text inputs; requiredness follows
    # the model (mandatory unless the schema declares the slot as optional).
    for meta_name in ["label", "description"]:
        finfo = model_cls.model_fields.get(meta_name)
        if finfo is None:
            continue
        # Use localized label for description if available in schema
        if meta_name == "description":
            label_value = _get_localized_label("description", language)
        elif meta_name == "label":
            # label is a special term slot without local_names in schema
            label_value = _get_localized_label("label", language)
        else:
            label_value = _label(meta_name)
        
        extra = finfo.json_schema_extra if isinstance(finfo.json_schema_extra, dict) else {}
        term_field: dict = {
            "name": meta_name,
            "label": label_value,
            "field_type": "single",
            "wikibase_type": "string",
            "required": finfo.is_required(),
        }
        if finfo.description:
            term_field["description"] = finfo.description
        # Include default_value from json_schema_extra
        if "default_value" in extra:
            term_field["default_value"] = extra["default_value"]
        # Include the full json_schema_extra as annotations for debugging and future use
        if extra:
            term_field["annotations"] = extra
        fields.append(term_field)

    for fname, finfo in model_cls.model_fields.items():
        if fname in _SKIP_FIELDS or fname in {"label", "description"}:
            continue
        # `<X>_sources` / `<X>_calendar` companions are rendered alongside their base
        # field, not as separate inputs.
        if fname.endswith("_sources") or fname.endswith(CALENDAR_FIELD_SUFFIX):
            continue

        extra = finfo.json_schema_extra if isinstance(finfo.json_schema_extra, dict) else {}
        wb_id = extra.get(WIKIBASE_ID, "")
        if wb_id in _INTERNAL_WB_IDS:
            continue

        # Statement-reference field (list[ScholarSignature], etc.)
        stmt_type = get_statement_field_type(finfo.annotation)
        if stmt_type is not None:
            stmt_name = stmt_type.__name__
            # The derived statement endpoint is linked to exactly this (entity, slot) pair.
            stmt_endpoint = next(
                (
                    ep
                    for ep in endpoints
                    if ep.get("type") == "statement"
                    and ep.get("parent_model") == entity_name
                    and ep.get("slot") == fname
                ),
                None,
            )
            ref_cls = _reference_class_for(stmt_type)
            if ref_cls is not None:
                ref_cls = _strict_variant(ref_cls, all_models)
            fields.append(
                {
                    "name": fname,
                    "label": _get_localized_label(fname, language),
                    "field_type": "statement_list",
                    "statement_model": stmt_name,
                    "statement_endpoint": stmt_endpoint["prefix"] if stmt_endpoint else None,
                    "statement_fields": _build_statement_fields(_strict_variant(stmt_type, all_models), language),
                    "enforce_unknown_stmt_name": bool(getattr(stmt_type, "_enforce_unknown_stmt_name", False)),
                    "supports_references": ref_cls is not None,
                    "reference_fields": _build_reference_fields(ref_cls, language) if ref_cls is not None else [],
                }
            )
            continue

        if not wb_id or wb_id in _INTERNAL_WB_IDS:
            continue

        descriptor: dict = {
            "name": fname,
            "label": _get_localized_label(fname, language),
            "field_type": "list" if _is_list_annotation(finfo.annotation) else "single",
            "wikibase_type": _wikibase_type(finfo),
            "required": finfo.is_required(),
        }
        # Include default_value from json_schema_extra
        if "default_value" in extra:
            descriptor["default_value"] = extra["default_value"]
        # Include the full json_schema_extra as annotations for debugging and future use
        if extra:
            descriptor["annotations"] = extra
        sources_field = model_cls.model_fields.get(f"{fname}_sources")
        if sources_field is not None:
            ref_cls = _wikibase_reference_class(sources_field)
            if ref_cls is not None:
                descriptor["supports_references"] = True
                descriptor["reference_fields"] = _build_reference_fields(_strict_variant(ref_cls, all_models), language)
        fields.append(descriptor)

    return {"name": entity_name, "fields": fields}


@router.get("/api/config")
def get_public_config() -> dict:
    """Public configuration the SPA needs before login (OAuth version, wiki URL)."""
    s = get_settings()
    return {
        "oauth_version": s.oauth_version,
        "oauth_configured": bool(
            s.oauth_client_id
            and s.oauth_client_secret
            and s.oauth_client_secret.get_secret_value()
            and s.oauth_redirect_uri
        ),
        "wikibase_website": s.wikibase_website.unicode_string(),
    }


@router.get("/api/schema/entities")
def get_schema_entities(
    language: str = Query(default="de", description="Language for localized labels (e.g., 'en', 'de')")
) -> list[dict]:
    """Return schema metadata for all item-type entities, suitable for form generation.
    
    The language parameter controls which localized labels are returned for fields.
    Falls back to English if the requested language is not available.
    """
    endpoints = derive_endpoints(get_settings().schema_path)

    item_endpoints = [ep for ep in endpoints if ep.get("type") == "item"]
    all_models = get_models()

    result = []
    for ep in item_endpoints:
        model_name: str = ep["model"]
        # Use the strict Create model so `required` reflects the schema; the read
        # model is lenient (all fields optional) to allow loading partial items.
        model_cls = all_models.get(f"{model_name}Create") or all_models.get(model_name)
        if model_cls is None:
            continue
        entity = _build_entity_schema(model_name, model_cls, all_models, endpoints, language)
        entity["endpoint_prefix"] = ep["prefix"]
        entity["id_param"] = ep.get("id_param", "item_id")
        result.append(entity)

    return result


@router.get("/api/entity-search")
async def entity_search(q: str = Query(..., min_length=1), limit: int = 10, language: str = "de") -> list[dict]:
    """Proxy to wbsearchentities to avoid CORS issues from the browser."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            get_settings().wikibase_mediawiki_api_url.unicode_string(),
            # Params-Dict for API:wbsearchentities
            # Problem searching for labels without phrasing/masking, so e.g.
            # you won't find 'Friedrich Melchior Grimm' with search-q 'Grimm'
            # but you will find other X Y Grimm because e.g. they have 'Grimm' in Alias.
            # Swapping to API:query list=search returns better results.
            # params={
            #     "action": "wbsearchentities",
            #     "search": q,
            #     "language": language,
            #     "strictlanguage": 1,
            #     "uselang": language,
            #     "type": "item",
            #     "format": "json",
            #     "formatversion": 2,
            #     "limit": limit,
            # },
            params = {
                "action": "query",
                "format": "json",
                "uselang": language,
                "list": "search",
                "formatversion": 2,
                "srsearch": q,
                "srnamespace": "120",
                "srlimit": limit,
                "srprop": "size|wordcount|timestamp|snippet|titlesnippet|extensiondata|redirecttitle|sectiontitle"
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        results = []
        for r in resp.json().get("query", {}).get("search", []):
            def clean_html(text):
                return html.unescape(re.sub(r'<[^>]+>', '', text))
            results.append({
                "id": re.sub("Item:", "", r.get("title", "")),
                "label": clean_html(r.get("titlesnippet", r.get("title", ""))),
                "description": clean_html(r.get("snippet", "")),
                "match": None,
                "display": clean_html(r.get("titlesnippet", r.get("title", ""))),
            })
        return results


@router.get("/api/entity-label")
async def entity_label(qid: str = Query(...), language: str = "de") -> dict:
    """Resolve a single QID to its label and description via wbgetentities."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            get_settings().wikibase_mediawiki_api_url.unicode_string(),
            params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "labels|descriptions",
                "languages": language,
                "uselang": language,
                "format": "json",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
    entities = resp.json().get("entities", {})
    entity = entities.get(qid, {})
    label = entity.get("labels", {}).get(language, {}).get("value", qid)
    description = entity.get("descriptions", {}).get(language, {}).get("value", "")
    return {"qid": qid, "label": label, "description": description}


@router.get("/")
def serve_index() -> FileResponse:
    return _index_response()


@router.get("/form/{path:path}")
def serve_form(path: str) -> FileResponse:
    return _index_response()


def _index_response() -> FileResponse:
    """Serve the SPA shell without allowing stale cross-deployment caching."""
    return FileResponse(
        _STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
