"""PACK-v1 completeness. The checklist is data, not a prompt."""

from __future__ import annotations

import re
from typing import Any

_TAXONOMY = {
    "passport",
    "proof_of_address",
    "bank_statement",
    "company_registry",
    "source_of_funds",
}


def is_known_type(value: str) -> bool:
    return value in _TAXONOMY


def intake_allows(folder_path: str, allow_prefix: str) -> bool:
    if not folder_path.startswith(allow_prefix):
        return False
    if ".." in folder_path or "\\" in folder_path:
        return False
    rest = folder_path[len(allow_prefix) :]
    return re.fullmatch(r"[A-Za-z0-9._-]+", rest) is not None


def field_citation(case_id: str, doc_id: str, field_id: str) -> str:
    return f"cite:{case_id}:{doc_id}:{field_id}"


def check_completeness(
    case_file: dict[str, Any],
    pack: dict[str, Any],
    taxonomy_ids: list[str],
) -> dict[str, Any]:
    taxonomy = set(taxonomy_ids)
    profile = pack["profiles"][case_file["profile"]]
    by_type: dict[str, list[dict[str, Any]]] = {}
    unknown_types: list[dict[str, str]] = []

    for doc in case_file["documents"]:
        classified = doc["classifiedType"]
        if classified not in taxonomy or classified == "unknown":
            unknown_types.append(
                {
                    "docId": doc["docId"],
                    "fileName": doc["fileName"],
                    "classifiedType": classified,
                }
            )
            continue
        by_type.setdefault(classified, []).append(doc)

    gaps: list[dict[str, Any]] = []
    case_id = case_file["caseId"]
    for doc_type in profile["requiredDocs"]:
        docs = by_type.get(doc_type, [])
        if not docs:
            gaps.append(
                {
                    "kind": "missing_doc",
                    "docType": doc_type,
                    "citationId": f"gap:{case_id}:missing_doc:{doc_type}",
                    "message": f'Required document "{doc_type}" is not in the named folder.',
                }
            )
            continue
        for field_id in profile["requiredFields"].get(doc_type, []):
            present = any(
                field["id"] == field_id and str(field["value"]).strip()
                for doc in docs
                for field in doc["fields"]
            )
            if not present:
                gaps.append(
                    {
                        "kind": "missing_field",
                        "docType": doc_type,
                        "fieldId": field_id,
                        "citationId": f"gap:{case_id}:missing_field:{doc_type}:{field_id}",
                        "message": f'Required field "{field_id}" is missing on {doc_type}.',
                    }
                )

    low_confidence: list[dict[str, Any]] = []
    required_field_count = 0
    floor = float(pack["confidenceFloor"])
    for doc in case_file["documents"]:
        classified = doc["classifiedType"]
        if not is_known_type(classified):
            continue
        required = set(profile["requiredFields"].get(classified, []))
        for field in doc["fields"]:
            if field["id"] not in required:
                continue
            required_field_count += 1
            if float(field["confidence"]) < floor:
                low_confidence.append(
                    {
                        "docId": doc["docId"],
                        "fieldId": field["id"],
                        "label": field["label"],
                        "confidence": field["confidence"],
                        "citationId": field_citation(case_id, doc["docId"], field["id"]),
                    }
                )

    share = 0.0 if required_field_count == 0 else len(low_confidence) / required_field_count
    return {
        "packId": "PACK-v1",
        "profile": case_file["profile"],
        "complete": len(gaps) == 0,
        "gaps": gaps,
        "lowConfidenceFields": low_confidence,
        "unknownTypes": unknown_types,
        "requiredFieldCount": required_field_count,
        "lowConfidenceShare": share,
    }
