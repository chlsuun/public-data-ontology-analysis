"""Read-only, bounded-memory census of the wanted-atlas SQLite catalog.

Run on the database host; stdout is aggregate JSON and stderr is progress.
This does not import the application, fetch source sites, or approve mappings.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
try:
    import resource
except ImportError:  # Allows the small reproducibility tests to run on Windows.
    resource = None
import sqlite3
import sys
import time

VERSION = "1.0.2"
FIELDS = ("title", "description", "publisher", "url", "metadata_url", "native_id",
          "format", "license", "region", "period", "source_modified", "subjects")
SCORE_FIELDS = ("title", "description", "publisher", "url", "format", "license", "region", "period")
PLACEHOLDERS = {"", "미상", "미제공", "미확인", "제공처확인", "확인필요", "알수없음",
                "정보없음", "없음", "해당없음", "unknown", "notavailable", "notprovided",
                "unspecified", "none", "null", "n/a", "na", "-", "--"}
CLASSIFICATION_STATUSES = {"approved", "classified", "proposed"}
HINTS = {
    "administrative_area_code": r"행정동\s*코드|법정동\s*코드|시군구\s*코드|행정표준코드|행정기관코드|administrative\s+(?:area\s+)?code|fips\s+code|nuts\s+code",
    "geographic_coordinates": r"위도|경도|좌표계|EPSG\s*:?\s*\d+|\blatitude\b|\blongitude\b|coordinate\s+reference",
    "statistical_unit": r"측정\s*단위|통계\s*단위|집계\s*단위|unit\s+of\s+measure|measurement\s+unit",
}
HINT_REGEX = {k: re.compile(v, re.I) for k, v in HINTS.items()}
HINT_PREFILTERS = {
    "administrative_area_code": ("행정동", "법정동", "시군구", "행정표준코드", "행정기관코드", "administrative", "fips", "nuts"),
    "geographic_coordinates": ("위도", "경도", "좌표계", "epsg", "latitude", "longitude", "coordinate"),
    "statistical_unit": ("측정", "통계", "집계", "unit", "measurement"),
}
JOIN_METADATA_KEYS = {"columns", "fields", "schema", "dimensions", "unit", "units",
                      "spatial_resolution", "temporal_resolution", "code_system", "join_keys"}


def normalized(value):
    return "".join(value.split()).casefold()


def supplied(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return not isinstance(value, bool)


def informative(value):
    if isinstance(value, str):
        # A prefix longer than every placeholder cannot normalize to a placeholder.
        # Avoid repeatedly copying long descriptions and mapping evidence strings.
        if len(value) > 64 and len(normalized(value[:64])) > 16:
            return True
        return normalized(value) not in PLACEHOLDERS
    if isinstance(value, dict):
        return any(informative(x) for x in value.values())
    if isinstance(value, list):
        return any(informative(x) for x in value)
    return supplied(value)


def declared_url(value):
    # Syntax signal only; no live link or access-right verification.
    return isinstance(value, str) and bool(re.match(r"^https?://[^\s/]+", value, re.I))


def parse_modified(value):
    # Accept a complete calendar date only; years in titles are not update dates.
    if not isinstance(value, str):
        return None
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:$|[T\s])", value.strip())
    if not m:
        return None
    try:
        return date(*map(int, m.groups()))
    except ValueError:
        return None


def new_profile():
    return {"raw_rows": 0, "duplicate_marked_rows": 0, "analysis_rows": 0,
            "supplied": Counter(), "informative": Counter(), "placeholder": Counter(),
            "quality_signals": Counter(), "metadata_keys": Counter(), "mapping_status": Counter(),
            "mapping_method": Counter(), "concept_counts": Counter(), "concept_pairs": Counter(),
            "modified_age_days": Counter(), "modified_date_min": None, "modified_date_max": None,
            "common_values": {k: Counter() for k in ("license", "format", "region", "period")},
            "examples": {}, "review_samples": []}


def merge_profiles(profiles):
    out = new_profile()
    for p in profiles:
        for k in ("raw_rows", "duplicate_marked_rows", "analysis_rows"):
            out[k] += p[k]
        for k in ("supplied", "informative", "placeholder", "quality_signals", "metadata_keys",
                  "mapping_status", "mapping_method", "concept_counts", "concept_pairs", "modified_age_days"):
            out[k].update(p[k])
    return out


def rate(n, d):
    return round(100 * n / d, 4) if d else None


def score(p):
    n = p["analysis_rows"]
    return round(10 * sum(p["informative"][k] for k in SCORE_FIELDS) / (len(SCORE_FIELDS) * n), 4) if n else None


def serialize(p):
    result = dict(p)
    result["field_rates_pct"] = {k: rate(p["informative"][k], p["analysis_rows"]) for k in FIELDS}
    result["metadata_documentation_score_0_10"] = score(p)
    result["common_values"] = {k: [{"value": v, "rows": n} for v, n in c.most_common(8)] for k, c in p["common_values"].items()}
    result["concept_pairs"] = [{"concept_a": a, "concept_b": b, "rows": n}
                               for (a, b), n in p["concept_pairs"].most_common()]
    result["modified_age_days"] = {str(k): v for k, v in sorted(p["modified_age_days"].items())}
    return result


def compare_portals(profiles):
    pairs = []
    # Tiny catalogs and catalogs with little classified content have unstable profiles.
    candidates = [(sid, p) for sid, p in profiles.items()
                  if p["analysis_rows"] >= 100 and p["quality_signals"]["classified_rows"] >= 100]
    for (a, pa), (b, pb) in itertools.combinations(candidates, 2):
        ca, cb = pa["concept_counts"], pb["concept_counts"]
        shared = sorted(ca.keys() & cb.keys())
        norm = math.sqrt(sum(x*x for x in ca.values()) * sum(x*x for x in cb.values()))
        similarity = sum(ca[k] * cb[k] for k in shared) / norm if norm else None
        pairs.append({"source_a": a, "source_b": b, "cosine_similarity": round(similarity, 6) if similarity is not None else None,
                      "shared_concepts": shared, "source_a_rows": pa["analysis_rows"], "source_b_rows": pb["analysis_rows"],
                      "interpretation": "stored_topic_distribution_similarity_only"})
    return sorted(pairs, key=lambda p: -(p["cosine_similarity"] or 0))


def analyze(db_path, graph_path, max_seconds=1800, progress_every=100000):
    started = datetime.now(timezone.utc)
    start_clock = time.monotonic()
    if hasattr(os, "nice"):
        os.nice(10)
    db_path = Path(db_path).resolve(strict=True)
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA cache_size=-16384")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.set_progress_handler(lambda: int(time.monotonic() - start_clock > max_seconds), 100000)
    before = conn.execute("PRAGMA data_version").fetchone()[0]
    conn.execute("BEGIN")
    source_rows = conn.execute("SELECT id,info,last_sync,last_error FROM sources ORDER BY id").fetchall()
    expected = dict(conn.execute("SELECT source_id,COUNT(*) FROM datasets GROUP BY source_id"))
    graph_bytes = Path(graph_path).read_bytes()
    graph = json.loads(graph_bytes)
    concepts = {x["id"]: x.get("name", x["id"]) for x in graph["concepts"] if x["id"] != "unclassified"}
    sources, profiles = {}, {}
    for sid, info, synced, error in source_rows:
        info = json.loads(info)
        sources[sid] = {k: info.get(k) for k in ("id", "name", "url", "country", "authority", "method")}
        sources[sid].update({"last_sync": synced, "last_error": error, "scan": info.get("scan", {}),
                             "collection_audit": info.get("collection_audit", {})})
        profiles[sid] = new_profile()
    digest = hashlib.sha256()
    sources_digest = hashlib.sha256(json.dumps(source_rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    pair_examples = {}
    raw_unclassified, scanned = 0, 0
    checked_min = checked_max = None
    cursor = conn.execute("SELECT rowid,id,source_id,title,description,metadata,mappings,fingerprint,checked_at FROM datasets ORDER BY rowid")
    for rowid, rid, sid, title, description, raw_meta, raw_map, fingerprint, checked_at in cursor:
        if sid not in profiles:
            raise ValueError("Dataset references unregistered source: " + sid)
        # Length framing makes the hash unambiguous even if a field contains newlines.
        for value in (str(rowid), rid, sid, title, description, raw_meta, raw_map, fingerprint, checked_at):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        meta, mappings = json.loads(raw_meta), json.loads(raw_map)
        if not isinstance(meta, dict) or not isinstance(mappings, list):
            raise ValueError("Unexpected JSON structure for " + rid)
        p = profiles[sid]
        p["raw_rows"] += 1
        scanned += 1
        if scanned % progress_every == 0:
            print(json.dumps({"scanned": scanned, "expected": sum(expected.values()),
                              "elapsed_seconds": round(time.monotonic() - start_clock, 1)}), file=sys.stderr, flush=True)
            if time.monotonic() - start_clock > max_seconds:
                raise TimeoutError("Analysis time budget exceeded; no completed report emitted")
        checked_min = min(checked_min, checked_at) if checked_min else checked_at
        checked_max = max(checked_max, checked_at) if checked_max else checked_at
        valid = {m.get("concept_id") for m in mappings if isinstance(m, dict)
                 and m.get("concept_id") in concepts and m.get("status") in CLASSIFICATION_STATUSES}
        if not valid:
            raw_unclassified += 1
        # Mirrors the server graph's explicit duplicate_of exclusion only.
        if meta.get("duplicate_of") is not None:
            p["duplicate_marked_rows"] += 1
            continue
        p["analysis_rows"] += 1
        values = {k: meta.get(k) for k in FIELDS}
        values.update(title=title, description=description)
        presence = {}
        for k, v in values.items():
            nonblank = supplied(v)
            good = informative(v)
            if k in ("url", "metadata_url"):
                good = good and declared_url(v)
            presence[k] = good
            p["supplied"][k] += int(nonblank)
            p["informative"][k] += int(good)
            p["placeholder"][k] += int(nonblank and not good)
        p["metadata_keys"].update(meta.keys())
        q = p["quality_signals"]
        q["classified_rows" if valid else "unclassified_rows"] += 1
        q["multiple_concept_rows"] += int(len(valid) > 1)
        q["region_and_period_stated"] += int(presence["region"] and presence["period"])
        q["region_period_license_stated"] += int(presence["region"] and presence["period"] and presence["license"])
        q["all_eight_score_fields_stated"] += int(all(presence[k] for k in SCORE_FIELDS))
        q["collection_method_stated"] += int(informative(meta.get("collection_method")))
        q["schema_or_join_key_declared"] += int(any(informative(meta.get(k)) for k in JOIN_METADATA_KEYS))
        q["title_metadata_disagreement"] += int(meta.get("title", title) != title)
        q["description_metadata_disagreement"] += int(meta.get("description", description) != description)
        for k in p["common_values"]:
            v = values[k]
            # Bounded value storage: top values only if short, with an explicit overflow bucket.
            if isinstance(v, (str, int, float)):
                v = str(v)
                if len(v) > 180:
                    v = "[long value: omitted]"
                c = p["common_values"][k]
                c[v if v in c or len(c) < 2000 else "[additional distinct values]"] += 1
        modified = parse_modified(meta.get("source_modified"))
        if modified:
            age = (started.date() - modified).days
            q["modified_date_parseable"] += 1
            q["modified_date_future"] += int(age < 0)
            q["modified_within_365_days"] += int(0 <= age <= 365)
            p["modified_age_days"][age] += 1
            iso = modified.isoformat()
            p["modified_date_min"] = min(p["modified_date_min"], iso) if p["modified_date_min"] else iso
            p["modified_date_max"] = max(p["modified_date_max"], iso) if p["modified_date_max"] else iso
        elif presence["source_modified"]:
            q["modified_date_unparseable"] += 1
        p["concept_counts"].update(valid)
        pairs = list(itertools.combinations(sorted(valid), 2))
        p["concept_pairs"].update(pairs)
        sample = {"id": rid, "source_id": sid, "title": title[:240], "url": meta.get("url"), "concepts": sorted(valid)}
        for pair in pairs:
            examples = pair_examples.setdefault(pair, [])
            if len(examples) < 3:
                examples.append(sample)
        for m in mappings:
            if not isinstance(m, dict):
                q["invalid_mapping_objects"] += 1
                continue
            status = m.get("status", "[missing]")
            p["mapping_status"][status] += 1
            p["mapping_method"][m.get("method", "[missing]")] += 1
            q["mapping_with_evidence"] += int(informative(m.get("evidence")))
            if m.get("concept_id") not in concepts:
                q["mapping_unknown_concept"] += 1
            if status == "approved":
                reviewer = any(informative(m.get(k)) for k in ("reviewer", "reviewer_id", "reviewed_by", "human_reviewer"))
                q["approved_mapping_with_reviewer_field"] += int(reviewer)
                q["approved_mapping_without_reviewer_field"] += int(not reviewer)
                if len(p["review_samples"]) < 3:
                    p["review_samples"].append({**sample, "mapping": m, "human_review_verified": False})
        text = title + "\n" + description
        folded = text.casefold()
        for hint, pattern in HINT_REGEX.items():
            if not any(token in folded for token in HINT_PREFILTERS[hint]):
                continue
            match = pattern.search(text)
            if match:
                q["text_hint_" + hint] += 1
                examples = p["examples"].setdefault(hint, [])
                if len(examples) < 2:
                    examples.append({**sample, "matched_text": match.group(0), "field": "title_or_description",
                                     "status": "candidate_not_verified_join"})
    assert {sid: p["raw_rows"] for sid, p in profiles.items() if p["raw_rows"]} == expected
    assert scanned == sum(expected.values())
    conn.rollback()
    after = conn.execute("PRAGMA data_version").fetchone()[0]
    conn.close()
    global_profile = merge_profiles(profiles.values())
    domestic = [p for sid, p in profiles.items() if sources[sid]["country"] == "대한민국"]
    foreign = [p for sid, p in profiles.items() if sources[sid]["country"] != "대한민국"]
    for p in profiles.values():
        assert p["raw_rows"] == p["duplicate_marked_rows"] + p["analysis_rows"]
        assert p["quality_signals"]["classified_rows"] + p["quality_signals"]["unclassified_rows"] == p["analysis_rows"]
    output = {
        "analysis_version": VERSION, "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {"database_path": str(db_path), "database_bytes": db_path.stat().st_size,
                       "read_only": True, "snapshot_transaction": True, "source_table_sha256": sources_digest,
                       "dataset_row_stream_sha256": digest.hexdigest(), "graph_overview_sha256": hashlib.sha256(graph_bytes).hexdigest(),
                       "sqlite_data_version_before": before, "sqlite_data_version_after": after,
                       "other_connection_change_observed": before != after,
                       "row_stream_order": "SQLite rowid ascending; every selected UTF-8 cell length-prefixed with 8-byte big-endian length",
                       "row_stream_fields": ["rowid", "id", "source_id", "title", "description", "metadata", "mappings", "fingerprint", "checked_at"],
                       "checked_at_min": checked_min, "checked_at_max": checked_max,
                       "max_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None},
        "method": {"scope": "all_registered_domestic_and_foreign_sources", "observation_unit": "dataset_catalog_registration",
                   "denominator": "rows without non-null metadata.duplicate_of; no new cross-portal deduplication",
                   "placeholder_tokens_normalized": sorted(PLACEHOLDERS), "score_fields": SCORE_FIELDS,
                   "score_formula": "10 * informative cells in eight fields / (8 * analysis rows)",
                   "score_interpretation": "stored metadata documentation only; not source reliability, raw-data quality or reuse permission",
                   "modified_age_reference_date_utc": started.date().isoformat(),
                   "date_interpretation": "declared metadata source_modified; no update-cycle compliance or observation freshness test",
                   "mapping_interpretation": "stored classifications including proposed/approved; no human verification assumed",
                   "url_interpretation": "declared HTTP(S) syntax only; no remote endpoint requests",
                   "join_metadata_keys_checked_at_top_level": sorted(JOIN_METADATA_KEYS),
                   "text_hint_patterns": HINTS, "hint_interpretation": "Korean/English keyword candidate evidence, not multilingual exhaustive recall",
                   "country_grouping": "portal owner country field, not geography covered by individual datasets",
                   "limits": ["No raw observations analyzed", "No statistical correlation or causality estimated",
                              "No cross-source equivalence or joinability approved", "Declared duplicates are not globally unique datasets",
                              "No universal portal quality ranking", "Collection audit statuses are stored claims, not newly reconciled against live source sites"]},
        "registered_sources": len(sources), "sources_with_rows": sum(bool(p["raw_rows"]) for p in profiles.values()),
        "raw_rows_without_valid_topic": raw_unclassified, "concepts": concepts,
        "groups": {"all": serialize(global_profile), "domestic": serialize(merge_profiles(domestic)),
                   "foreign_international": serialize(merge_profiles(foreign))},
        "sources": [{**sources[sid], "metrics": serialize(profiles[sid])} for sid in sources],
        "topic_distribution_similarity": compare_portals(profiles),
        "topic_cooccurrence_examples": [{"concept_a": a, "concept_b": b, "rows": n,
                                          "examples": pair_examples.get((a, b), []), "status": "stored_coclassification_not_statistical_correlation"}
                                         for (a, b), n in global_profile["concept_pairs"].most_common(30)],
        "validation": {"sql_counts_equal_scanned_counts": True, "duplicate_partition_reconciled": True,
                       "classification_partition_reconciled": True, "database_modified_by_analysis": False},
    }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="/data/catalog.sqlite3")
    parser.add_argument("--graph", default="/data/graph-overview.json")
    parser.add_argument("--max-seconds", type=int, default=1800)
    args = parser.parse_args()
    json.dump(analyze(args.db, args.graph, args.max_seconds), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    print()


if __name__ == "__main__":
    main()
