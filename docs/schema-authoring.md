# Authoring a LinkML schema for wbforms

This guide describes how to write a LinkML schema so that wbforms generates working REST
endpoints and a usable data-entry form. How the generation itself works is described in
[architecture.md](architecture.md); the bundled schemas
`src/wbforms/schema/ceur_graph.yaml` and `src/wbforms/schema/factgrid_besucherbuch.yaml`
are complete real-world examples.

## Mental model

A wbforms schema describes three kinds of classes:

| Kind | `python_base` annotation | Becomes |
|---|---|---|
| Item class | `entity_item` | a top-level editable Wikibase item (own form, own REST route). Gets `label`, `description`, `qid` automatically. |
| Statement class | `extracted_statement` | a qualified statement attached to an item (rendered as an editable row list inside the parent form; own statement REST route). |
| Reference class | `wikibase_reference` | the statement-level reference block ("sources"); the class **must be named `WikibaseReference`**. |

REST endpoints are **derived from the classes** — there is nothing extra to declare
(see § 6 for the conventions and override annotations).

Slots (fields) carry the mapping to Wikibase properties via annotations; the **path
segment of the property IRI decides the field's role** (direct statement, statement
subject, qualifier, or reference snak).

> **Important:** a class without a recognized `python_base` annotation (own or inherited
> via `is_a`) is **silently skipped** — no model, no endpoint, no form field.

## 1. Required boilerplate

Every schema starts with the same top matter (copy from `ceur_graph.yaml`):

```yaml
id: https://example.org/schema/library      # any unique URI
name: library                               # schema name
description: Example schema

prefixes:
  linkml: https://w3id.org/linkml/

default_range: string

imports:
  - linkml:types

types:
  anyuri:
    uri: xsd:anyURI
    base: str
  item_statement_subject:
    uri: xsd:string
    base: str
    description: "QID (Q\\d+) or Wikibase somevalue sentinel"
```

The two custom types are consumed by the codegen: `anyuri` becomes a validated
`AnyHttpUrl` field, `item_statement_subject` is the type used for the subject slot of a
statement class (it accepts a QID or the "unknown value" sentinel).

## 2. Defining slots

A slot is one form field. The Wikibase mapping lives in `annotations`:

```yaml
slots:
  title:
    range: string
    annotations:
      wikibase_id: "https://ceur-dev.wikibase.cloud/prop/direct/P5"
      wikidata_id: "http://www.wikidata.org/prop/direct/P1476"   # optional
      wikibase_type: monolingualtext
```

### `wikibase_id` — property IRI; the path decides the role

| IRI path segment | Role | Example (from `ceur_graph.yaml`) |
|---|---|---|
| `/prop/direct/Pxx` | direct statement on the item | `title` → `.../prop/direct/P5` |
| `/prop/statement/Pxx` | **subject of a statement class** (the "main value" of a qualified statement) | `scholar_id` → `.../prop/statement/P93` |
| `/prop/qualifier/Pxx` | qualifier inside a statement class | `series_ordinal` → `.../prop/qualifier/P18` |
| `/prop/reference/Pxx` | snak inside the `WikibaseReference` class | `stated_in` → `.../prop/reference/P34` |

A statement-subject slot should use `range: item_statement_subject`. It is automatically
made optional and defaults to the Wikibase "unknown value" sentinel, so statements can be
recorded before the subject item exists (see `object_named_as` below).

### `wikibase_type` — datatype and form widget

| `wikibase_type` | Wikibase datatype written | Form widget |
|---|---|---|
| `item` | `wikibase-item` | entity autocomplete (`ItemSearchInput`) |
| `time` | `time` | date/time picker (`DateTimeInput`) |
| `quantity` | `quantity` | number input |
| `url` | `url` | URL input |
| `string` | `string` | text input |
| `external-id` | `external-id` | text input |
| `monolingualtext` | `monolingualtext` | text input |

### `calendar_model` — calendar for `time` slots

