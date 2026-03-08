#!/usr/bin/env python3
"""
AppSpec Demo — The Missing Schema
==================================
A standalone demonstration of AppSpec: a structured intermediate representation
that captures what an application needs from MongoDB — not just data shape,
but access patterns, security, search, time-series, and embedding strategy.

One JSON document. Every MongoDB feature configured correctly.

Usage:
    python demo.py                     # Pretty-print all derived artifacts
    python demo.py --json              # Output raw JSON for each artifact
    python demo.py --export spec.json  # Export the AppSpec as a portable document

Requirements:
    pip install pydantic
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Dict, List

from pydantic import BaseModel, Field


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
# 3. DERIVATION FUNCTIONS — AppSpec → MongoDB Infrastructure
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
# 4. EXAMPLE — A Real Estate Listings App
# ═══════════════════════════════════════════════════════════════════════════════


def build_example_spec() -> AppSpec:
    """Build a realistic AppSpec for a real estate listings application.

    This demonstrates every MongoDB feature AppSpec can configure:
    indexes, compound indexes (ESR), Atlas Search, Vector Search,
    CSFLE encryption, time-series collections, Change Streams,
    embedded documents, $lookup aggregations, and $jsonSchema validation.
    """
    n_properties = 10
    n_agents = 5
    n_showings = 8

    id_map = {
        "properties": [
            hashlib.sha256(f"Property:{i}".encode()).hexdigest()[:24]
            for i in range(n_properties)
        ],
        "agents": [
            hashlib.sha256(f"Agent:{i}".encode()).hexdigest()[:24]
            for i in range(n_agents)
        ],
        "showings": [
            hashlib.sha256(f"Showing:{i}".encode()).hexdigest()[:24]
            for i in range(n_showings)
        ],
    }

    property_entity = EntitySpec(
        name="Property",
        collection="properties",
        description="A real estate property listing",
        fields=[
            DataField(name="address", type="string", label="Address",
                      description="Street address of the property",
                      is_searchable=True),
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
        relationships=["Agent"],
        real_time=True,
    )

    agent_entity = EntitySpec(
        name="Agent",
        collection="agents",
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
                      is_filterable=True,
                      enum_values=["active", "inactive"]),
        ],
    )

    showing_entity = EntitySpec(
        name="Showing",
        collection="showings",
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
        is_time_series=True,
        time_field="scheduled_at",
        meta_field="property_id",
    )

    endpoints = [
        Endpoint(method="GET", path="/properties", model_name="Property",
                 description="List properties with filtering and sorting",
                 filters=["status", "bedrooms", "bathrooms"],
                 sort_fields=["price", "listing_date"]),
        Endpoint(method="GET", path="/properties/{id}", model_name="Property",
                 needs_join=True),
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
    ]

    sample_data = {
        "properties": [
            {
                "_id": id_map["properties"][0],
                "address": "742 Evergreen Terrace, Springfield, IL",
                "price": 350000.0,
                "bedrooms": 4,
                "bathrooms": 2.5,
                "square_footage": 2200,
                "description": "Charming family home with updated kitchen and spacious backyard.",
                "status": "active",
                "listing_date": "2024-03-15T00:00:00Z",
                "agent_id": id_map["agents"][0],
            },
            {
                "_id": id_map["properties"][1],
                "address": "1600 Pennsylvania Ave NW, Washington, DC",
                "price": 12500000.0,
                "bedrooms": 16,
                "bathrooms": 35.0,
                "square_footage": 55000,
                "description": "Historic executive residence with extensive grounds and security infrastructure.",
                "status": "withdrawn",
                "listing_date": "2024-01-01T00:00:00Z",
                "agent_id": id_map["agents"][1],
            },
        ],
        "agents": [
            {
                "_id": id_map["agents"][0],
                "name": "Sarah Chen",
                "email": "sarah.chen@realty.example.com",
                "phone": "555-0101",
                "license_number": "RE-2024-0042",
                "agency": "Atlas Realty Group",
                "status": "active",
            },
            {
                "_id": id_map["agents"][1],
                "name": "Marcus Johnson",
                "email": "marcus.j@realty.example.com",
                "phone": "555-0202",
                "license_number": "RE-2024-0087",
                "agency": "MongoDB Properties",
                "status": "active",
            },
        ],
    }

    return AppSpec(
        app_name="Real Estate Listings",
        slug="real-estate-listings",
        description="A real estate application enabling agents to manage property listings, schedule showings, and handle inquiries.",
        auth_enabled=True,
        vector_search_enabled=True,
        entities=[property_entity, agent_entity, showing_entity],
        endpoints=endpoints,
        sample_data=sample_data,
        id_map=id_map,
        custom_pages=[
            CustomPageSpec(
                id="dashboard",
                label="Dashboard",
                description="Overview of listings activity and agent performance",
                data_collections=["properties", "agents", "showings"],
                sections=[
                    PageSection(type="stat_cards", source="properties",
                                title="Listing Overview", value_field="status",
                                aggregate="count"),
                    PageSection(type="ranked_list", source="agents",
                                title="Top Agents", value_field="properties_listed_count",
                                label_field="name", limit=5),
                ],
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CLI — Pretty-printed output
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

    # Entities overview
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

    # Indexes
    _section("Derived Indexes")
    for coll, idxs in artifacts["indexes"].items():
        _subsection(coll)
        for idx in idxs:
            keys_str = ", ".join(f"{k}: {v}" for k, v in idx["keys"].items())
            print(f"    {BOLD}{idx['name']}{RESET}")
            print(f"      keys: {{ {keys_str} }}")
            print(f"      {DIM}{idx['reason']}{RESET}")

    # Search indexes
    if artifacts["search_indexes"]:
        _section("Atlas Search Indexes")
        for coll, idx in artifacts["search_indexes"].items():
            _subsection(f"{coll} → {idx['name']}")
            for field_name, mapping in idx["mappings"]["fields"].items():
                print(f"    {field_name}: {mapping['analyzer']} + autocomplete (edgeGram 2-15)")

    # Vector search
    if artifacts["vector_search_indexes"]:
        _section("Atlas Vector Search Indexes")
        for coll, idx in artifacts["vector_search_indexes"].items():
            _subsection(f"{coll} → {idx['name']}")
            for field_def in idx["fields"]:
                if field_def["type"] == "vector":
                    print(f"    {field_def['path']}: {field_def['numDimensions']}d {field_def['similarity']}")
                else:
                    print(f"    {field_def['path']}: {DIM}pre-filter{RESET}")

    # Encryption
    if artifacts["encryption_config"]:
        _section("CSFLE Encryption Config")
        for coll, fields in artifacts["encryption_config"].items():
            _subsection(coll)
            for f in fields:
                algo_short = "Deterministic" if "Deterministic" in f["algorithm"] else "Random"
                color = YELLOW if algo_short == "Deterministic" else GREEN
                print(f"    {f['path']}: {color}{algo_short}{RESET}")

    # Time-series
    if artifacts["time_series"]:
        _section("Time-Series Collections")
        for ts in artifacts["time_series"]:
            print(f"  {BOLD}{ts['collection']}{RESET}")
            print(f"    timeField: {ts['time_field']}")
            if ts["meta_field"]:
                print(f"    metaField: {ts['meta_field']}")
            print(f"    granularity: {ts['granularity']}")

    # Change Streams
    if artifacts["change_stream_collections"]:
        _section("Change Stream Collections")
        for coll in artifacts["change_stream_collections"]:
            print(f"  {BOLD}{coll}{RESET} → SSE endpoint")

    # $lookup
    if artifacts["lookups"]:
        _section("$lookup Aggregation Stages")
        for coll, stages in artifacts["lookups"].items():
            _subsection(coll)
            for stage in stages:
                print(f"    $lookup: {stage['localField']} → {stage['from']}.{stage['foreignField']} as {stage['as']}")

    # Validation
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

    # Summary
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


def main():
    spec = build_example_spec()
    artifacts = derive_all(spec)

    if "--json" in sys.argv:
        print(json.dumps(artifacts, indent=2, default=str))
        return

    if "--export" in sys.argv:
        idx = sys.argv.index("--export")
        if idx + 1 < len(sys.argv):
            path = sys.argv[idx + 1]
        else:
            path = "appspec.json"
        with open(path, "w") as f:
            json.dump(spec.model_dump(), f, indent=2, default=str)
        print(f"Exported AppSpec to {path}")
        return

    if "--spec" in sys.argv:
        print(json.dumps(spec.model_dump(), indent=2, default=str))
        return

    pretty_print(spec, artifacts)


if __name__ == "__main__":
    main()
