#!/usr/bin/env python3
"""
AppSpec Demo — The Missing Schema
==================================
A standalone demonstration of AppSpec: a structured intermediate representation
that captures what an application needs from MongoDB — not just data shape,
but access patterns, security, search, time-series, and embedding strategy.

One natural language prompt. One LLM call. Every MongoDB feature configured.

Usage:
    python demo.py "pet daycare with pets and owners"   # LLM-generated spec
    python demo.py                                       # Built-in example (no LLM)
    python demo.py --json "inventory tracker"            # Raw JSON artifacts
    python demo.py --export spec.json "recipe app"       # Export portable document
    python demo.py --mongo "task management"             # Output mongosh commands

Environment:
    LITELLM_MODEL   Model to use (default: gemini/gemini-2.5-flash)
    GEMINI_API_KEY   API key for Gemini (or set provider-specific key)

Requirements:
    pip install pydantic litellm
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

try:
    import litellm
    HAS_LITELLM = True
except ImportError:
    HAS_LITELLM = False


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TYPE MAPS
# ═══════════════════════════════════════════════════════════════════════════════

BSON_TYPE_MAP = {
    "string": "string", "text": "string", "email": "string", "enum": "string",
    "integer": "int", "float": "double", "boolean": "bool",
    "datetime": "date", "reference": "objectId",
    "array": "array", "object": "object",
}

INPUT_TYPE_MAP = {
    "string": "text", "text": "textarea", "email": "email",
    "enum": "select", "integer": "number", "float": "number",
    "boolean": "checkbox", "datetime": "datetime-local", "reference": "select",
    "array": "text", "object": "textarea",
}

TYPE_MAP_PYTHON = {
    "string": "str", "text": "str", "email": "str", "enum": "str",
    "reference": "str", "integer": "int", "float": "float",
    "boolean": "bool", "datetime": "datetime",
    "array": "list", "object": "dict",
}

TYPE_MAP_TYPESCRIPT = {
    "string": "string", "text": "string", "email": "string", "enum": "string",
    "reference": "string", "integer": "number", "float": "number",
    "boolean": "boolean", "datetime": "Date",
    "array": "string[]", "object": "Record<string, any>",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PYDANTIC MODELS — The AppSpec Schema
# ═══════════════════════════════════════════════════════════════════════════════


class DataField(BaseModel):
    """A single field on a data model, enriched with access-pattern metadata."""
    name: str = Field(..., description="snake_case field name")
    type: str = Field(
        ...,
        description="One of: string, integer, float, boolean, datetime, text, email, enum, reference",
    )
    label: str = Field(..., description="Human-readable label for UI forms")
    description: str = Field(default="", description="What this field represents")
    required: bool = Field(default=True)
    is_filterable: bool = Field(default=False, description="Users will filter/search by this field")
    is_sortable: bool = Field(default=False, description="Users will sort by this field")
    is_searchable: bool = Field(default=False, description="Full-text search target")
    is_vectorizable: bool = Field(default=False, description="Semantic/similarity search target")
    is_sensitive: bool = Field(default=False, description="PII — needs CSFLE encryption")
    enum_values: List[str] = Field(default_factory=list, description="Allowed values for enum fields")
    reference_collection: str = Field(default="", description="Target collection for reference fields")


class EntitySpec(BaseModel):
    """A data entity — maps directly to a MongoDB collection."""
    name: str = Field(..., description="PascalCase class name")
    collection: str = Field(..., description="MongoDB collection name in snake_case")
    description: str = Field(default="", description="What this entity represents")
    fields: List[DataField]
    relationships: List[str] = Field(default_factory=list, description="References to other entity names")
    real_time: bool = Field(default=False, description="Benefits from Change Streams")
    is_time_series: bool = Field(default=False, description="Time-series collection")
    time_field: str = Field(default="", description="datetime field used as timeField")
    meta_field: str = Field(default="", description="field used as metaField for grouping")


class Endpoint(BaseModel):
    """An API endpoint whose filters and sorts drive compound index derivation."""
    method: str = Field(..., description="HTTP method: GET, POST, PUT, DELETE")
    path: str = Field(..., description="URL path, e.g. /properties/{id}")
    description: str = Field(default="")
    model_name: str = Field(..., description="Which EntitySpec this operates on")
    filters: List[str] = Field(default_factory=list, description="Field names this endpoint filters by")
    sort_fields: List[str] = Field(default_factory=list, description="Field names this endpoint sorts by")
    needs_join: bool = Field(default=False, description="Requires $lookup from related collections")


class PageSection(BaseModel):
    """One visual section of a custom page."""
    type: str = Field(..., description="stat_cards | table | ranked_list | cross_table")
    title: str = Field(default="", description="Section heading")
    source: str = Field(..., description="Collection name to fetch data from")
    columns: List[str] = Field(default_factory=list)
    value_field: str = Field(default="")
    label_field: str = Field(default="")
    aggregate: str = Field(default="count")
    sort_field: str = Field(default="created_at")
    sort_dir: str = Field(default="desc")
    limit: int = Field(default=5)
    lookup_collection: str = Field(default="")
    lookup_field: str = Field(default="")
    lookup_label: str = Field(default="")


class CustomPageSpec(BaseModel):
    """A non-CRUD page — dashboards, activity logs, analytics views."""
    id: str = Field(..., description="URL-safe page identifier")
    label: str = Field(..., description="Navigation tab label")
    description: str = Field(..., description="What this page does")
    data_collections: List[str] = Field(default_factory=list)
    sections: List[PageSection] = Field(default_factory=list)
    is_default: bool = Field(default=False)


class AppSpec(BaseModel):
    """The complete structured schema for a generated application.

    This is the 'missing standard' — a single document that captures
    everything an application needs from MongoDB: data shape, access patterns,
    security, search, time-series, relationships, and seed data.
    """
    app_name: str = Field(..., description="Human-readable app name")
    slug: str = Field(..., description="URL-safe kebab-case slug")
    description: str = Field(default="")
    auth_enabled: bool = Field(default=True)
    vector_search_enabled: bool = Field(default=False)
    app_mode: str = Field(default="crud", description="crud | dashboard")
    entities: List[EntitySpec]
    endpoints: List[Endpoint] = Field(default_factory=list)
    sample_data: Dict[str, List[Dict]] = Field(default_factory=dict)
    embedded_entities: Dict[str, List[EntitySpec]] = Field(default_factory=dict)
    dashboard_widgets: Dict[str, List[Dict[str, str]]] = Field(default_factory=dict)
    custom_pages: List[CustomPageSpec] = Field(default_factory=list)
    id_map: Dict[str, List[str]] = Field(default_factory=dict)


AppSpec.model_rebuild()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. LLM GENERATION — Natural Language → AppSpec
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
You are a senior MongoDB solutions architect (2026 best practices).

Given a natural language app description, produce a COMPLETE AppSpec JSON
document that captures everything the application needs from MongoDB.

Your job is to think deeply about:

1. ENTITY DECOMPOSITION
   - Identify all entities (1-5) from the description
   - Use PascalCase names, snake_case collection names (plural)
   - Include a 'created_at' (datetime) field on every entity. Do NOT include an 'id' field.
   - For each field, assign the correct type: string, text, email, enum,
     integer, float, boolean, datetime, reference

2. ACCESS PATTERNS (this is the key innovation — annotate every field)
   - is_filterable: users will filter/query by this field → drives index creation
   - is_sortable: users will sort by this field → drives compound index sort keys
   - is_searchable: users will full-text search this → drives Atlas Search index
   - is_sensitive: PII data (email, phone, SSN, salary) → drives CSFLE encryption
   - is_vectorizable: set to FALSE for all fields (disabled in this demo)

3. MONGODB-NATIVE FEATURES
   - real_time: set true for entities with collaborative/live views → Change Streams
   - is_time_series: set true for event logs, metrics, temporal data → Time Series collections
     If time_series, set time_field and meta_field appropriately
   - Use type='reference' with reference_collection for foreign keys → $lookup
   - Use type='enum' with enum_values for status/category fields → $jsonSchema validation

4. ENDPOINTS
   - Generate standard CRUD endpoints for each entity (GET list, GET by id, POST, PUT, DELETE)
   - On GET list endpoints, populate 'filters' with filterable field names and
     'sort_fields' with sortable field names — these drive compound index derivation
   - Set needs_join=true on GET endpoints that should resolve references via $lookup
   - Use the collection name in paths (e.g. /properties, /properties/{id})

Be thorough and opinionated. Mark MORE fields as searchable/filterable rather than fewer.
Always flag PII fields as sensitive. Always detect time-series patterns.
"""