Wikibase stores every time value together with a calendar model. Historical dates are
often recorded in the **Julian** calendar (`Q1985786`) rather than the **Gregorian**
default (`Q1985727`) — the FactGrid Besucherbuch persons are a typical case.

Each `wikibase_type: time` slot gets a companion `<slot>_calendar` model field (the same
pattern as `<slot>_sources`) and a calendar selector next to its date input. Two
annotations set the default that is applied when nothing else says otherwise:

```yaml
annotations:                              # schema root
  default_calendar_model: "Q1985786"      # default for every time slot

slots:
  date_of_death:
    range: string
    annotations:
      wikibase_id: "https://database.factgrid.de/prop/direct/P38"
      wikibase_type: time
      calendar_model: "Q1985727"          # this slot overrides the schema default
```

Precedence, most specific first:

1. the value the user picked in the form (`<slot>_calendar` on the request body);
2. the **calendar already stored** on the claim being updated — an existing Julian date
   keeps its calendar even when the date value itself is corrected, so editing an
   unrelated field never silently rewrites it;
3. the slot's `calendar_model` annotation;
4. the schema root's `default_calendar_model`;
5. Gregorian (`Q1985727`).

Both annotations accept a bare QID or a full IRI. Only Gregorian and Julian are offered in
the form, since those are the only calendar models Wikibase supports. Values whose stored
calendar differs from the field's default are flagged in the form so historical dates are
visible at a glance.

> Multivalued time slots pair positionally with `<slot>_calendar`, mirroring
> `<slot>_sources`. Because such claims are removed and rebuilt on update, an unchanged
> calendar is carried over by matching the time string.

### Other slot properties

| Property | Effect |
|---|---|
| `range` | Python type: `string`, `integer`, `anyuri`, `item_statement_subject`, `boolean`, `float` — or the name of a statement class (see § 4) |
| `multivalued: true` | list field; the form shows add/remove controls per value |
| `required: true` | required in the create form / POST body (set globally or per class via `slot_usage`) |
| `pattern` | regex validation, e.g. `orcid_id: pattern: "\\d{4}-\\d{4}-\\d{4}-\\d{3}[\\dX]"` |
| `wikidata_id` annotation | corresponding Wikidata property IRI, used for Wikidata migration/sync — not needed for the form itself |

> **Note on labels:** form labels are currently derived from the slot name
> (`author_name_string` → "Author Name String"). The `local_names` i18n entries seen in
> `factgrid_besucherbuch.yaml` are *not* consumed for form labels yet — choose readable
> slot names.

## 3. Defining classes

### Item classes (`entity_item`)

```yaml
classes:
  Paper:
    annotations:
      python_base: entity_item
    slots:
      - title
      - published_in
      - authors            # statement-reference slot, see § 4
    slot_usage:
      published_in:
        required: true     # per-class override
      title:
        annotations:
          supports_references: true   # this field gets a source-block editor
```

`label`, `description`, and `qid` are contributed by the base class. By default you do
not declare them as slots, and `label` and `description` appear as required inputs at
the top of the form.

To make the label or description optional (e.g. because existing items in the Wikibase
may lack a description), declare a slot literally named `label` or `description` on the
item class — the slot's `required:` flag then controls whether the input is mandatory:

```yaml
slots:
  description:
    range: string
    required: false      # description may be left empty

classes:
  Book:
    annotations:
      python_base: entity_item
    slots:
      - description
```

Rules for these term slots:

- Use `range: string`; the slot must **not** be `multivalued` and must **not** carry a
  `wikibase_id` annotation — the mapping is fixed (`rdfs:label` / `schema:description`).
  Violations raise a `ValueError` at startup.
- `pattern` and the slot's LinkML `description:` doc string are passed through to the
  generated field (the doc string is exposed in the form metadata).
- Requiredness can be overridden per class via `slot_usage`, like any other slot.
- Classes that do not declare the slot keep today's behavior: the input stays required.

### Statement classes (`extracted_statement`)

A statement class bundles one `/prop/statement/` subject slot with its
`/prop/qualifier/` slots:

