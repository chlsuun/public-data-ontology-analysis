"""Exercise consequential denominators and interpretation on a small fake catalog."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from analyze_server_catalog import analyze, informative, parse_modified
from render_server_catalog_analysis import render


class CatalogAnalysisTests(unittest.TestCase):
    def test_unknown_values_are_not_documented_information(self):
        for value in (None, "미상", "제공처 확인", " ", "N/A", [], {"unit": "미확인"}):
            self.assertFalse(informative(value), value)
        for value in ("서울특별시", "2020-2024", ["인구"], 0):
            self.assertTrue(informative(value), value)

    def test_calendar_dates_require_a_real_complete_date(self):
        self.assertIsNone(parse_modified("2026"))
        self.assertIsNone(parse_modified("2026-02-30"))
        self.assertIsNone(parse_modified("updated in 2026"))
        self.assertEqual(str(parse_modified("2026-09-14T12:30:00Z")), "2026-09-14")

    def test_full_scan_preserves_denominators_and_review_uncertainty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "catalog.sqlite3"
            graph = Path(tmp) / "graph.json"
            graph.write_text(json.dumps({"concepts": [{"id": "population", "name": "인구"},
                                                       {"id": "employment", "name": "고용"}]}), encoding="utf-8")
            c = sqlite3.connect(db)
            c.executescript("CREATE TABLE sources(id TEXT,info TEXT,last_sync TEXT,last_error TEXT);"
                            "CREATE TABLE datasets(id TEXT,source_id TEXT,title TEXT,description TEXT,metadata TEXT,mappings TEXT,fingerprint TEXT,checked_at TEXT);")
            for sid, country in [("kr", "대한민국"), ("foreign", "해외"), ("empty", "해외")]:
                c.execute("INSERT INTO sources VALUES(?,?,?,?)", (sid, json.dumps({"id": sid, "country": country}), "", ""))
            future = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
            rows = [
                ("a", "kr", "지역 인구", "행정동코드로 집계", {"region": "서울", "period": "2025", "license": "제공처 확인",
                                                            "url": "https://example.org/a", "source_modified": future},
                 [{"concept_id": "population", "status": "approved", "method": "keyword", "evidence": "인구"},
                  {"concept_id": "employment", "status": "rejected", "method": "keyword"}]),
                ("b", "kr", "복제 등록", "", {"duplicate_of": "a"}, [{"concept_id": "population", "status": "classified"}]),
                ("c", "foreign", "labor population", "", {"region": "미상", "period": "미상"},
                 [{"concept_id": "population", "status": "proposed", "method": "keyword"},
                  {"concept_id": "employment", "status": "classified", "method": "keyword"}]),
                ("d", "foreign", "untagged </script><script>window.injected=true</script>", "", {}, []),
            ]
            for rid, sid, title, desc, meta, mappings in rows:
                c.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?)",
                          (rid, sid, title, desc, json.dumps(meta), json.dumps(mappings), "hash", "2026-09-14T00:00:00Z"))
            c.commit()
            c.close()
            before = db.read_bytes()
            report = analyze(db, graph)
            self.assertEqual(before, db.read_bytes())
            all_rows = report["groups"]["all"]
            self.assertEqual((all_rows["raw_rows"], all_rows["analysis_rows"], all_rows["duplicate_marked_rows"]), (4, 3, 1))
            self.assertEqual(all_rows["field_rates_pct"]["region"], 33.3333)
            self.assertEqual(all_rows["informative"]["license"], 0)
            self.assertEqual(all_rows["quality_signals"]["unclassified_rows"], 1)
            self.assertEqual(all_rows["quality_signals"]["approved_mapping_without_reviewer_field"], 1)
            self.assertEqual(all_rows["quality_signals"]["modified_date_future"], 1)
            self.assertEqual(all_rows["quality_signals"]["modified_within_365_days"], 0)
            self.assertEqual(all_rows["concept_pairs"], [{"concept_a": "employment", "concept_b": "population", "rows": 1}])
            empty = next(p for p in report["sources"] if p["id"] == "empty")
            self.assertIsNone(empty["metrics"]["metadata_documentation_score_0_10"])
            self.assertTrue(report["validation"]["sql_counts_equal_scanned_counts"])
            # The portable report treats source text as data, including script-like text.
            report["sources"][0]["name"] = "</script><script>window.injected=true</script>"
            for source in report["sources"]:
                if not source.get("name"):
                    source["name"] = source["id"]
            report_path = Path(tmp) / "report.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            render(report_path)
            page = report_path.with_name("index.html").read_text(encoding="utf-8")
            self.assertNotIn("</script><script>window.injected=true</script>", page)
            self.assertIn("\\u003c/script>", page)
            queue = json.loads(report_path.with_name("review-candidates.json").read_text(encoding="utf-8"))
            self.assertEqual(queue["candidate_count"], 1)
            self.assertFalse(queue["candidates"][0]["human_approved"])


if __name__ == "__main__":
    unittest.main()
