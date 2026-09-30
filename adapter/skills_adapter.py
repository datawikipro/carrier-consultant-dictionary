"""Skills Taxonomy Reconciliation Adapter for CareerLab and Generic MDM Hub.

Provides deterministic entity resolution, composite token decomposition,
protected syntax preservation, fuzzy matching, and unmapped queue dispatch.
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple


class SkillsReconciliationAdapter:
    """Core adapter for reconciling raw parsed skills against canonical taxonomy."""

    def __init__(
        self,
        taxonomy_path: Optional[str] = None,
        rules_path: Optional[str] = None
    ):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if taxonomy_path is None:
            taxonomy_path = os.path.join(base_dir, "skills_taxonomy.json")
        if rules_path is None:
            rules_path = os.path.join(base_dir, "skills_mapping_rules.json")

        self.taxonomy_path = taxonomy_path
        self.rules_path = rules_path

        self.canonical_skills: Dict[str, Dict[str, Any]] = {}
        self.alias_to_code: Dict[str, str] = {}
        self.canonical_name_to_code: Dict[str, str] = {}
        self.unmapped_queue: Dict[str, Dict[str, Any]] = {}

        self.load_rules()
        self.load_taxonomy()

    def load_rules(self) -> None:
        if os.path.exists(self.rules_path):
            with open(self.rules_path, "r", encoding="utf-8") as f:
                rules = json.load(f)
        else:
            rules = {}

        self.protected_tokens: List[str] = [
            t.lower() for t in rules.get("protected_tokens", [
                "c++", "c#", ".net", ".net core", "asp.net", "node.js",
                "vue.js", "next.js", "nuxt.js", "ci/cd", "pl/sql", "tcp/ip"
            ])
        ]
        self.delimiters: List[str] = rules.get(
            "delimiters", [" / ", "/", ", ", ",", "; ", ";", " | ", "|", "\n"]
        )
        self.version_patterns: List[re.Pattern] = [
            re.compile(p, re.IGNORECASE) for p in rules.get("version_patterns", [
                r"\s+v?\d+(\.\d+)*(\+)?$",
                r"\s+(se|ee|core)?\s*\d+(\+)?$"
            ])
        ]
        self.stopwords: Set[str] = set(
            s.lower() for s in rules.get("stopwords", ["опыт", "знание", "навыки", "experience"])
        )
        self.fuzzy_threshold: float = float(rules.get("fuzzy_similarity_threshold", 0.88))

    def load_taxonomy(self) -> None:
        if not os.path.exists(self.taxonomy_path):
            raise FileNotFoundError(f"Taxonomy file not found at {self.taxonomy_path}")

        with open(self.taxonomy_path, "r", encoding="utf-8") as f:
            items = json.load(f)

        self.canonical_skills.clear()
        self.alias_to_code.clear()
        self.canonical_name_to_code.clear()

        for item in items:
            code = item["code"]
            self.canonical_skills[code] = item
            canonical_name_lower = item["canonical_name"].strip().lower()
            self.canonical_name_to_code[canonical_name_lower] = code

            # Index code itself
            self.alias_to_code[code.lower()] = code
            self.alias_to_code[canonical_name_lower] = code

            for alias in item.get("aliases", []):
                norm_alias = alias.strip().lower()
                self.alias_to_code[norm_alias] = code

    def normalize_text(self, text: str) -> str:
        """Strip redundant whitespace, stopwords, and trailing version specifiers."""
        if not text:
            return ""
        cleaned = text.strip()
        cleaned_lower = cleaned.lower()

        # Check if already a protected token
        if cleaned_lower in self.protected_tokens:
            return cleaned

        # Strip version suffix
        for pat in self.version_patterns:
            cleaned = pat.sub("", cleaned).strip()

        # Strip standard stopwords if not single word
        words = cleaned.split()
        if len(words) > 1:
            filtered = [w for w in words if w.lower() not in self.stopwords]
            if filtered:
                cleaned = " ".join(filtered)

        return cleaned

    def split_composite_skills(self, raw_input: str) -> List[str]:
        """Decompose composite strings preserving protected technology tokens."""
        if not raw_input:
            return []

        text = raw_input.strip()
        text_lower = text.lower()

        # If entire input is protected, return as-is
        if text_lower in self.protected_tokens:
            return [text]

        # Protect special tokens using placeholders
        replacements: Dict[str, str] = {}
        protected_sorted = sorted(self.protected_tokens, key=len, reverse=True)

        masked_text = text
        for idx, token in enumerate(protected_sorted):
            # Regex match token boundaries or standalone presence
            pattern = re.compile(re.escape(token), re.IGNORECASE)
            matches = list(pattern.finditer(masked_text))
            if matches:
                placeholder = f"__PROT_TOKEN_{idx}__"
                replacements[placeholder] = token
                masked_text = pattern.sub(placeholder, masked_text)

        # Build combined delimiter regex
        delimiter_regex = "|".join(re.escape(d.strip()) for d in self.delimiters if d.strip())
        tokens = re.split(delimiter_regex, masked_text)

        results: List[str] = []
        for t in tokens:
            t = t.strip()
            if not t:
                continue
            # Restore protected placeholders
            for placeholder, original in replacements.items():
                if placeholder in t:
                    t = t.replace(placeholder, original)
            cleaned = self.normalize_text(t)
            if cleaned:
                results.append(cleaned)

        return results if results else [text]

    def _fuzzy_match(self, text_lower: str) -> Optional[Tuple[str, float]]:
        best_match_code = None
        best_ratio = 0.0

        for alias, code in self.alias_to_code.items():
            ratio = SequenceMatcher(None, text_lower, alias).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_code = code

        if best_ratio >= self.fuzzy_threshold and best_match_code:
            return best_match_code, round(best_ratio, 3)

        return None

    def reconcile_skill(
        self,
        raw_skill: str,
        source: str = "HH_RU",
        sample_context: str = ""
    ) -> Dict[str, Any]:
        """Reconcile a single skill against canonical taxonomy or enqueue to MDM Hub."""
        normalized = self.normalize_text(raw_skill)
        key = normalized.lower()

        # 1. Exact match on canonical code or name
        if key in self.canonical_name_to_code:
            code = self.canonical_name_to_code[key]
            return {
                "status": "RESOLVED",
                "match_type": "EXACT",
                "confidence": 1.0,
                "raw_skill": raw_skill,
                "normalized": normalized,
                "canonical_code": code,
                "canonical_name": self.canonical_skills[code]["canonical_name"],
                "category": self.canonical_skills[code]["category"]
            }

        # 2. Match on registered alias
        if key in self.alias_to_code:
            code = self.alias_to_code[key]
            return {
                "status": "RESOLVED",
                "match_type": "ALIAS",
                "confidence": 0.98,
                "raw_skill": raw_skill,
                "normalized": normalized,
                "canonical_code": code,
                "canonical_name": self.canonical_skills[code]["canonical_name"],
                "category": self.canonical_skills[code]["category"]
            }

        # 3. Fuzzy match
        fuzzy = self._fuzzy_match(key)
        if fuzzy:
            code, confidence = fuzzy
            return {
                "status": "RESOLVED",
                "match_type": "FUZZY",
                "confidence": confidence,
                "raw_skill": raw_skill,
                "normalized": normalized,
                "canonical_code": code,
                "canonical_name": self.canonical_skills[code]["canonical_name"],
                "category": self.canonical_skills[code]["category"]
            }

        # 4. Unmapped: Enqueue to Generic MDM Hub
        unmapped_entry = self._enqueue_unmapped(normalized, source, sample_context)
        return {
            "status": "UNMAPPED",
            "match_type": "NONE",
            "confidence": 0.0,
            "raw_skill": raw_skill,
            "normalized": normalized,
            "canonical_code": None,
            "unmapped_id": unmapped_entry["id"],
            "occurrence_count": unmapped_entry["occurrence_count"]
        }

    def reconcile_all(
        self,
        raw_skills: List[str],
        source: str = "HH_RU",
        sample_context: str = ""
    ) -> List[Dict[str, Any]]:
        """Splits composite strings and reconciles each discrete skill."""
        results = []
        for raw in raw_skills:
            atomic_tokens = self.split_composite_skills(raw)
            for token in atomic_tokens:
                res = self.reconcile_skill(token, source, sample_context)
                results.append(res)
        return results

    def _enqueue_unmapped(
        self,
        raw_value: str,
        source: str,
        sample_context: str
    ) -> Dict[str, Any]:
        """Record or update an unmapped skill in the Generic MDM Hub queue."""
        key = raw_value.lower()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Look for existing pending entry with same normalized value
        for entry in self.unmapped_queue.values():
            if entry["raw_value"].lower() == key and entry["status"] == "PENDING":
                entry["occurrence_count"] += 1
                entry["last_seen_at"] = now_iso
                if sample_context and not entry.get("sample_context"):
                    entry["sample_context"] = sample_context
                return entry

        entry_id = str(uuid.uuid4())
        entry = {
            "id": entry_id,
            "entity_type": "SKILL",
            "raw_value": raw_value,
            "source_code": source,
            "occurrence_count": 1,
            "first_seen_at": now_iso,
            "last_seen_at": now_iso,
            "sample_context": sample_context,
            "status": "PENDING",
            "resolved_to_code": None
        }
        self.unmapped_queue[entry_id] = entry
        return entry

    def get_unmapped_queue(
        self,
        status: str = "PENDING",
        source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return list of unmapped entries filtered by status and source."""
        entries = [
            e for e in self.unmapped_queue.values()
            if (not status or e["status"] == status) and
               (not source or e["source_code"] == source)
        ]
        return sorted(entries, key=lambda x: x["occurrence_count"], reverse=True)

    def resolve_unmapped(
        self,
        unmapped_id: str,
        target_canonical_code: str,
        create_alias: bool = True
    ) -> Dict[str, Any]:
        """1-Click Resolve endpoint integration for Generic MDM Hub."""
        if unmapped_id not in self.unmapped_queue:
            raise ValueError(f"Unmapped entry '{unmapped_id}' not found.")
        if target_canonical_code not in self.canonical_skills:
            raise ValueError(f"Canonical skill code '{target_canonical_code}' does not exist.")

        entry = self.unmapped_queue[unmapped_id]
        entry["status"] = "RESOLVED"
        entry["resolved_to_code"] = target_canonical_code
        entry["resolved_at"] = datetime.now(timezone.utc).isoformat()

        raw_val = entry["raw_value"].strip().lower()
        if create_alias:
            self.alias_to_code[raw_val] = target_canonical_code
            aliases = self.canonical_skills[target_canonical_code].setdefault("aliases", [])
            if raw_val not in aliases:
                aliases.append(raw_val)

        return {
            "status": "SUCCESS",
            "unmapped_id": unmapped_id,
            "canonical_code": target_canonical_code,
            "canonical_name": self.canonical_skills[target_canonical_code]["canonical_name"],
            "new_alias_registered": raw_val if create_alias else None
        }

    def get_canonical_dictionary(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return canonical dictionary matching filters."""
        results = []
        search_lower = search.lower() if search else None

        for item in self.canonical_skills.values():
            if category and item.get("category") != category:
                continue
            if search_lower:
                name_match = search_lower in item["canonical_name"].lower()
                code_match = search_lower in item["code"].lower()
                alias_match = any(search_lower in a.lower() for a in item.get("aliases", []))
                if not (name_match or code_match or alias_match):
                    continue
            results.append(item)

        return sorted(results, key=lambda x: x["canonical_name"])
