# Carrier Consultant Dictionary & Skills Taxonomy

Authoritative master data repository for CareerLab domain models, meta-professions, and canonical skills taxonomy.

## Contents
- `meta_professions.md`: Canonical master professions catalog (287 entries).
- `skills_taxonomy.json`: Machine-readable canonical taxonomy of technical and soft skills, complete with categories, codes, and multilingual aliases.
- `skills_mapping_rules.json`: Normalization rules, protected technology tokens (`C++`, `.NET`, `CI/CD`), version stripping regexes, and composite delimiters.
- `adapter/skills_adapter.py`: Production reconciliation engine and Generic MDM Hub adapter.

## Taxonomy Specification

Each canonical skill in `skills_taxonomy.json` adheres to the following schema:
```json
{
  "code": "SKILL_POSTGRESQL",
  "canonical_name": "PostgreSQL",
  "category": "DATABASE",
  "subcategory": "RELATIONAL",
  "description": "Free and open-source relational database management system.",
  "aliases": ["postgres", "postgresql", "psql", "pgsql", "постгрес"],
  "related_skills": ["SKILL_SQL"]
}
```

## Generic MDM Hub Integration

The adapter provides seamless integration with the Generic MDM Hub:
1. **Unmapped Skill Ingestion:** When incoming parser strings cannot be matched, they are queued via `_enqueue_unmapped` with source tracking and frequency counters.
2. **1-Click Entity Resolution:** `resolve_unmapped(unmapped_id, target_canonical_code, create_alias=True)` resolves the unmapped entity and registers the new alias into the taxonomy.
3. **Canonical Dictionary API:** `get_canonical_dictionary(category, search)` allows UI components to search and autocomplete against canonical records.