USER_PROMPT_TEMPLATE = """\
Design a complete AppSpec for this application:

{description}

Return a valid AppSpec JSON with:
- app_name, slug, description
- auth_enabled (true for apps with user-facing features)
- entities (1-5, with fully annotated fields)
- endpoints (CRUD for each entity, with filters and sort_fields on GET list)
- Do NOT include sample_data or id_map (those are generated separately)
"""


class _SampleDocuments(BaseModel):
    """LLM response model for seed data generation."""
    documents: List[Dict] = Field(..., description="List of sample documents")


SAMPLE_DATA_SYSTEM = """\
You are a QA engineer creating realistic seed data for a MongoDB demo app.
Generate exactly {num_docs} documents for the {model_name} collection.

Rules:
- Include ALL fields listed below
- For enum fields, only use values from the allowed list
- For reference fields, use ONLY the provided reference IDs
- For datetime fields, use ISO-8601 strings with varied recent dates
- Use REAL, specific names (not "Item 1", "Sample 2")
- For descriptions/notes, write 1-2 sentences of genuine context
- Make the data tell a coherent story
- Do NOT include a created_at field (added automatically)
- Do NOT include an _id field
"""


async def generate_spec_from_llm(description: str, model: str) -> AppSpec:
    """Use an LLM to generate an AppSpec from a natural language description."""
    if not HAS_LITELLM:
        raise RuntimeError("litellm is required for LLM generation. Install with: pip install litellm")

    litellm.enable_json_schema_validation = True

    resp = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(description=description)},
        ],
        temperature=0.1,
        response_format=AppSpec,
    )
    raw = resp.choices[0].message.content
    spec = AppSpec.model_validate_json(raw)

    n_docs = 5
    id_map: Dict[str, List[str]] = {}
    for entity in spec.entities:
        id_map[entity.collection] = [
            hashlib.sha256(f"{entity.name}:{i}".encode()).hexdigest()[:24]
            for i in range(n_docs)
        ]
    spec.id_map = id_map

    sample_data: Dict[str, List[Dict]] = {}
    for entity in spec.entities:
        ref_info_lines = []
        for e2 in spec.entities:
            if e2.collection in id_map:
                ref_info_lines.append(f"  {e2.collection}: {id_map[e2.collection]}")

        fields_desc = "\n".join(
            f"  - {f.name} ({f.type}){' enum=' + str(f.enum_values) if f.enum_values else ''}"
            f"{' ref=' + f.reference_collection if f.reference_collection else ''}"
            for f in entity.fields
        )

        try:
            data_resp = await litellm.acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": SAMPLE_DATA_SYSTEM.format(
                        num_docs=n_docs, model_name=entity.name)},
                    {"role": "user", "content": (
                        f"Collection: {entity.collection}\n"
                        f"Description: {entity.description}\n\n"
                        f"Fields:\n{fields_desc}\n\n"
                        f"Reference IDs available:\n" + "\n".join(ref_info_lines)
                    )},
                ],
                temperature=0.3,
                response_format=_SampleDocuments,
            )
            docs_raw = _SampleDocuments.model_validate_json(data_resp.choices[0].message.content)
            sample_data[entity.collection] = docs_raw.documents[:n_docs]
        except Exception as e:
            print(f"  {YELLOW}Warning: seed data generation failed for {entity.collection}: {e}{RESET}")
            sample_data[entity.collection] = []

    spec.sample_data = sample_data
    return spec


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DERIVATION FUNCTIONS — AppSpec → MongoDB Infrastructure
# ═══════════════════════════════════════════════════════════════════════════════


def derive_indexes(spec: AppSpec) -> dict[str, list[dict]]:
    """Derive MongoDB index definitions from access patterns (ESR-aware)."""
    indexes: dict[str, list[dict]] = {}
    for entity in spec.entities:
        collection = entity.collection
        idx_list: list[dict] = []

        ref_fields = [f for f in entity.fields if f.type == "reference"]
        for f in ref_fields:
            idx_list.append({
                "keys": {f.name: 1},
                "name": f"idx_{collection}_{f.name}",
                "reason": f"Foreign key lookup to {f.reference_collection}",
            })

        filterable = {f.name for f in entity.fields if f.is_filterable}
        sortable = {f.name for f in entity.fields if f.is_sortable}

        for ep in spec.endpoints:
            if ep.model_name != entity.name:
                continue
            if ep.filters and ep.sort_fields:
                compound_keys = {f: 1 for f in ep.filters if f in filterable}
                for s in ep.sort_fields:
                    if s in sortable:
                        compound_keys[s] = -1
                if len(compound_keys) > 1:
                    name_parts = "_".join(compound_keys.keys())
                    idx_list.append({
                        "keys": compound_keys,
                        "name": f"idx_{collection}_{name_parts}",
                        "reason": f"Compound index for {ep.method} {ep.path}",
                    })

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


def derive_lookups(spec: AppSpec) -> dict[str, list[dict]]:
    """Derive $lookup aggregation stages from reference fields."""
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


def derive_search_indexes(spec: AppSpec) -> dict[str, dict]:
    """Derive Atlas Search index definitions from is_searchable fields."""
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


def derive_vector_search_config(spec: AppSpec) -> dict[str, dict]:
    """Derive Atlas Vector Search index definitions from is_vectorizable fields."""
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


def derive_sensitive_fields(spec: AppSpec) -> dict[str, list[dict]]:
    """Derive CSFLE encryption schema from is_sensitive fields.

    Automatically selects Deterministic (queryable) vs Random (stronger)
    encryption based on whether the field is also filterable.
    """
    schema_map: dict[str, list[dict]] = {}
    for entity in spec.entities:
        sensitive = [f for f in entity.fields if f.is_sensitive]
        if not sensitive:
            continue
        fields = []
        for f in sensitive:
            algo = (
                "AEAD_AES_256_CBC_HMAC_SHA_512-Deterministic"
                if f.is_filterable
                else "AEAD_AES_256_CBC_HMAC_SHA_512-Random"
            )
            fields.append({"path": f.name, "bsonType": "string", "algorithm": algo})
        schema_map[entity.collection] = fields
    return schema_map


def derive_change_stream_collections(spec: AppSpec) -> list[str]:
    """Return collection names that benefit from Change Streams."""
    return [e.collection for e in spec.entities if e.real_time]


