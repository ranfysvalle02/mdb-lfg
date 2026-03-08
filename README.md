# mdb-lfg

# The Missing Schema: How a Code Generator Accidentally Created What the Industry Needs

*Every standard describes a slice of your application. None describes what your application needs from your database.*

---

## The Lie of `generate`

Here's the pitch: describe your app in plain English, press a button, and get production-ready code. Dozens of AI code generators make this promise. Most of them keep it — technically. The code compiles. The routes resolve. The UI renders.

Then you deploy it.

No indexes. No schema validation. No encryption on the PII fields. No search indexes on the fields users will actually search. Collections created with the implicit hope that MongoDB will somehow figure out your access patterns on its own.

The generated app *looks* right. It *runs* wrong.

This isn't the LLM's fault. The LLM understood your intent perfectly: "a pet daycare app with owners and activity logs." It knows what fields you need, what relationships exist, what endpoints to expose. The problem is what happens between understanding and infrastructure. There's a gap — a conceptual void — where someone or something needs to answer the question:

**Given what this application does, what should the database look like?**

Not the shape of the data. The *behavior* of the data. Which fields get queried together? Which ones need full-text search? Which contain PII? Which represent time-series measurements? Which entities are always accessed with their parent and should be embedded rather than referenced?

No standard answers this question. Not one.

---

## The Standards Graveyard

It's not for lack of trying. The industry has produced an impressive collection of schema languages, each solving exactly one part of the problem.

**JSON Schema** describes data shape. It tells you a field is a string, an integer, a required property. MongoDB even uses it natively via `$jsonSchema` for collection validation. But JSON Schema has no concept of access patterns. It can't express "users will filter by this field" or "this field contains sensitive PII that needs client-side encryption." It describes what data *is*, not how data *behaves*.

**OpenAPI** describes API surfaces. It catalogs endpoints, request bodies, response shapes, authentication flows. It's the gold standard for REST API documentation. But OpenAPI has zero awareness of the database behind those endpoints. It can tell you `GET /api/properties?status=active` exists. It cannot tell you that `status` needs an index, or that the query should use a compound index with `listing_date` for the sort, or that the `address` field behind the same entity needs an Atlas Search index for autocomplete.

**Prisma Schema** comes closer. It describes models, fields, relations, and even indexes. But Prisma is SQL-first. Its mental model is tables, rows, foreign keys, and JOIN operations. It has no concept of embedded documents — the single most important data modeling decision in MongoDB. No time-series collections. No Atlas Search. No Client-Side Field Level Encryption. No Change Streams. It maps beautifully to PostgreSQL. It maps awkwardly to MongoDB.

**DBML** is elegant for diagramming database schemas, but it inherits the same relational assumptions. Tables. Columns. Foreign keys. The vocabulary itself prevents it from expressing document-model-native concepts.

