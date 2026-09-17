# LinkML Schema Loading Analysis

**Date:** 2026-09-16  
**Schema:** `factgrid_besucherbuch.yaml`  
**Purpose:** Understanding how LinkML schema annotations flow through to Python data structures and JavaScript objects

---

## Table of Contents

1. [Schema Path](#1-schema-path)
2. [Raw YAML Content](#2-raw-yaml-content)
3. [SchemaView Creation](#3-schemaview-creation)
4. [Slot Annotations Resolution](#4-slot-annotations-resolution)
5. [Pydantic Model Generation](#5-pydantic-model-generation)
6. [Instance_of Field in FamilyName](#6-instance_of-field-in-familyname)
7. [Flow to JavaScript](#7-flow-to-javascript)
8. [Full Data Flow Summary](#8-full-data-flow-summary)
9. [How to Fix: Make default_value Available](#9-how-to-fix-make-default_value-available)

---

## 1. Schema Path

```
Schema file: /home/chris/wbforms/src/wbforms/schema/factgrid_besucherbuch.yaml
Exists: True
```

---

## 2. Raw YAML Content

### FamilyName Class Definition

```json
{
  "annotations": {
    "python_base": "entity_item"
  },
  "slots": [
    "instance_of",
    "description"
  ],
  "slot_usage": {
    "instance_of": {
      "annotations": {
        "default_value": "Q24499"
      }
    }
  }
}
```

### Global 'instance_of' Slot Definition

```json
{
  "range": "string",
  "ifabsent": "https://database.factgrid.de/entity/Q7",
  "local_names": {
    "en": {
      "local_name_value": "instance of"
    },
    "de": {
      "local_name_value": "ist ein/e"
    }
  },
  "annotations": {
    "wikibase_id": "https://database.factgrid.de/prop/direct/P2",
    "wikibase_type": "item"
  }
}
```

---

## 3. SchemaView Creation

```
SchemaView created successfully
All classes: ['FamilyName', 'PersonGroup', 'Person_Besucherbuch', 'StayIn', 'WikibaseReference']
All slots: ['adb', 'aristocratic', 'begin_date', 'biographical_notes', 'career_statement', 'country_citizenship', 'date_of_birth', 'date_of_death', 'description', 'end_date', 'family_name', 'given_name', 'gnd_id', 'instance_of', 'literal_statement', 'location_identiy', 'notate', 'note', 'note_qual', 'online_digistation', 'online_information', 'other_person_id', 'page', 'person_group', 'place_from', 'place_of_birth', 'place_of_death', 'position', 'primary_source', 'ref_begin_date', 'ref_end_date', 'ref_literal_statement', 'ref_online_digistation', 'ref_page', 'ref_primary_source', 'ref_wikisource_page', 'research_project_reference', 'station_id', 'stay_in', 'wbis_id', 'work_location']
```

---

## 4. Slot Annotations Resolution

```
FamilyName class name: FamilyName
FamilyName slots: ['instance_of', 'description']
FamilyName slot_usage: {'instance_of': SlotDefinition({
  'name': 'instance_of',
  'annotations': {'default_value': Annotation({'tag': 'default_value', 'value': 'Q24499'})}
})}

Induced slot 'instance_of' for FamilyName:
  name: instance_of
  range: string
  required: None
  annotations (raw): JsonObj(default_value=Annotation({'tag': 'default_value', 'value': 'Q24499'}))
  annotations (converted): {'default_value': 'Q24499'}

Merged annotations (base slot + slot_usage):
  wikibase_id: https://database.factgrid.de/prop/direct/P2
  wikibase_type: item
  default_value: Q24499

✓ default_value found in merged annotations: 'Q24499'
```

---

## 5. Pydantic Model Generation

```
Generated model classes: ['FamilyNameBase', 'FamilyNameCreate', 'FamilyNameUpdate', 'FamilyName', 'WikibaseReferenceBase', 'WikibaseReferenceCreate', 'WikibaseReferenceUpdate', 'WikibaseReference', 'PersonGroupBase', 'PersonGroupCreate', 'PersonGroupUpdate', 'PersonGroup', 'StayInBase', 'StayInCreate', 'StayInUpdate', 'StayIn', 'Person_BesucherbuchBase', 'Person_BesucherbuchCreate', 'Person_BesucherbuchUpdate', 'Person_Besucherbuch']

FamilyNameBase model fields:

  Field: label
    type: <class 'str'>
    required: True
    default: PydanticUndefined
    default_factory: None
    json_schema_extra: {'WIKIBASE_ID': 'rdfs:label'}

  Field: description
    type: str | None
    required: False
    default: None
    default_factory: None
    json_schema_extra: {'WIKIBASE_ID': 'schema:description'}

  Field: instance_of
    type: str | None
    required: False
    default: Q24499
    default_factory: None
    json_schema_extra: {'WIKIBASE_ID': 'https://database.factgrid.de/prop/direct/P2', 'wikibase_type': 'wikibase-item', 'default_value': 'Q24499'}
```

---

## 6. Instance_of Field in FamilyName

```
Field name: annotation=Union[str, NoneType] required=False default='Q24499' json_schema_extra={'WIKIBASE_ID': 'https://database.factgrid.de/prop/direct/P2', 'wikibase_type': 'wikibase-item', 'default_value': 'Q24499'}
  annotation (type): str | None
  is_required: False
  default: Q24499
  default_factory: None

  json_schema_extra contents:
    WIKIBASE_ID: https://database.factgrid.de/prop/direct/P2
    wikibase_type: wikibase-item
    default_value: Q24499

  ✓ default_value IS available in json_schema_extra: Q24499
```

---

## 7. Flow to JavaScript (FastAPI/React)

The generated Pydantic models are used by FastAPI, which automatically:

1. Generates OpenAPI schema from Pydantic model fields
2. The json_schema_extra dict is included in the OpenAPI schema
3. React/TypeScript frontend can access this via:
   - Fetching `/openapi.json`
   - Or via FastAPI's automatic JSON Schema generation

For the `instance_of` field in FamilyName:
- The `'default_value'` annotation from slot_usage **is now** available in:
  `FamilyNameBase.model_fields['instance_of'].json_schema_extra['default_value']`

- This **is now** available to the frontend as metadata
- The actual Pydantic field default is now `Q24499` (was `None` before the fix)

To use this as an actual default value in the form, you would need to:
1. Extract it from `json_schema_extra` in the frontend
2. Or use the actual field default which is now set correctly

---

## 8. Full Data Flow Summary

```
LinkML Schema (factgrid_besucherbuch.yaml)
    └── classes.FamilyName.slot_usage.instance_of.annotations.default_value = "Q24499"
        
    → SchemaView (linkml_runtime)
        └── Merges slot_usage annotations with base slot annotations
        └── view.induced_slot() returns the effective slot definition
        
    → Codegen (_slot_annotations in pydantic_gen.py)
        └── Extracts all annotations via _ann_dict()
        └── Merges: base_slot.annotations + induced_slot.annotations + slot_usage.annotations
        └── Returns: {"wikibase_id": "...", "wikibase_type": "...", "default_value": "Q24499", ...}
        
    → Pydantic Field Definition (_build_field_def in pydantic_gen.py)
        └── NOW includes ALL annotations in json_schema_extra (not just wikibase_id, wikidata_id, wikibase_type)
        └── default_value IS included in json_schema_extra (FIXED!)
        └── default_value IS used as Field(default=...) - it's now used as the actual default!
        
    → Generated Pydantic Model (FamilyNameBase)
        └── instance_of field has:
            - annotation: str | None
            - default: Q24499 (was None before)
            - json_schema_extra: {"wikibase_id": "...", "wikibase_type": "...", "default_value": "Q24499"}
            - default_value: NOW AVAILABLE! (in json_schema_extra)
        
    → FastAPI Endpoint
        └── Uses the Pydantic model for request/response validation
        └── OpenAPI schema includes json_schema_extra (default_value is now present)
        
    → React Frontend
        └── CAN NOW read default_value from the OpenAPI schema
        └── The annotation is now available in the Python->JS flow
```

---

## 9. How to Fix: Make default_value Available

To make `'default_value'` (and other custom annotations) flow through to the frontend, the fix was implemented in `_build_field_def` in `pydantic_gen.py`:

### Implemented Solution (Option C: Both - Include in json_schema_extra AND Use as Default)

**File:** `src/wbforms/codegen/pydantic_gen.py`  
**Location:** Lines 141-172

**Changes made:**

1. Include all annotations in json_schema_extra:
```python
# Include all other annotations as-is (e.g., default_value)
for key, value in anns.items():
    if key not in ("wikibase_id", "wikidata_id", "wikibase_type"):
        # Skip callable values (like _if_missing function from JsonObj)
        if not callable(value):
            extra[key] = value
```

2. Use default_value as actual field default:
```python
# Use default_value as actual Field default when present (for optional fields)
if default_val := anns.get("default_value"):
    field_kwargs["default"] = default_val
```

3. Refactored return statements to avoid conflicts:
```python
if is_stmt_subject:
    field_kwargs["default"] = WikibaseSnakType.UNKNOWN_VALUE.value
    return py_type, Field(**field_kwargs)
elif is_required:
    field_kwargs["default"] = ...
    return py_type, Field(**field_kwargs)
else:
    # Only set default=None if no default was set from annotations
    if "default" not in field_kwargs:
        field_kwargs["default"] = None
    return py_type | None, Field(**field_kwargs)
```

**Effect:** This makes `'default_value'` and any other custom annotations available in `json_schema_extra`, making them available through the OpenAPI schema to the frontend. Additionally, `default_value` is now used as the actual Pydantic field default.

---

## Conclusion

Your `default_value: Q24499` annotation in `slot_usage` is now correctly defined in the LinkML schema and is properly read by the `SchemaView`. The code generation in `pydantic_gen.py` now includes ALL annotations (not just three specific ones) into the Pydantic model's `json_schema_extra`. The `default_value` is also used as the actual field default.

This means custom annotations, including `default_value`, now flow through to the frontend via the OpenAPI schema.

---

**Test Script:** [`test_schema_loading.py`](../test_schema_loading.py)  
**Schema File:** [`factgrid_besucherbuch.yaml`](../src/wbforms/schema/factgrid_besucherbuch.yaml)  
**Codegen File:** [`pydantic_gen.py`](../src/wbforms/codegen/pydantic_gen.py)

**Status:** ✅ FIXED - All tests pass, default_value is now available in models and JSON schema