def derive_time_series_entities(spec: AppSpec) -> list[dict]:
    """Return time-series collection configuration."""
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


def derive_validation(spec: AppSpec) -> dict[str, dict]:
    """Produce MongoDB $jsonSchema validation for each collection."""
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
                prop["pattern"] = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
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
    return validations


def derive_all(spec: AppSpec) -> dict[str, object]:
    """Run every derivation and return the complete MongoDB infrastructure map."""
    return {
        "indexes": derive_indexes(spec),
        "lookups": derive_lookups(spec),
        "search_indexes": derive_search_indexes(spec),
        "vector_search_indexes": derive_vector_search_config(spec),
        "encryption_config": derive_sensitive_fields(spec),
        "change_stream_collections": derive_change_stream_collections(spec),
        "time_series": derive_time_series_entities(spec),
        "validation": derive_validation(spec),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MONGODB SHELL COMMANDS — Runnable mongosh output
# ═══════════════════════════════════════════════════════════════════════════════


def generate_mongosh_script(spec: AppSpec, artifacts: dict) -> str:
    """Produce a complete, runnable mongosh script that provisions the database."""
    lines: list[str] = []
    db_name = spec.slug.replace("-", "_")
    script_filename = f"{db_name}_setup.js"

    has_search = bool(artifacts["search_indexes"])
    has_vector = bool(artifacts["vector_search_indexes"])
    needs_atlas = has_search or has_vector

    lines.append("// ═══════════════════════════════════════════════════════════")
    lines.append(f"// MongoDB Setup Script for: {spec.app_name}")
    lines.append(f"// Generated from AppSpec — The Missing Schema")
    lines.append("// ═══════════════════════════════════════════════════════════")
    lines.append("//")
    lines.append("// HOW TO USE THIS SCRIPT")
    lines.append("// ─────────────────────")
    lines.append("//")
    lines.append(f"// Save this file as: {script_filename}")
    lines.append("//")
    lines.append("// ── Option 1: Docker (quickest, no signup) ──────────────")
    lines.append("//")
    lines.append("//   # Start MongoDB in Docker:")
    lines.append('//   docker run -d --name mongodb -p 27017:27017 mongodb/mongodb-community-server:latest')
    lines.append("//")
    lines.append(f"//   # Run the setup script:")
    lines.append(f"//   mongosh mongodb://localhost:27017 {script_filename}")
    lines.append("//")
    if needs_atlas:
        lines.append("// ── Option 2: Atlas CLI / Local Dev (recommended) ──────")
        lines.append("//")
        lines.append("//   Atlas local dev gives you Atlas Search + Vector Search")
        lines.append("//   on your laptop — no cloud deployment needed.")
        lines.append("//")
        lines.append("//   # Install Atlas CLI (macOS):")
        lines.append("//   brew install mongodb-atlas-cli")
        lines.append("//")
        lines.append("//   # Start a local Atlas deployment with search support:")
        lines.append("//   atlas deployments setup local --type local --port 27017")
        lines.append("//   atlas deployments start local")
        lines.append("//")
        lines.append(f"//   # Run the setup script:")
        lines.append(f"//   mongosh mongodb://localhost:27017 {script_filename}")
        lines.append("//")
        lines.append("// ── Option 3: MongoDB Atlas (cloud, full features) ─────")
        lines.append("//")
        lines.append("//   # Create a free M0 cluster at https://cloud.mongodb.com")
        lines.append("//   # Copy your connection string, then:")
        lines.append(f'//   mongosh "mongodb+srv://user:pass@cluster.mongodb.net" {script_filename}')
    else:
        lines.append("// ── Option 2: MongoDB Atlas (cloud, free tier) ─────────")
        lines.append("//")
        lines.append("//   # Create a free M0 cluster at https://cloud.mongodb.com")
        lines.append("//   # Copy your connection string, then:")
        lines.append(f'//   mongosh "mongodb+srv://user:pass@cluster.mongodb.net" {script_filename}')
        lines.append("//")
        lines.append("// ── Option 3: Atlas CLI / Local Dev ────────────────────")
        lines.append("//")
        lines.append("//   # Install Atlas CLI (macOS):")
        lines.append("//   brew install mongodb-atlas-cli")
        lines.append("//")
        lines.append("//   # Start a local Atlas deployment:")
        lines.append("//   atlas deployments setup local --type local --port 27017")
        lines.append("//   atlas deployments start local")
        lines.append("//")
        lines.append(f"//   # Run the setup script:")
        lines.append(f"//   mongosh mongodb://localhost:27017 {script_filename}")
    lines.append("//")
    lines.append("// ── Don't have mongosh? ────────────────────────────────")
    lines.append("//")
    lines.append("//   brew install mongosh          # macOS")
    lines.append("//   npm install -g mongosh         # any OS with Node.js")
    lines.append("//   https://www.mongodb.com/try/download/shell  # direct download")
    lines.append("//")
    if needs_atlas:
        lines.append("// ── Notes ──────────────────────────────────────────────")
        lines.append("//")
        if has_search:
            lines.append("//   * Atlas Search indexes require Atlas (cloud or local dev).")
            lines.append("//     Plain Docker MongoDB does not support createSearchIndex().")
            lines.append("//     On plain Docker, search index commands will be skipped.")
        if has_vector:
            lines.append("//   * Vector Search indexes require Atlas (cloud or local dev).")
        lines.append("//")
    lines.append("// ═══════════════════════════════════════════════════════════")
    lines.append("")
    lines.append(f'const DB_NAME = "{db_name}";')
    lines.append(f"const db = db.getSiblingDB(DB_NAME);")
    lines.append(f'print("\\n  Setting up database: " + DB_NAME + "\\n");')
    lines.append("")

    # Time-series collections first (must use createCollection)
    ts_collections = {ts["collection"] for ts in artifacts["time_series"]}
    if ts_collections:
        lines.append("// ─── Time-Series Collections ─────────────────────────────")
        for ts in artifacts["time_series"]:
            opts = {
                "timeseries": {
                    "timeField": ts["time_field"],
                    "granularity": ts["granularity"],
                }
            }
            if ts["meta_field"]:
                opts["timeseries"]["metaField"] = ts["meta_field"]
            lines.append(f'db.createCollection("{ts["collection"]}", {json.dumps(opts, indent=2)});')
            lines.append(f'print("  ✓ Created time-series collection: {ts["collection"]}");')
        lines.append("")

    # $jsonSchema validation
    lines.append("// ─── Collection Validation ($jsonSchema) ──────────────────")
    for coll, schema in artifacts["validation"].items():
        if coll in ts_collections:
            lines.append(f"// Skipping validation for time-series collection: {coll}")
            continue
        lines.append(f"db.createCollection(\"{coll}\", {{")
        lines.append(f"  validator: {json.dumps(schema, indent=4).replace(chr(10), chr(10) + '  ')}")
        lines.append(f"}});")
        lines.append(f'print("  ✓ Created collection with validation: {coll}");')
    lines.append("")

    # Indexes
    if artifacts["indexes"]:
        lines.append("// ─── Indexes (ESR-optimized) ─────────────────────────────")
        for coll, idxs in artifacts["indexes"].items():
            for idx in idxs:
                keys_js = json.dumps(idx["keys"])
                lines.append(f'db.{coll}.createIndex({keys_js}, {{ name: "{idx["name"]}" }});')
                lines.append(f'print("  ✓ Index: {idx["name"]}  // {idx["reason"]}");')
        lines.append("")

    # Atlas Search indexes
    if artifacts["search_indexes"]:
        lines.append("// ─── Atlas Search Indexes ────────────────────────────────")
        lines.append("// NOTE: These require Atlas. Run via Atlas UI, CLI, or Admin API.")
        for coll, idx in artifacts["search_indexes"].items():
            idx_json = json.dumps(idx, indent=2)
            lines.append(f"db.{coll}.createSearchIndex({idx_json});")
            field_names = list(idx["mappings"]["fields"].keys())
            lines.append(f'print("  ✓ Search index: {idx["name"]} on [{", ".join(field_names)}]");')
        lines.append("")

    # Vector Search indexes
    if artifacts["vector_search_indexes"]:
        lines.append("// ─── Atlas Vector Search Indexes ─────────────────────────")
        lines.append("// NOTE: These require Atlas. Run via Atlas UI, CLI, or Admin API.")
        for coll, idx in artifacts["vector_search_indexes"].items():
            idx_json = json.dumps(idx, indent=2)
            lines.append(f"db.{coll}.createSearchIndex({idx_json});")
            vector_fields = [f["path"] for f in idx["fields"] if f["type"] == "vector"]
            lines.append(f'print("  ✓ Vector index: {idx["name"]} on [{", ".join(vector_fields)}]");')
        lines.append("")

    # CSFLE
    if artifacts["encryption_config"]:
        lines.append("// ─── Client-Side Field Level Encryption ──────────────────")
        lines.append("// NOTE: CSFLE is configured in the application driver, not mongosh.")
        lines.append("// Below is the encryption schema map for reference:")
        lines.append(f"const encryptionSchemaMap = {json.dumps(artifacts['encryption_config'], indent=2)};")
        lines.append('print("  ✓ CSFLE schema map defined for driver configuration");')
        lines.append("")

    # Change Streams
    if artifacts["change_stream_collections"]:
        lines.append("// ─── Change Streams ──────────────────────────────────────")
        lines.append("// NOTE: Change Streams are consumed in application code.")
        lines.append("// Example watch commands for reference:")
        for coll in artifacts["change_stream_collections"]:
            lines.append(f"// db.{coll}.watch([{{ $match: {{ operationType: {{ $in: ['insert', 'update'] }} }} }}]);")
        lines.append("")

    # Seed data
    if spec.sample_data:
        lines.append("// ─── Seed Data ───────────────────────────────────────────")
        for coll, docs in spec.sample_data.items():
            if not docs:
                continue
            enriched = []
            id_list = spec.id_map.get(coll, [])
            for i, doc in enumerate(docs):
                d = {}
                if i < len(id_list):
                    d["_id"] = f"ObjectId('{id_list[i]}')"
                d["created_at"] = "new Date()"
                for k, v in doc.items():
                    if k in ("_id", "created_at"):
                        continue
                    ref_fields = {f.name for e in spec.entities
                                  if e.collection == coll for f in e.fields
                                  if f.type == "reference"}
                    if k in ref_fields and isinstance(v, str) and len(v) == 24:
                        d[k] = f"ObjectId('{v}')"
                    else:
                        d[k] = v
                enriched.append(d)

            docs_str = json.dumps(enriched, indent=2, default=str)
            docs_str = _unwrap_oid_and_date(docs_str)
            lines.append(f"db.{coll}.insertMany({docs_str});")
            lines.append(f'print("  ✓ Seeded {len(docs)} documents into {coll}");')
        lines.append("")

    # ── Try These Queries ──────────────────────────────────────
    lines.append("// ═══════════════════════════════════════════════════════════")
    lines.append("// TRY THESE QUERIES (paste into mongosh after running setup)")
    lines.append("// ═══════════════════════════════════════════════════════════")
    lines.append("")

    for entity in spec.entities:
        coll = entity.collection
        lines.append(f"// ─── {entity.name} queries ──────────────────────────────")
        lines.append("")

        # Basic find
        lines.append(f"// List all {coll}:")
        lines.append(f"db.{coll}.find().limit(5).pretty();")
        lines.append("")

        # Count
        lines.append(f"// Count {coll}:")
        lines.append(f"db.{coll}.countDocuments();")
        lines.append("")

        # Filter by enum field
        enum_fields = [f for f in entity.fields if f.type == "enum" and f.enum_values]
        if enum_fields:
            ef = enum_fields[0]
            val = ef.enum_values[0]
            lines.append(f"// Filter by {ef.name}:")
            lines.append(f'db.{coll}.find({{ {ef.name}: "{val}" }}).pretty();')
            lines.append("")

        # Filter + sort (uses compound index)
        filterable = [f for f in entity.fields if f.is_filterable and f.type == "enum" and f.enum_values]
        sortable = [f for f in entity.fields if f.is_sortable]
        if filterable and sortable:
            ff = filterable[0]
            sf = sortable[0]
            fval = ff.enum_values[0]
            sort_dir = -1 if sf.type in ("datetime", "float", "integer") else 1
            lines.append(f"// Filter + sort (uses compound index — ESR pattern):")
            lines.append(f'db.{coll}.find({{ {ff.name}: "{fval}" }}).sort({{ {sf.name}: {sort_dir} }}).limit(10);')
            lines.append("")

        # Reference lookup / aggregation
        ref_fields = [f for f in entity.fields if f.type == "reference" and f.reference_collection]
        if ref_fields:
            rf = ref_fields[0]
            as_name = rf.reference_collection.rstrip("s")
            lines.append(f"// Join {coll} with {rf.reference_collection} ($lookup):")
            pipeline = [
                {"$lookup": {"from": rf.reference_collection,
                              "localField": rf.name,
                              "foreignField": "_id",
                              "as": as_name}},
                {"$unwind": f"${as_name}"},
                {"$limit": 5},
            ]
            lines.append(f"db.{coll}.aggregate({json.dumps(pipeline, indent=2)});")
            lines.append("")

        # Text search (Atlas Search)
        searchable = [f for f in entity.fields if f.is_searchable]
        if searchable:
            sf = searchable[0]
            example_term = {"address": "evergreen", "name": "sarah", "description": "modern",
                            "title": "project"}.get(sf.name, "example")
            lines.append(f"// Full-text search on {sf.name} (requires Atlas Search index):")
            lines.append(f"db.{coll}.aggregate([")
            lines.append(f'  {{ $search: {{ index: "{coll}_search", text: {{ query: "{example_term}", path: "{sf.name}" }} }} }},')
            lines.append(f"  {{ $limit: 5 }},")
            lines.append(f'  {{ $project: {{ {sf.name}: 1, score: {{ $meta: "searchScore" }} }} }}')
            lines.append(f"]);")
            lines.append("")

        # Distinct values for enum
        if enum_fields:
            ef = enum_fields[0]
            lines.append(f"// Distinct {ef.name} values:")
            lines.append(f'db.{coll}.distinct("{ef.name}");')
            lines.append("")

        # Group by / aggregation
        if enum_fields:
            ef = enum_fields[0]
            lines.append(f"// Count by {ef.name}:")
            lines.append(f"db.{coll}.aggregate([")
            lines.append(f'  {{ $group: {{ _id: "${ef.name}", count: {{ $sum: 1 }} }} }},')
            lines.append(f"  {{ $sort: {{ count: -1 }} }}")
            lines.append(f"]);")
            lines.append("")

        # Explain a query (show index usage)
        if filterable:
            ff = filterable[0]
            fval = ff.enum_values[0] if ff.enum_values else "value"
            lines.append(f"// Verify index usage with explain():")
            lines.append(f'db.{coll}.find({{ {ff.name}: "{fval}" }}).explain("executionStats").queryPlanner.winningPlan;')
            lines.append("")

    # ── curl commands for REST API ────────────────────────────
    if spec.endpoints:
        lines.append("// ═══════════════════════════════════════════════════════════")
        lines.append("// CURL COMMANDS (if you build the REST API from this spec)")
        lines.append("// ═══════════════════════════════════════════════════════════")
        lines.append("//")
        lines.append("// Start your server on port 3000, then try these:")
        lines.append("//")

        for ep in spec.endpoints:
            path = ep.path.replace("{id}", spec.id_map.get(
                next((e.collection for e in spec.entities if e.name == ep.model_name), ""), ["abc123"]
            )[0] if spec.id_map else "abc123")
            url = f"http://localhost:3000/api{path}"

            if ep.method == "GET":
                if ep.filters:
                    entity = next((e for e in spec.entities if e.name == ep.model_name), None)
                    filter_params = []
                    for fname in ep.filters[:2]:
                        field = next((f for f in (entity.fields if entity else []) if f.name == fname), None)
                        if field and field.enum_values:
                            filter_params.append(f"{fname}={field.enum_values[0]}")
                        elif field:
                            filter_params.append(f"{fname}=value")
                    if ep.sort_fields:
                        filter_params.append(f"sort={ep.sort_fields[0]}")
                    qs = "&".join(filter_params)
                    lines.append(f"//   # {ep.description or f'List {ep.model_name} with filters'}")
                    lines.append(f'//   curl "{url}?{qs}"')
                else:
                    lines.append(f"//   # {ep.description or f'Get {ep.model_name}'}")
                    lines.append(f'//   curl "{url}"')

            elif ep.method == "POST":
                entity = next((e for e in spec.entities if e.name == ep.model_name), None)
                if entity:
                    sample_body = {}
                    for f in entity.fields:
                        if f.name == "created_at":
                            continue
                        if f.type == "string":
                            sample_body[f.name] = f"New {f.label}"
                        elif f.type == "text":
                            sample_body[f.name] = f"Sample {f.label.lower()} text"
                        elif f.type == "email":
                            sample_body[f.name] = "user@example.com"
                        elif f.type == "enum" and f.enum_values:
                            sample_body[f.name] = f.enum_values[0]
                        elif f.type == "integer":
                            sample_body[f.name] = 1
                        elif f.type == "float":
                            sample_body[f.name] = 1.0
                        elif f.type == "boolean":
                            sample_body[f.name] = True
                        elif f.type == "datetime":
                            sample_body[f.name] = "2024-01-01T00:00:00Z"
                        elif f.type == "reference":
                            ref_ids = spec.id_map.get(f.reference_collection, [])
                            sample_body[f.name] = ref_ids[0] if ref_ids else "ObjectId"
                    body_json = json.dumps(sample_body, indent=4)
                    body_oneline = json.dumps(sample_body)
                    lines.append(f"//   # Create a new {ep.model_name}")
                    lines.append(f"//   curl -X POST {url} \\")
                    lines.append(f"//     -H 'Content-Type: application/json' \\")
                    lines.append(f"//     -d '{body_oneline}'")

            elif ep.method == "PUT":
                lines.append(f"//   # Update a {ep.model_name}")
                lines.append(f"//   curl -X PUT {url} \\")
                lines.append(f"//     -H 'Content-Type: application/json' \\")
                lines.append(f"//     -d '{{\"status\": \"updated\"}}'")

            elif ep.method == "DELETE":
                lines.append(f"//   # Delete a {ep.model_name}")
                lines.append(f"//   curl -X DELETE {url}")

            lines.append("//")
        lines.append("")

    # Summary
    total_indexes = sum(len(v) for v in artifacts["indexes"].values())
    total_search = len(artifacts["search_indexes"])
    total_vector = len(artifacts["vector_search_indexes"])
    total_encrypted = sum(len(v) for v in artifacts["encryption_config"].values())
    total_ts = len(artifacts["time_series"])
    total_docs = sum(len(v) for v in spec.sample_data.values())

    lines.append("// ─── Summary ────────────────────────────────────────────")
    lines.append(f'print("\\n  ════════════════════════════════════════════");')
    lines.append(f'print("  Database: " + DB_NAME);')
    lines.append(f'print("  {len(artifacts["validation"])} collections created");')
    lines.append(f'print("  {total_indexes} indexes (including ESR compound indexes)");')
    if total_search:
        lines.append(f'print("  {total_search} Atlas Search indexes");')
    if total_vector:
        lines.append(f'print("  {total_vector} Vector Search indexes");')
    if total_encrypted:
        lines.append(f'print("  {total_encrypted} CSFLE-encrypted fields");')
    if total_ts:
        lines.append(f'print("  {total_ts} time-series collections");')
    if total_docs:
        lines.append(f'print("  {total_docs} seed documents inserted");')
    lines.append(f'print("  ════════════════════════════════════════════\\n");')

    return "\n".join(lines)


def _unwrap_oid_and_date(s: str) -> str:
    """Convert "ObjectId('...')" strings back to actual ObjectId() calls in JS."""
    import re
    s = re.sub(r'"ObjectId\(\'([a-f0-9]{24})\'\)"', r"ObjectId('\1')", s)
    s = re.sub(r'"new Date\(\)"', "new Date()", s)
    return s


# ═══════════════════════════════════════════════════════════════════════════════
# 6. BUILT-IN EXAMPLE — A Real Estate Listings App
# ═══════════════════════════════════════════════════════════════════════════════


def build_example_spec() -> AppSpec:
    """Build a realistic AppSpec for a real estate listings application.

    Demonstrates every MongoDB feature: indexes (ESR), Atlas Search,
    Vector Search, CSFLE, time-series, Change Streams, $lookup, $jsonSchema.
    """
    n_docs = 5

    id_map = {
        "properties": [hashlib.sha256(f"Property:{i}".encode()).hexdigest()[:24] for i in range(n_docs)],
        "agents": [hashlib.sha256(f"Agent:{i}".encode()).hexdigest()[:24] for i in range(n_docs)],
        "showings": [hashlib.sha256(f"Showing:{i}".encode()).hexdigest()[:24] for i in range(n_docs)],
    }

    property_entity = EntitySpec(
        name="Property", collection="properties",
        description="A real estate property listing",
        fields=[
            DataField(name="address", type="string", label="Address",
                      description="Street address", is_searchable=True),
            DataField(name="price", type="float", label="Price",
                      description="Listing price in USD",
                      is_filterable=True, is_sortable=True),
            DataField(name="bedrooms", type="integer", label="Bedrooms",
                      is_filterable=True),
            DataField(name="bathrooms", type="float", label="Bathrooms",
                      is_filterable=True),
            DataField(name="square_footage", type="integer", label="Square Footage",
                      is_sortable=True),
            DataField(name="description", type="text", label="Description",
                      description="Detailed property description",
                      is_searchable=True, is_vectorizable=True),
            DataField(name="status", type="enum", label="Status",
                      is_filterable=True,
                      enum_values=["active", "pending", "sold", "withdrawn"]),
            DataField(name="listing_date", type="datetime", label="Listing Date",
                      is_sortable=True),
            DataField(name="agent_id", type="reference", label="Agent",
                      reference_collection="agents"),
        ],
        relationships=["Agent"], real_time=True,
    )

    agent_entity = EntitySpec(
        name="Agent", collection="agents",
        description="A real estate agent",
        fields=[
            DataField(name="name", type="string", label="Agent Name",
                      is_searchable=True, is_sortable=True),
            DataField(name="email", type="email", label="Email",
                      is_sensitive=True),
            DataField(name="phone", type="string", label="Phone",
                      is_sensitive=True, is_filterable=True),
            DataField(name="license_number", type="string", label="License Number"),
            DataField(name="agency", type="string", label="Agency",
                      is_filterable=True),
            DataField(name="status", type="enum", label="Status",
                      is_filterable=True, enum_values=["active", "inactive"]),
        ],
    )

    showing_entity = EntitySpec(
        name="Showing", collection="showings",
        description="A scheduled property showing — stored as time-series data",
        fields=[
            DataField(name="property_id", type="reference", label="Property",
                      reference_collection="properties"),
            DataField(name="agent_id", type="reference", label="Agent",
                      reference_collection="agents"),
            DataField(name="scheduled_at", type="datetime", label="Scheduled At",
                      is_sortable=True),
            DataField(name="status", type="enum", label="Status",
                      is_filterable=True,
                      enum_values=["scheduled", "completed", "cancelled"]),
            DataField(name="notes", type="text", label="Notes", required=False),
        ],
        relationships=["Property", "Agent"],
        is_time_series=True, time_field="scheduled_at", meta_field="property_id",
    )

    return AppSpec(
        app_name="Real Estate Listings",
        slug="real-estate-listings",
        description="A real estate application enabling agents to manage property listings, schedule showings, and handle inquiries.",
        auth_enabled=True, vector_search_enabled=True,
        entities=[property_entity, agent_entity, showing_entity],
        endpoints=[
            Endpoint(method="GET", path="/properties", model_name="Property",
                     description="List properties with filtering and sorting",
                     filters=["status", "bedrooms", "bathrooms"],
                     sort_fields=["price", "listing_date"]),
            Endpoint(method="GET", path="/properties/{id}", model_name="Property", needs_join=True),
            Endpoint(method="POST", path="/properties", model_name="Property"),
            Endpoint(method="PUT", path="/properties/{id}", model_name="Property"),
            Endpoint(method="DELETE", path="/properties/{id}", model_name="Property"),
            Endpoint(method="GET", path="/properties/search", model_name="Property",
                     description="Full-text search on address and description"),
            Endpoint(method="GET", path="/agents", model_name="Agent",
                     filters=["agency", "status"], sort_fields=["name"]),
            Endpoint(method="GET", path="/agents/{id}", model_name="Agent"),
            Endpoint(method="POST", path="/agents", model_name="Agent"),
            Endpoint(method="GET", path="/showings", model_name="Showing",
                     filters=["status"], sort_fields=["scheduled_at"]),
            Endpoint(method="POST", path="/showings", model_name="Showing"),
        ],
        sample_data={
            "properties": [
                {"address": "742 Evergreen Terrace, Springfield, IL", "price": 350000.0,
                 "bedrooms": 4, "bathrooms": 2.5, "square_footage": 2200,
                 "description": "Charming family home with updated kitchen and spacious backyard.",
                 "status": "active", "listing_date": "2024-03-15T00:00:00Z",
                 "agent_id": id_map["agents"][0]},
                {"address": "221B Baker Street, London, UK", "price": 1250000.0,
                 "bedrooms": 2, "bathrooms": 1.0, "square_footage": 1100,
                 "description": "Historic flat with fireplace. Famous consulting detective previously resided here.",
                 "status": "active", "listing_date": "2024-06-01T00:00:00Z",
                 "agent_id": id_map["agents"][1]},
                {"address": "1600 Pennsylvania Ave NW, Washington, DC", "price": 12500000.0,
                 "bedrooms": 16, "bathrooms": 35.0, "square_footage": 55000,
                 "description": "Historic executive residence with extensive grounds and helipad.",
                 "status": "withdrawn", "listing_date": "2024-01-01T00:00:00Z",
                 "agent_id": id_map["agents"][0]},
            ],
            "agents": [
                {"name": "Sarah Chen", "email": "sarah.chen@realty.example.com",
                 "phone": "555-0101", "license_number": "RE-2024-0042",
                 "agency": "Atlas Realty Group", "status": "active"},
                {"name": "Marcus Johnson", "email": "marcus.j@realty.example.com",
                 "phone": "555-0202", "license_number": "RE-2024-0087",
                 "agency": "MongoDB Properties", "status": "active"},
            ],
            "showings": [
                {"property_id": id_map["properties"][0], "agent_id": id_map["agents"][0],
                 "scheduled_at": "2024-09-10T14:00:00Z", "status": "completed",
                 "notes": "Buyers loved the backyard. Second showing requested."},
                {"property_id": id_map["properties"][1], "agent_id": id_map["agents"][1],
                 "scheduled_at": "2024-09-12T10:30:00Z", "status": "scheduled",
                 "notes": "Virtual tour for international client."},
            ],
        },
        id_map=id_map,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. CLI — Pretty-printed output
# ═══════════════════════════════════════════════════════════════════════════════

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'═' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 60}{RESET}")


def _subsection(title: str) -> None:
    print(f"\n  {BOLD}{GREEN}{title}{RESET}")
    print(f"  {DIM}{'─' * 50}{RESET}")


def pretty_print(spec: AppSpec, artifacts: dict) -> None:
    """Rich terminal output showing what AppSpec produces."""
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  AppSpec Demo: {spec.app_name}{RESET}")
    print(f"  {DIM}{spec.description}{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    _section("Entities")
    for e in spec.entities:
        flags = []
        if e.is_time_series:
            flags.append(f"{YELLOW}time-series{RESET}")
        if e.real_time:
            flags.append(f"{YELLOW}change-streams{RESET}")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"\n  {BOLD}{e.name}{RESET} → {DIM}{e.collection}{RESET}{flag_str}")
        print(f"  {DIM}{e.description}{RESET}")
        for f in e.fields:
            badges = []
            if f.is_filterable:
                badges.append(f"{GREEN}filterable{RESET}")
            if f.is_sortable:
                badges.append(f"{GREEN}sortable{RESET}")
            if f.is_searchable:
                badges.append(f"{CYAN}searchable{RESET}")
            if f.is_vectorizable:
                badges.append(f"{CYAN}vectorizable{RESET}")
            if f.is_sensitive:
                badges.append(f"{RED}sensitive{RESET}")
            badge_str = f"  [{', '.join(badges)}]" if badges else ""
            ref = f" → {f.reference_collection}" if f.reference_collection else ""
            enum = f" {f.enum_values}" if f.enum_values else ""
            print(f"    {f.name}: {DIM}{f.type}{ref}{enum}{RESET}{badge_str}")

    _section("Derived Indexes")
    for coll, idxs in artifacts["indexes"].items():
        _subsection(coll)
        for idx in idxs:
            keys_str = ", ".join(f"{k}: {v}" for k, v in idx["keys"].items())
            print(f"    {BOLD}{idx['name']}{RESET}")
            print(f"      keys: {{ {keys_str} }}")
            print(f"      {DIM}{idx['reason']}{RESET}")

    if artifacts["search_indexes"]:
        _section("Atlas Search Indexes")
        for coll, idx in artifacts["search_indexes"].items():
            _subsection(f"{coll} → {idx['name']}")
            for field_name in idx["mappings"]["fields"]:
                print(f"    {field_name}: lucene.standard + autocomplete (edgeGram 2-15)")

    if artifacts["vector_search_indexes"]:
        _section("Atlas Vector Search Indexes")
        for coll, idx in artifacts["vector_search_indexes"].items():
            _subsection(f"{coll} → {idx['name']}")
            for field_def in idx["fields"]:
                if field_def["type"] == "vector":
                    print(f"    {field_def['path']}: {field_def['numDimensions']}d {field_def['similarity']}")
                else:
                    print(f"    {field_def['path']}: {DIM}pre-filter{RESET}")

    if artifacts["encryption_config"]:
        _section("CSFLE Encryption Config")
        for coll, fields in artifacts["encryption_config"].items():
            _subsection(coll)
            for f in fields:
                algo_short = "Deterministic" if "Deterministic" in f["algorithm"] else "Random"
                color = YELLOW if algo_short == "Deterministic" else GREEN
                print(f"    {f['path']}: {color}{algo_short}{RESET}")

    if artifacts["time_series"]:
        _section("Time-Series Collections")
        for ts in artifacts["time_series"]:
            print(f"  {BOLD}{ts['collection']}{RESET}")
            print(f"    timeField: {ts['time_field']}")
            if ts["meta_field"]:
                print(f"    metaField: {ts['meta_field']}")
            print(f"    granularity: {ts['granularity']}")

    if artifacts["change_stream_collections"]:
        _section("Change Stream Collections")
        for coll in artifacts["change_stream_collections"]:
            print(f"  {BOLD}{coll}{RESET} → SSE endpoint")

    if artifacts["lookups"]:
        _section("$lookup Aggregation Stages")
        for coll, stages in artifacts["lookups"].items():
            _subsection(coll)
            for stage in stages:
                print(f"    $lookup: {stage['localField']} → {stage['from']}.{stage['foreignField']} as {stage['as']}")

    _section("$jsonSchema Validation")
    for coll, schema in artifacts["validation"].items():
        js = schema["$jsonSchema"]
        n_required = len(js.get("required", []))
        n_props = len(js.get("properties", {}))
        has_enum = any("enum" in p for p in js["properties"].values())
        has_pattern = any("pattern" in p for p in js["properties"].values())
        extras = []
        if has_enum:
            extras.append("enum constraints")
        if has_pattern:
            extras.append("regex patterns")
        extra_str = f" ({', '.join(extras)})" if extras else ""
        print(f"  {BOLD}{coll}{RESET}: {n_props} properties, {n_required} required{extra_str}")

    # mongosh query examples
    _section("Try These Queries (mongosh)")
    for entity in spec.entities:
        coll = entity.collection
        enum_fields = [f for f in entity.fields if f.type == "enum" and f.enum_values]
        sortable = [f for f in entity.fields if f.is_sortable]
        ref_fields = [f for f in entity.fields if f.type == "reference"]
        searchable = [f for f in entity.fields if f.is_searchable]

        _subsection(entity.name)

        print(f"    {DIM}# List all{RESET}")
        print(f"    db.{coll}.find().limit(5).pretty()")

        if enum_fields:
            ef = enum_fields[0]
            print(f"\n    {DIM}# Filter by {ef.name}{RESET}")
            print(f'    db.{coll}.find({{ {ef.name}: "{ef.enum_values[0]}" }})')

        if enum_fields and sortable:
            ef, sf = enum_fields[0], sortable[0]
            sd = -1 if sf.type in ("datetime", "float", "integer") else 1
            print(f"\n    {DIM}# Filter + sort (compound index){RESET}")
            print(f'    db.{coll}.find({{ {ef.name}: "{ef.enum_values[0]}" }}).sort({{ {sf.name}: {sd} }})')

        if ref_fields:
            rf = ref_fields[0]
            as_name = rf.reference_collection.rstrip("s")
            print(f"\n    {DIM}# $lookup → join with {rf.reference_collection}{RESET}")
            print(f"    db.{coll}.aggregate([")
            print(f'      {{ $lookup: {{ from: "{rf.reference_collection}", localField: "{rf.name}", foreignField: "_id", as: "{as_name}" }} }},')
            print(f"      {{ $limit: 3 }}")
            print(f"    ])")

        if enum_fields:
            ef = enum_fields[0]
            print(f"\n    {DIM}# Group by {ef.name}{RESET}")
            print(f"    db.{coll}.aggregate([")
            print(f'      {{ $group: {{ _id: "${ef.name}", count: {{ $sum: 1 }} }} }},')
            print(f"      {{ $sort: {{ count: -1 }} }}")
            print(f"    ])")

        if searchable:
            sf = searchable[0]
            term = {"address": "evergreen", "name": "sarah", "description": "modern",
                    "title": "project"}.get(sf.name, "test")
            print(f"\n    {DIM}# Atlas Search on {sf.name}{RESET}")
            print(f"    db.{coll}.aggregate([")
            print(f'      {{ $search: {{ index: "{coll}_search", text: {{ query: "{term}", path: "{sf.name}" }} }} }},')
            print(f"      {{ $limit: 5 }}")
            print(f"    ])")

    # curl examples
    if spec.endpoints:
        _section("Try These curl Commands")
        print(f"  {DIM}Start your server on localhost:3000, then:{RESET}\n")
        for ep in spec.endpoints:
            entity = next((e for e in spec.entities if e.name == ep.model_name), None)
            path = ep.path
            if "{id}" in path:
                coll_name = entity.collection if entity else ""
                ids = spec.id_map.get(coll_name, ["abc123"])
                path = path.replace("{id}", ids[0][:24] if ids else "abc123")
            url = f"http://localhost:3000/api{path}"

            if ep.method == "GET":
                desc = ep.description or f"{ep.model_name}"
                if ep.filters:
                    params = []
                    for fname in ep.filters[:2]:
                        field = next((f for f in (entity.fields if entity else []) if f.name == fname), None)
                        if field and field.enum_values:
                            params.append(f"{fname}={field.enum_values[0]}")
                    if ep.sort_fields:
                        params.append(f"sort={ep.sort_fields[0]}")
                    qs = "&".join(params)
                    print(f"  {GREEN}GET{RESET}  {DIM}{desc}{RESET}")
                    print(f'    curl "{url}?{qs}"')
                else:
                    print(f"  {GREEN}GET{RESET}  {DIM}{desc}{RESET}")
                    print(f'    curl "{url}"')

            elif ep.method == "POST" and entity:
                sample = {}
                for f in entity.fields:
                    if f.name == "created_at":
                        continue
                    if f.type in ("string", "text"):
                        sample[f.name] = f"New {f.label}"
                    elif f.type == "email":
                        sample[f.name] = "user@example.com"
                    elif f.type == "enum" and f.enum_values:
                        sample[f.name] = f.enum_values[0]
                    elif f.type == "integer":
                        sample[f.name] = 1
                    elif f.type == "float":
                        sample[f.name] = 1.0
                    elif f.type == "boolean":
                        sample[f.name] = True
                    elif f.type == "datetime":
                        sample[f.name] = "2024-01-01T00:00:00Z"
                    elif f.type == "reference":
                        ref_ids = spec.id_map.get(f.reference_collection, [])
                        sample[f.name] = ref_ids[0] if ref_ids else "ObjectId"
                body = json.dumps(sample)
                print(f"  {YELLOW}POST{RESET} {DIM}Create {ep.model_name}{RESET}")
                print(f"    curl -X POST {url} -H 'Content-Type: application/json' \\")
                print(f"      -d '{body}'")

            elif ep.method == "PUT":
                print(f"  {CYAN}PUT{RESET}  {DIM}Update {ep.model_name}{RESET}")
                print(f'    curl -X PUT {url} -H \'Content-Type: application/json\' \\')
                print(f"      -d '{{\"status\": \"updated\"}}'")

            elif ep.method == "DELETE":
                print(f"  {RED}DEL{RESET}  {DIM}Delete {ep.model_name}{RESET}")
                print(f"    curl -X DELETE {url}")
            print()

    _section("Summary")
    total_indexes = sum(len(v) for v in artifacts["indexes"].values())
    total_search = len(artifacts["search_indexes"])
    total_vector = len(artifacts["vector_search_indexes"])
    total_encrypted = sum(len(v) for v in artifacts["encryption_config"].values())
    total_ts = len(artifacts["time_series"])
    total_cs = len(artifacts["change_stream_collections"])
    total_lookups = sum(len(v) for v in artifacts["lookups"].values())

    print(f"  {total_indexes} indexes (including ESR compound indexes)")
    print(f"  {total_search} Atlas Search indexes")
    print(f"  {total_vector} Vector Search indexes")
    print(f"  {total_encrypted} CSFLE-encrypted fields")
    print(f"  {total_ts} time-series collections")
    print(f"  {total_cs} Change Stream collections")
    print(f"  {total_lookups} $lookup aggregation stages")
    print(f"  {len(artifacts['validation'])} $jsonSchema validators")
    print(f"\n  {DIM}All derived from a single AppSpec document.{RESET}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# 8. MAIN
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_args() -> dict:
    """Parse CLI arguments into a structured dict."""
    args = sys.argv[1:]
    opts = {
        "json_mode": False,
        "mongo_mode": False,
        "export_path": None,
        "spec_mode": False,
        "prompt": None,
    }
    i = 0
    positional = []
    while i < len(args):
        if args[i] == "--json":
            opts["json_mode"] = True
        elif args[i] == "--mongo":
            opts["mongo_mode"] = True
        elif args[i] == "--spec":
            opts["spec_mode"] = True
        elif args[i] == "--export":
            i += 1
            opts["export_path"] = args[i] if i < len(args) else "appspec.json"
        elif not args[i].startswith("--"):
            positional.append(args[i])
        i += 1
    if positional:
        opts["prompt"] = " ".join(positional)
    return opts


def main():
    opts = _parse_args()
    prompt = opts["prompt"]

    model = os.environ.get("LITELLM_MODEL", "gemini/gemini-2.5-flash")

    if prompt:
        if not HAS_LITELLM:
            print(f"{RED}Error: litellm is required for LLM generation.{RESET}")
            print(f"  pip install litellm")
            print(f"\nOr run without a prompt to use the built-in example:")
            print(f"  python demo.py")
            sys.exit(1)

        print(f"\n{BOLD}AppSpec Demo — LLM Generation{RESET}")
        print(f"{DIM}Model: {model}{RESET}")
        print(f"{DIM}Prompt: {prompt}{RESET}")
        print(f"\n{YELLOW}Generating AppSpec from natural language...{RESET}")
        t0 = time.time()

        try:
            spec = asyncio.run(generate_spec_from_llm(prompt, model))
        except Exception as e:
            print(f"\n{RED}LLM generation failed: {e}{RESET}")
            print(f"\nMake sure your API key is set (e.g. GEMINI_API_KEY)")
            sys.exit(1)

        elapsed = time.time() - t0
        print(f"{GREEN}Done in {elapsed:.1f}s{RESET}")
        print(f"  {len(spec.entities)} entities, {len(spec.endpoints)} endpoints, "
              f"{sum(len(v) for v in spec.sample_data.values())} seed documents")
    else:
        spec = build_example_spec()

    artifacts = derive_all(spec)

    if opts["json_mode"]:
        print(json.dumps(artifacts, indent=2, default=str))
        return

    if opts["export_path"]:
        with open(opts["export_path"], "w") as f:
            json.dump(spec.model_dump(), f, indent=2, default=str)
        print(f"Exported AppSpec to {opts['export_path']}")
        return

    if opts["spec_mode"]:
        print(json.dumps(spec.model_dump(), indent=2, default=str))
        return

    if opts["mongo_mode"]:
        script = generate_mongosh_script(spec, artifacts)
        db_name = spec.slug.replace("-", "_")
        script_filename = f"{db_name}_setup.js"

        with open(script_filename, "w") as f:
            f.write(script)

        total_indexes = sum(len(v) for v in artifacts["indexes"].values())
        total_search = len(artifacts["search_indexes"])
        total_vector = len(artifacts["vector_search_indexes"])
        has_search = total_search > 0 or total_vector > 0

        print(f"\n{BOLD}  Wrote {script_filename}{RESET}")
        print(f"  {DIM}{spec.app_name} — {len(artifacts['validation'])} collections, "
              f"{total_indexes} indexes, "
              f"{sum(len(v) for v in spec.sample_data.values())} seed docs{RESET}")

        print(f"\n{BOLD}{CYAN}  Quick Start{RESET}")
        print(f"  {DIM}{'─' * 50}{RESET}")

        if has_search:
            print(f"\n  {GREEN}Option A: Atlas Local Dev{RESET} {DIM}(recommended — includes Search){RESET}")
            print(f"  {DIM}$ brew install mongodb-atlas-cli{RESET}")
            print(f"  $ atlas deployments setup local --type local --port 27017")
            print(f"  $ atlas deployments start local")
            print(f"  $ mongosh mongodb://localhost:27017 {script_filename}")

            print(f"\n  {GREEN}Option B: Docker{RESET} {DIM}(no Search/Vector support){RESET}")
            print(f"  $ docker run -d --name mongodb -p 27017:27017 mongodb/mongodb-community-server:latest")
            print(f"  $ mongosh mongodb://localhost:27017 {script_filename}")

            print(f"\n  {GREEN}Option C: Atlas Cloud{RESET} {DIM}(full features, free M0 tier){RESET}")
            print(f'  $ mongosh "mongodb+srv://user:pass@cluster.mongodb.net" {script_filename}')
        else:
            print(f"\n  {GREEN}Option A: Docker{RESET} {DIM}(quickest, no signup){RESET}")
            print(f"  $ docker run -d --name mongodb -p 27017:27017 mongodb/mongodb-community-server:latest")
            print(f"  $ mongosh mongodb://localhost:27017 {script_filename}")

            print(f"\n  {GREEN}Option B: Atlas Cloud{RESET} {DIM}(free M0 tier){RESET}")
            print(f'  $ mongosh "mongodb+srv://user:pass@cluster.mongodb.net" {script_filename}')

        print(f"\n  {DIM}Don't have mongosh? → brew install mongosh{RESET}")
        print(f"  {DIM}Full instructions inside {script_filename}{RESET}\n")
        return

    pretty_print(spec, artifacts)

    print(f"  {DIM}Run with --mongo to generate a runnable mongosh setup script.{RESET}")
    if prompt:
        print(f"  {DIM}Run with --export spec.json to save the portable AppSpec.{RESET}")
    print()


if __name__ == "__main__":
    main()