**MDA/PIM** (the OMG's Model-Driven Architecture) gets the *idea* right. A Platform-Independent Model that describes your application abstractly, then transforms into platform-specific code. That's exactly the right concept. But MDA ships as UML diagrams serialized in XMI/XML, requires enterprise tooling, and has the developer experience of filing a tax return. Nobody builds with it. Nobody ships it.

Every standard answers *one* question. None answers *the* question: given what my app does, what should my database look like?

---

## We Didn't Mean to Build a Standard

We built [LFG](https://github.com/mongodb-developer/mdb-lfg) — an AI-powered application generator that takes a natural language prompt ("pet daycare with pets and owners") and produces a complete, production-ready application: backend, frontend, database configuration, seed data, Docker setup, documentation. The whole thing, zipped and downloadable.

The architecture is a pipeline. An LLM understands the user's intent. Jinja2 templates render the code deterministically. But between understanding and rendering, we needed *something* — an intermediate representation that captured everything the templates needed to know.

So we built `AppSpec`. A Pydantic model. Internal plumbing. A data structure that could shuttle information from the LLM to the templates without losing any of the nuance.

Then we looked at what we'd built, and realized it was the most complete description of an application's database needs we'd ever seen.

Here's the pipeline:

```
"Pet daycare with pets and owners"
      |
      v
  LLM decomposes into EntityBriefs
  (with embedding_strategy: "separate" or "embed_in_parent")
      |
      v
  LLM enriches into EntitySpecs + DataFields
  (with access-pattern booleans: is_filterable, is_searchable, is_sensitive...)
      |
      v
  Deterministic derivation functions produce:
  indexes, validation, search configs, encryption, seed data
      |
      v
  Jinja2 templates render production-ready code
```

The LLM's job is to understand intent. The spec's job is to encode access patterns. The templates' job is to render infrastructure. `AppSpec` is the contract between understanding and infrastructure — and it turns out that contract is exactly the standard nobody built.

---

## One Boolean, Six Consequences

The power of this approach isn't in the schema itself. It's in the *cascade*. A single annotation on a single field ripples through the entire MongoDB stack, configuring multiple features simultaneously with zero manual intervention.

Take `is_sensitive: true` on an `email` field.

That one boolean triggers a chain reaction:

**1. Encryption algorithm selection.** The derivation function checks whether the field is *also* filterable. If it is, it picks `AEAD_AES_256_CBC_HMAC_SHA_512-Deterministic` — queryable encryption that still allows equality matching. If it isn't filterable, it picks `AEAD_AES_256_CBC_HMAC_SHA_512-Random` — stronger encryption, because you don't need to query on it. One boolean, and the system already made a nuanced cryptographic decision for you.

```python
algo = ("AEAD_AES_256_CBC_HMAC_SHA_512-Deterministic"
        if f.is_filterable
        else "AEAD_AES_256_CBC_HMAC_SHA_512-Random")
```

**2. Encryption config generation.** The field gets added to `encryption_config.json` with its BSON type and selected algorithm, ready for MongoDB's Client-Side Field Level Encryption driver.

**3. Schema validation.** Because the field's `type` is `email`, the `$jsonSchema` validator adds a regex pattern constraint: `^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$`. The BSON type is set to `string`. The field is marked as required if `required: true`.

**4. Search exclusion.** A sensitive email field should *not* appear in an Atlas Search index. The `is_searchable` flag is `false`, so the search index derivation skips it entirely. No full-text search on PII — by design, not by accident.

**5. UI form binding.** The `INPUT_TYPE_MAP` maps `email` to `type="email"` on the HTML input, giving browsers native email validation, autocomplete, and mobile keyboard optimization.

**6. Type mapping across languages.** The same field maps to `str` in Python, `string` in TypeScript, `string` in Go — all via the type map dictionaries.

One annotation. Six MongoDB features configured correctly. Zero manual decisions.

Now consider `is_filterable: true` on a `status` field:

- A **single-field index** is created: `{ status: 1 }`.
- If an endpoint declares `status` as a filter and `created_at` as a sort, a **compound index** is created following the ESR (Equality-Sort-Range) rule: `{ status: 1, created_at: -1 }`.
- If another field on the same entity has `is_vectorizable: true`, `status` becomes a **pre-filter field** in the Vector Search index definition: `{ "type": "filter", "path": "status" }`.
- If the same field is *also* `is_sensitive`, the CSFLE algorithm switches from Random to **Deterministic** — because you told the system you need to query on it.

Four MongoDB features. One boolean. The compound index even follows the ESR pattern automatically, because the derivation function places equality filters first (`1`) and sort fields second (`-1`).

---

## The Full Map

Here is every field in the spec and what it produces in MongoDB. This isn't theoretical — these are the actual derivation paths in the codebase.

| Spec Field | MongoDB Feature | Mechanism |
|---|---|---|
| `DataField.type` | BSON type + `$jsonSchema` validation | `BSON_TYPE_MAP` lookup, `render_mongodb_validation()` |
| `DataField.type == "email"` | Regex pattern in `$jsonSchema` | Hardcoded pattern in validation renderer |
| `DataField.type == "enum"` | `enum` constraint in `$jsonSchema` | `enum_values` list injected into schema |
| `DataField.type == "reference"` | Single-field index + `$lookup` aggregation | `_derive_indexes()` + `_derive_lookups()` |
| `DataField.is_filterable` | Index key (equality), ESR compound prefix, Vector Search filter, CSFLE Deterministic | `_derive_indexes()`, `_derive_vector_search_config()`, `_derive_sensitive_fields()` |
| `DataField.is_sortable` | Compound index sort position (descending) | `_derive_indexes()` with `compound_keys[s] = -1` |
| `DataField.is_searchable` | Atlas Search index with `lucene.standard` analyzer + `edgeGram` autocomplete | `_derive_search_indexes()` |
| `DataField.is_vectorizable` | Atlas Vector Search index (1536 dimensions, cosine similarity) | `_derive_vector_search_config()` |
| `DataField.is_sensitive` | CSFLE `encryption_config.json` with algorithm selection | `_derive_sensitive_fields()` |
| `EntitySpec.is_time_series` | Time-series collection (`timeField`, `metaField`, `granularity: "seconds"`) | `_derive_time_series_entities()` |
| `EntitySpec.real_time` | Change Streams + Server-Sent Events endpoint | `_derive_change_stream_collections()` |
| `EntityBrief.embedding_strategy` | Embedded sub-documents vs. separate collection | Decomposition logic: `"embed_in_parent"` nests the entity; `"separate"` creates its own collection |
| `Endpoint.filters + sort_fields` | Compound index derivation following ESR rule | `_derive_indexes()` cross-references endpoint filters with entity fields |
| `Endpoint.needs_join` | `$lookup` aggregation pipeline | Template rendering includes join stages |
| `sample_data + id_map` | Seed documents with valid `ObjectId` cross-references | Deterministic hex IDs via SHA-256, `_id` and reference fields linked across collections |

Every row in that table has a function behind it. No hand-waving. No "best practices recommended." The spec *produces* the infrastructure.

---

## It's Just a Document

Here's the part that makes you pause.

`AppSpec` is a Pydantic model. Call `.model_dump()` and you get a Python dictionary. That dictionary is a valid BSON document. You could do this:

```python
db.blueprints.insert_one(spec.model_dump())
```

The schema that describes how to build a MongoDB application *is itself a MongoDB document*.

You could query it:

```javascript
db.blueprints.find({
  "entities.fields": {
    $elemMatch: { is_sensitive: true, is_filterable: true }
  }
})
```

"Show me every blueprint where sensitive fields are also filterable" — because that's a security-relevant data modeling decision you'd want to audit across your organization's applications.

You could validate it with `$jsonSchema` — the same validation mechanism it generates for the applications it describes.

You could build aggregation pipelines on it:

```javascript
db.blueprints.aggregate([
  { $unwind: "$entities" },
  { $unwind: "$entities.fields" },
  { $match: { "entities.fields.is_searchable": true } },
  { $group: { _id: "$slug", searchable_fields: { $sum: 1 } } }
])
```

"How many searchable fields does each application have?" — because search index proliferation is a cost and performance concern you want visibility into.

The spec isn't just *about* MongoDB. It *is* MongoDB. Document in, documents out. The format is the platform.

---

## What If This Were a Standard?

Right now, `AppSpec` is internal plumbing. It lives inside one code generator, serialized once during the `design` phase, consumed by templates, and discarded after the zip file is built. It has no name, no version, no published schema. It's an accident.

But imagine if it weren't.

Imagine `atlas app init --from-spec blueprint.json`. One command. Atlas provisions collections with `$jsonSchema` validation. Creates standard indexes and compound indexes following the ESR rule. Configures Atlas Search indexes with the right analyzers and autocomplete. Sets up time-series collections with the correct `timeField` and `metaField`. Generates CSFLE encryption schemas for sensitive fields. Seeds the database with realistic, cross-referenced documents. Done. Your database matches your application's access patterns before you write a single line of application code.

Imagine Compass importing a blueprint and showing you a visual map: here are your entities, here are their relationships, here are the indexes you'll need, here are the fields that will be encrypted, here's which collections use Change Streams. Not documentation — a living contract between your application and your database.

Imagine Relational Migrator exporting *to* this format. You analyze your PostgreSQL schema, and instead of just getting a MongoDB schema, you get a full blueprint — with access patterns inferred from your existing queries, indexes derived from your existing indexes, and search fields identified from your existing `LIKE` queries and `tsvector` columns.

Imagine third-party ORMs — Mongoose, Prisma, Beanie, Motor — consuming the spec and generating typed models with the correct indexes already defined. Not just the types. The indexes. The validation. The encryption config. The search mappings.

Imagine developers sharing blueprints the way they share OpenAPI specs. "Here's the database contract for my e-commerce application." Fork it, modify it, generate a new app from it. A blueprint library indexed by industry, complexity, and MongoDB features used.

The gap in the standards landscape is real. JSON Schema describes what data *is*. OpenAPI describes what APIs *do*. Nothing describes what applications *need from their database*.

That's the standard nobody built. We built it by accident, because we needed it, and we didn't know it didn't exist until we went looking for it.

Maybe it's time to give it a name.

---

## Appendix A: The Full AppSpec Schema

The complete model hierarchy, reproduced from the codebase. These are Pydantic `BaseModel` classes used as structured output schemas for the LLM and as the contract between the AI and the deterministic code generation templates.

### DataField

The atomic unit — a single field on a data model, enriched with access-pattern metadata that drives every downstream derivation.

```python
class DataField(BaseModel):
    name: str           # snake_case field name
    type: str           # string | integer | float | boolean | datetime
                        # text | email | enum | reference
    label: str          # Human-readable label for UI forms
    description: str    # What this field represents
    required: bool      # Default: True

    # Access-pattern booleans — the core innovation
    is_filterable: bool   # Users will filter/search by this field
    is_sortable: bool     # Users will sort by this field
    is_searchable: bool   # Full-text search (names, titles, descriptions)
    is_vectorizable: bool # Semantic/similarity search on text
    is_sensitive: bool    # PII: email, SSN, phone, salary

    # Type-specific metadata
    enum_values: List[str]        # Allowed values for enum fields
    reference_collection: str     # Target collection for reference fields
```

### EntitySpec

A data entity — maps directly to a MongoDB collection.

```python
class EntitySpec(BaseModel):
    name: str              # PascalCase class name, e.g. "Ticket"
    collection: str        # MongoDB collection name in snake_case
    description: str       # What this entity represents
    fields: List[DataField]
    relationships: List[str]  # References to other entity names

    # MongoDB-native features
    real_time: bool        # Benefits from Change Streams (dashboards, feeds)
    is_time_series: bool   # Measurements, events, or logs over time
    time_field: str        # datetime field used as timeField
    meta_field: str        # field used as metaField for grouping
```

### EntityBrief

Lightweight entity description from the decomposition step — critically includes the embedding strategy decision.

```python
class EntityBrief(BaseModel):
    name: str               # PascalCase model name
    collection_name: str    # snake_case MongoDB collection name
    description: str        # What this entity represents
    key_fields: List[str]   # Important field names
    related_to: List[str]   # Other entities this one references

    # The core MongoDB data modeling decision
    embedding_strategy: str  # "separate" for its own collection,
                             # "embed_in_parent" if always accessed with parent
    parent_entity: str       # If embedded, the parent entity name
```

### Endpoint

An API endpoint, whose `filters` and `sort_fields` drive compound index derivation.

```python
class Endpoint(BaseModel):
    method: str          # HTTP method: GET, POST, PUT, DELETE
    path: str            # URL path, e.g. /initiatives/{id}
    description: str
    model_name: str      # Which EntitySpec this operates on
    filters: List[str]   # Field names this endpoint filters by
    sort_fields: List[str]  # Field names this endpoint sorts by
    needs_join: bool     # Requires data from related collections ($lookup)
```

### CustomPageSpec and PageSection

Non-CRUD pages (dashboards, activity logs, analytics views) with structured sections.

```python
class PageSection(BaseModel):
    type: str            # stat_cards | table | ranked_list | cross_table
    title: str           # Section heading
    source: str          # Collection name to fetch data from
    columns: List[str]   # Fields to display (table/cross_table)
    value_field: str     # Field to aggregate/rank by
    label_field: str     # Display label field (ranked_list)
    aggregate: str       # count | sum | avg (stat_cards)
    sort_field: str      # Default: created_at
    sort_dir: str        # asc | desc
    limit: int           # Max rows (default: 5)
    # Cross-collection join support
    lookup_collection: str
    lookup_field: str
    lookup_label: str

class CustomPageSpec(BaseModel):
    id: str                        # URL-safe page identifier
    label: str                     # Navigation tab label
    description: str               # What this page does
    data_collections: List[str]    # Collections this page fetches from
    sections: List[PageSection]    # Ordered list of UI sections
    is_default: bool               # Show first instead of CRUD
```

### AppSpec (the root)

The complete structured schema for a generated application.

```python
class AppSpec(BaseModel):
    app_name: str                    # Human-readable name
    slug: str                        # URL-safe kebab-case slug
    description: str
    auth_enabled: bool               # Generate JWT auth + login flow
    vector_search_enabled: bool      # Any field is vectorizable
    app_mode: str                    # "crud" or "dashboard"

    entities: List[EntitySpec]
    endpoints: List[Endpoint]

    sample_data: Dict[str, List[Dict]]         # collection -> seed documents
    embedded_entities: Dict[str, List[EntitySpec]]  # parent -> embedded children
    dashboard_widgets: Dict[str, List[Dict]]   # collection -> chart configs
    custom_pages: List[CustomPageSpec]          # Non-CRUD pages
    id_map: Dict[str, List[str]]               # collection -> pre-computed ObjectId hex strings
```

---

## Appendix B: Derivation Functions

These are the deterministic functions that transform `AppSpec` annotations into MongoDB infrastructure. No LLM involved — pure programmatic derivation. Each function reads the boolean flags and type annotations on `DataField` and `EntitySpec`, and produces the corresponding MongoDB configuration.

### Index Derivation (ESR-Aware)

Produces `createIndex()` calls following the Equality-Sort-Range pattern. Reference fields get their own index. Endpoint filter+sort combinations produce compound indexes. Remaining filterable fields get single-field indexes if not already covered.

```python
def _derive_indexes(spec: AppSpec) -> dict[str, list[dict]]:
    indexes: dict[str, list[dict]] = {}
    for entity in spec.entities:
        collection = entity.collection
        idx_list: list[dict] = []

        # Reference fields -> single-field indexes for $lookup joins
        ref_fields = [f for f in entity.fields if f.type == "reference"]
        for f in ref_fields:
            idx_list.append({
                "keys": {f.name: 1},
                "name": f"idx_{collection}_{f.name}",
                "reason": f"Foreign key lookup to {f.reference_collection}",
            })

        filterable = {f.name for f in entity.fields if f.is_filterable}
        sortable = {f.name for f in entity.fields if f.is_sortable}

        # Endpoint-driven compound indexes (ESR pattern)
        for ep in spec.endpoints:
            if ep.model_name != entity.name:
                continue
            if ep.filters and ep.sort_fields:
                compound_keys = {f: 1 for f in ep.filters if f in filterable}
                for s in ep.sort_fields:
                    if s in sortable:
                        compound_keys[s] = -1  # Sort fields descending
                if len(compound_keys) > 1:
                    name_parts = "_".join(compound_keys.keys())
                    idx_list.append({
                        "keys": compound_keys,
                        "name": f"idx_{collection}_{name_parts}",
                        "reason": f"Compound index for {ep.method} {ep.path}",
                    })

        # Remaining filterable fields -> single-field indexes
        for f in entity.fields:
            if f.is_filterable and f.type != "reference":
                already_covered = any(
                    f.name in idx["keys"] and len(idx["keys"]) == 1
                    for idx in idx_list
                )
                if not already_covered:
                    idx_list.append({
                        "keys": {f.name: 1},
                        "name": f"idx_{collection}_{f.name}",
                        "reason": f"Filter/search on {f.name}",
                    })

        if idx_list:
            indexes[collection] = idx_list
    return indexes
```

### Atlas Search Index Generation

Produces Atlas Search index definitions with `lucene.standard` analysis and `edgeGram` autocomplete for every field marked `is_searchable`.

```python
def _derive_search_indexes(spec: AppSpec) -> dict[str, dict]:
    search_indexes: dict[str, dict] = {}
    for entity in spec.entities:
        searchable = [f for f in entity.fields if f.is_searchable]
        if not searchable:
            continue
        field_mappings = {}
        for f in searchable:
            field_mappings[f.name] = {
                "type": "string",
                "analyzer": "lucene.standard",
                "multi": {
                    "autocomplete": {
                        "type": "autocomplete",
                        "tokenization": "edgeGram",
                        "minGrams": 2,
                        "maxGrams": 15,
                    }
                },
            }
        search_indexes[entity.collection] = {
            "name": f"{entity.collection}_search",
            "mappings": {"dynamic": False, "fields": field_mappings},
        }
    return search_indexes
```

### Atlas Vector Search Index Generation

Produces Vector Search index definitions for semantic search. Automatically adds filterable fields as pre-filter paths.

```python
def _derive_vector_search_config(spec: AppSpec) -> dict[str, dict]:
    vs_indexes: dict[str, dict] = {}
    for entity in spec.entities:
        vectorizable = [f for f in entity.fields if f.is_vectorizable]
        if not vectorizable:
            continue
        fields = []
        for f in vectorizable:
            fields.append({
                "type": "vector",
                "path": f"{f.name}_embedding",
                "numDimensions": 1536,
                "similarity": "cosine",
            })
        for f in entity.fields:
            if f.is_filterable:
                fields.append({"type": "filter", "path": f.name})
        vs_indexes[entity.collection] = {
            "name": f"{entity.collection}_vector_search",
            "type": "vectorSearch",
            "fields": fields,
        }
    return vs_indexes
```

### CSFLE Encryption Schema

Derives Client-Side Field Level Encryption configuration. The algorithm choice is automatic: Deterministic if the field is filterable (queryable encryption), Random otherwise (stronger, non-queryable).

```python
def _derive_sensitive_fields(spec: AppSpec) -> dict[str, list[dict]]:
    schema_map: dict[str, list[dict]] = {}
    for entity in spec.entities:
        sensitive = [f for f in entity.fields if f.is_sensitive]
        if not sensitive:
            continue
        fields = []
        for f in sensitive:
            algo = ("AEAD_AES_256_CBC_HMAC_SHA_512-Deterministic"
                    if f.is_filterable
                    else "AEAD_AES_256_CBC_HMAC_SHA_512-Random")
            fields.append({
                "path": f.name, "bsonType": "string", "algorithm": algo
            })
        schema_map[entity.collection] = fields
    return schema_map
```

### $lookup Aggregation Derivation

Produces `$lookup` pipeline stages from reference fields, linking collections via `ObjectId` foreign keys.

```python
def _derive_lookups(spec: AppSpec) -> dict[str, list[dict]]:
    lookups: dict[str, list[dict]] = {}
    for entity in spec.entities:
        model_lookups = []
        for f in entity.fields:
            if f.type == "reference" and f.reference_collection:
                model_lookups.append({
                    "from": f.reference_collection,
                    "localField": f.name,
                    "foreignField": "_id",
                    "as": f.reference_collection.rstrip("s"),
                })
        if model_lookups:
            lookups[entity.collection] = model_lookups
    return lookups
```

### Time-Series Collection Configuration

Produces `timeseries` options for `createCollection()` on entities flagged as time-series data.

```python
def _derive_time_series_entities(spec: AppSpec) -> list[dict]:
    ts_entities = []
    for e in spec.entities:
        if not e.is_time_series:
            continue
        ts_entities.append({
            "collection": e.collection,
            "name": e.name,
            "time_field": e.time_field or "created_at",
            "meta_field": e.meta_field or "",
            "granularity": "seconds",
        })
    return ts_entities
```

### $jsonSchema Validation Generation

Produces MongoDB `$jsonSchema` validation documents from entity fields. Handles BSON type mapping, enum constraints, email pattern validation, and required field lists.

```python
def render_mongodb_validation(spec: AppSpec) -> str:
    validations = {}
    for entity in spec.entities:
        properties = {}
        required = []
        for f in entity.fields:
            prop: dict = {"description": f.description or f.label}
            prop["bsonType"] = BSON_TYPE_MAP.get(f.type, "string")
            if f.type == "enum" and f.enum_values:
                prop["enum"] = f.enum_values
            if f.type == "email":
                prop["pattern"] = (
                    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
                )
            properties[f.name] = prop
            if f.required:
                required.append(f.name)
        validations[entity.collection] = {
            "$jsonSchema": {
                "bsonType": "object",
                "title": f"{entity.name} validation",
                "description": entity.description,
                "required": required,
                "properties": properties,
            }
        }
    return json.dumps(validations, indent=2)
```

---

## Appendix C: Type Maps

The translation layers between the spec's logical types and platform-specific types. Each map is consumed by a different part of the rendering pipeline.

### BSON Type Map (Spec Type to MongoDB)

Used by `$jsonSchema` validation and seed document generation.

```python
BSON_TYPE_MAP = {
    "string": "string",   "text": "string",      "email": "string",
    "enum": "string",      "integer": "int",      "float": "double",
    "boolean": "bool",     "datetime": "date",    "reference": "objectId",
    "array": "array",      "object": "object",
}
```

### HTML Input Type Map (Spec Type to UI)

Used by frontend templates (React, Vue) to render correct form input elements with native browser validation.

```python
INPUT_TYPE_MAP = {
    "string": "text",       "text": "textarea",
    "email": "email",       "enum": "select",
    "integer": "number",    "float": "number",
    "boolean": "checkbox",  "datetime": "datetime-local",
    "reference": "select",  "array": "text",
    "object": "textarea",
}
```

### Language-Specific Type Maps

The same logical type resolves to the correct native type for each supported backend language.

**Python:**
```python
{"string": "str", "integer": "int", "float": "float",
 "boolean": "bool", "datetime": "datetime", "reference": "str", ...}
```

**TypeScript:**
```python
{"string": "string", "integer": "number", "float": "number",
 "boolean": "boolean", "datetime": "Date", "reference": "string", ...}
```

**Go:**
```python
{"string": "string", "integer": "int64", "float": "float64",
 "boolean": "bool", "datetime": "time.Time", "reference": "string", ...}
```

One logical type. Four platform representations. Zero ambiguity.