```yaml
  ScholarSignature:
    annotations:
      python_base: extracted_statement
      enforce_unknown_stmt_name: true
      supports_references: true
      has_delete_by_object: true       # endpoint option, see § 6
    slots:
      - scholar_id         # /prop/statement/P93 — the subject
      - series_ordinal     # /prop/qualifier/P18
      - orcid_id           # /prop/qualifier/P87
      - object_named_as    # /prop/qualifier/P91 — free-text name
```

- `object_named_as` (the slot **must** have exactly this name — the frontend special-cases
  it) holds the textual name when the subject item is unknown.
- `enforce_unknown_stmt_name: true` makes the form require `object_named_as` when the
  subject is set to "unknown value".
- `supports_references: true` at class level gives every statement row a `sources` list
  rendered with the reference editor (requires a `WikibaseReference` class, § 5).
- `model_title: <Title>` sets the display title of the generated model.

### Inheritance

Use `is_a` plus `slot_usage` to derive variants; the `python_base` is inherited:

```yaml
  EditorSignature:
    is_a: ScholarSignature
    annotations:
      python_base: extracted_statement
      supports_references: true
    slot_usage:
      scholar_id:
        annotations:
          wikibase_id: "https://ceur-dev.wikibase.cloud/prop/statement/P10"
          wikibase_type: item
```

`slot_usage` can override `required`, annotations (`wikibase_id`, `wikibase_type`,
`supports_references`), etc. Annotation overrides are *merged* with the global slot
definition (the class-level value wins on conflicts). `ScholarlyArticle is_a Paper` in
`ceur_graph.yaml` shows the same pattern for item classes.

## 4. Attaching statements to items (statement-reference slots)

The item class points at its statement classes through slots whose `range` is the class
name — **no Wikibase annotations** on these:

```yaml
slots:
  authors:
    range: ScholarSignature
    multivalued: true
    inlined_as_list: true
```

In the form this renders as a `statement_list`: an editable table of statement rows with
its own add/edit/delete controls, backed by the statement REST endpoint (§ 6).

## 5. References ("sources")

To support statement-level references, define the reference class (name is fixed):

```yaml
  WikibaseReference:
    annotations:
      python_base: wikibase_reference
    slots:
      - stated_in        # /prop/reference/P34
      - reference_url    # /prop/reference/P66
      - retrieved        # /prop/reference/P24, wikibase_type: time
```

Then opt in where needed:

- **Class level** (on a statement class): `supports_references: true` → each statement
  row gets a `sources` block.
- **Slot level** (via `slot_usage` on an item class): the field gets a companion
  `<slot>_sources` field and a source-block editor under the input (list fields get one
  block list per value).

## 6. REST endpoints (derived, not declared)

Endpoints are derived from the classes (`src/wbforms/codegen/endpoints.py`); there is no
routing section in the schema. The conventions:

- Every `entity_item` class `Foo` gets an item route at `/foo` (lower-cased class name)
  with path parameter `foo_id`: `POST /foo/`, `GET/PUT/DELETE /foo/{foo_id}`.
- Every statement-reference slot on an item class mounts a statement route at
  `/foo/{foo_id}/<slot name>`: `GET` (list), `POST /`, `PUT/DELETE /{statement_id}`.
  In `ceur_graph.yaml`, `Paper.authors → ScholarSignature` yields
  `/paper/{paper_id}/authors`.
- **Inherited slots count.** A subclass (`ScholarlyArticle is_a Paper`) automatically
  gets its own item route *and* its own mounts of the inherited statement slots
  (`/scholarlyarticle/{scholarlyarticle_id}/authors`, …).
- A statement class used by several item classes is mounted once per slot
  (`Subject` → `/paper/{paper_id}/paper_subjects` and `/volume/{volume_id}/volume_subjects`).

Optional annotations override the conventions:

| Annotation | Where | Effect |
|---|---|---|
| `endpoint_prefix` | item class | route prefix (default: `/<classname lower>`) |
| `endpoint_tag` | item or statement class | OpenAPI tag (default: class name / `<Entity> <segment>`) |
| `generate_endpoint: false` | item class | generate the model but no routes |
| `endpoint_segment` | statement-reference slot | path segment (default: the slot name) |
| `has_get_by_id: true` | statement class | adds `GET /{statement_id}` |
| `has_delete_by_object: true` | statement class | adds `DELETE /` by `object_named_as` |

The two `has_*` flags are inherited via `is_a` (in `ceur_graph.yaml`, `EditorSignature`
inherits `has_delete_by_object` from `ScholarSignature`).

Because the form metadata is derived from the same `(entity, slot)` information, every
statement field in the form is always linked to its endpoint — there is no separate
routing declaration that could go out of sync.

## 7. Minimal working example

A complete schema with one item type and one statement type:

```yaml
id: https://example.org/schema/library
name: library
description: Minimal wbforms example

prefixes:
  linkml: https://w3id.org/linkml/

default_range: string

imports:
  - linkml:types

types:
  anyuri:
    uri: xsd:anyURI
    base: str
  item_statement_subject:
    uri: xsd:string
    base: str
    description: "QID (Q\\d+) or Wikibase somevalue sentinel"

slots:
  title:
    range: string
    annotations:
      wikibase_id: "https://my.wikibase.example/prop/direct/P5"
      wikibase_type: monolingualtext

  official_website:
    range: anyuri
    annotations:
      wikibase_id: "https://my.wikibase.example/prop/direct/P12"
      wikibase_type: url

  author_id:
    range: item_statement_subject
    annotations:
      wikibase_id: "https://my.wikibase.example/prop/statement/P50"
      wikibase_type: item

  series_ordinal:
    range: integer
    annotations:
      wikibase_id: "https://my.wikibase.example/prop/qualifier/P18"
      wikibase_type: string

  object_named_as:
    range: string
    annotations:
      wikibase_id: "https://my.wikibase.example/prop/qualifier/P91"
      wikibase_type: string

  authors:
    range: AuthorSignature
    multivalued: true
    inlined_as_list: true

classes:
  Book:
    annotations:
      python_base: entity_item
    slots:
      - title
      - official_website
      - authors
    slot_usage:
      title:
        required: true

  AuthorSignature:
    annotations:
      python_base: extracted_statement
      enforce_unknown_stmt_name: true
    slots:
      - author_id
      - series_ordinal
      - object_named_as
```

Run it:

```shell
WBFORMS_SCHEMA_PATH=/path/to/library.yaml uv run fastapi dev src/wbforms/main.py
```

The derived routes are `POST /book/`, `GET/PUT/DELETE /book/{book_id}`, and
`/book/{book_id}/authors` for the statement rows. Open `http://localhost:8000/` for the
form, `/docs` for the generated REST API, and `/api/schema/entities` to inspect the form
metadata. Point the `WBFORMS_WIKIBASE_*` variables at your Wikibase instance (see
[configuration.md](configuration.md)).

## 8. Checklist and common pitfalls

- [ ] Every class you want generated has `python_base` (own or via `is_a`) — otherwise it
      is skipped without an error.
- [ ] Property IRIs use the correct path for the field's role: `/prop/direct/`,
      `/prop/statement/`, `/prop/qualifier/`, `/prop/reference/`.
- [ ] Each statement class has exactly one `/prop/statement/` slot, with
      `range: item_statement_subject`.
- [ ] The free-text-name qualifier slot is literally named `object_named_as`.
- [ ] The reference class is literally named `WikibaseReference`.
- [ ] A statement class is only editable in the form when an item class references it
      through a statement-reference slot — that slot is what creates the route.
- [ ] The schema (or `WBFORMS_SCHEMA_PATH`) changed? Restart the server — codegen runs
      once at startup.
- [ ] Property IRIs must point at the **target** Wikibase (the one in
      `WBFORMS_WIKIBASE_WEBSITE`), not at Wikidata — `wikidata_id` is the place for the
      Wikidata mapping.
