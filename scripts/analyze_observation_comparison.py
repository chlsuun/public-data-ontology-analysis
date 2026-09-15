"""Reproducible, offline population comparison from preserved official responses."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, correlation
import sys
import xml.etree.ElementTree as ET

COUNTRIES = {"KOR": "한국", "JPN": "일본", "DEU": "독일", "USA": "미국"}
NS = {"g": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic",
      "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
      "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common"}
EXPECTED = {(c, y) for c in COUNTRIES for y in range(2010, 2025)}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def pearson(x, y):
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    return correlation(x, y)


def to_persons(value, multiplier):
    if value in (None, ""):
        return None
    number = Decimal(str(value)) * (Decimal(10) ** int(multiplier))
    if not number.is_finite() or number <= 0:
        raise ValueError("Population must be finite and positive")
    return int(number) if number == number.to_integral_value() else float(number)


def indexed(rows):
    result = {}
    for row in rows:
        key = (row["country"], row["year"])
        if key not in EXPECTED:
            raise ValueError(f"Unexpected country-year: {key}")
        if key in result:
            raise ValueError(f"Duplicate country-year: {key}")
        result[key] = row
    return result


def parse_oecd(path):
    root = ET.parse(path).getroot()
    result = []
    for obs in root.findall(".//g:Obs", NS):
        dims = {v.get("id"): v.get("value") for v in obs.findall("g:ObsKey/g:Value", NS)}
        attrs = {v.get("id"): v.get("value") for v in obs.findall("g:Attributes/g:Value", NS)}
        for name, val in {"MEASURE": "POP", "UNIT_MEASURE": "PS", "SEX": "_T", "AGE": "_T", "TIME_HORIZ": "H"}.items():
            if dims.get(name) != val:
                raise ValueError(f"Unexpected OECD dimension {name}: {dims.get(name)}")
        if "UNIT_MULT" not in attrs:
            raise ValueError("Missing explicit OECD multiplier")
        value_node = obs.find("g:ObsValue", NS)
        raw_value = None if value_node is None else value_node.get("value")
        result.append({"source": "oecd", "country": dims["REF_AREA"], "year": int(dims["TIME_PERIOD"]),
                       "persons": to_persons(raw_value, attrs["UNIT_MULT"]), "raw_value": raw_value,
                       "dimensions": dims, "attributes": attrs, "raw_file": "raw/oecd-population.xml"})
    if not result:
        raise ValueError("No OECD observations parsed")
    return result


def parse_worldbank(path):
    header, records = json.loads(path.read_text(encoding="utf-8"))
    if int(header["pages"]) != 1 or int(header["total"]) != len(records) or header["sourceid"] != "2":
        raise ValueError("Incomplete or wrong World Bank response")
    result = []
    for row in records:
        if row["indicator"]["id"] != "SP.POP.TOTL":
            raise ValueError("Wrong World Bank indicator")
        result.append({"source": "worldbank", "country": row["countryiso3code"], "year": int(row["date"]),
                       "persons": to_persons(row["value"], 0), "raw_value": row["value"],
                       "attributes": {"obs_status": row["obs_status"], "footnote": row.get("footnote", ""),
                                      "unit": row["unit"], "decimal": row["decimal"]},
                       "raw_file": "raw/worldbank-population.json"})
    return result, header


def warnings(country, year, oecd, wb):
    out = []
    if wb["attributes"]["footnote"]:
        out.append({"code": "wb_footnote", "text": wb["attributes"]["footnote"], "sensitivity_exclude": True})
    if oecd["attributes"].get("OBS_STATUS") != "A":
        out.append({"code": "oecd_status", "text": oecd["attributes"].get("OBS_STATUS", "missing"), "sensitivity_exclude": True})
    if country == "JPN" and year == 2024:
        out.append({"code": "reference_date_review", "text": "OECD 국가 설명표: 2024년 10월 추정치. 연중 기준과의 정합성 추가 확인 필요.", "sensitivity_exclude": True})
    if country == "DEU" and year in (2023, 2024):
        out.append({"code": "reference_estimation_review", "text": "OECD 국가 설명표: 1월 1일 추정치를 바탕으로 산출.", "sensitivity_exclude": True})
    if country == "DEU" and year == 2011:
        out.append({"code": "series_benchmark", "text": "OECD 국가 설명표: 2010/11년 새 계열 기준 도입.", "sensitivity_exclude": True})
    if country == "KOR" and year >= 2021:
        out.append({"code": "revised_estimate", "text": "OECD 국가 설명표: 2021~2024년 새 추정치 반영. 개정 안내 자체로 제외하지 않음.", "sensitivity_exclude": False})
    return out


def summarize(pairs, changes):
    if not pairs:
        return {"n": 0}
    worst = max(pairs, key=lambda r: abs(r["difference_pct"]))
    result = {"n": len(pairs), "mean_signed_gap_persons": mean(r["difference_persons"] for r in pairs),
              "mae_persons": mean(abs(r["difference_persons"]) for r in pairs),
              "mean_absolute_gap_pct": mean(abs(r["difference_pct"]) for r in pairs),
              "max_absolute_gap_pct": abs(worst["difference_pct"]), "max_gap_year": worst["year"],
              "exact_equal_pairs": sum(r["difference_persons"] == 0 for r in pairs),
              "level_pearson_r": pearson([r["oecd"] for r in pairs], [r["worldbank"] for r in pairs]),
              "change_n": len(changes),
              "change_pearson_r": pearson([r["oecd_change"] for r in changes], [r["worldbank_change"] for r in changes]),
              "growth_gap_mae_pp": mean(abs(r["growth_gap_pp"]) for r in changes) if changes else None,
              "direction_disagreement_n": sum(r["direction_disagrees"] for r in changes)}
    return result


def analyze(folder):
    raw = folder / "raw"
    receipts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(raw.glob("*.receipt.json"))]
    for receipt in receipts:
        assert receipt.get("status") == 200 and "error" not in receipt
        body = (raw / receipt["file"]).read_bytes()
        assert len(body) == receipt["bytes"]
        assert hashlib.sha256(body).hexdigest() == receipt["sha256"]
    structure = ET.parse(raw / "oecd-structure.xml").getroot()
    dimensions = [d.get("id") for d in structure.findall(".//s:DataStructure/s:DataStructureComponents/s:DimensionList/*", NS)]
    assert dimensions == ["REF_AREA", "MEASURE", "UNIT_MEASURE", "SEX", "AGE", "TIME_HORIZ", "TIME_PERIOD"]
    wbmeta = json.loads((raw / "worldbank-series-metadata.json").read_text())
    meta = {m["id"]: m["value"] for s in wbmeta["source"] for c in s["concept"] for v in c["variable"] for m in v["metatype"]}
    assert meta["Unitofmeasure"] == "Unit" and meta["Periodicity"] == "Annual"
    oecd = parse_oecd(raw / "oecd-population.xml")
    wb, wb_header = parse_worldbank(raw / "worldbank-population.json")
    oi, wi = indexed(oecd), indexed(wb)
    pairs, unmatched = [], []
    for c, y in sorted(EXPECTED):
        a, b = oi.get((c, y)), wi.get((c, y))
        if a is None or b is None or a["persons"] is None or b["persons"] is None:
            unmatched.append({"country": c, "year": y, "oecd_available": a is not None and a["persons"] is not None,
                              "worldbank_available": b is not None and b["persons"] is not None})
            continue
        issues = warnings(c, y, a, b)
        diff = a["persons"] - b["persons"]
        pairs.append({"country": c, "country_name": COUNTRIES[c], "year": y, "oecd": a["persons"], "worldbank": b["persons"],
                      "difference_persons": diff, "difference_pct": 100 * diff / b["persons"],
                      "warnings": issues, "sensitivity_included": not any(w["sensitivity_exclude"] for w in issues)})
    pair_index = {(p["country"], p["year"]): p for p in pairs}
    changes = []
    for pair in pairs:
        prev = pair_index.get((pair["country"], pair["year"] - 1))
        if prev is None:
            continue
        oc, wc = pair["oecd"] - prev["oecd"], pair["worldbank"] - prev["worldbank"]
        og, wg = 100 * oc / prev["oecd"], 100 * wc / prev["worldbank"]
        changes.append({"country": pair["country"], "year": pair["year"], "oecd_change": oc,
                        "worldbank_change": wc, "oecd_growth_pct": og, "worldbank_growth_pct": wg,
                        "growth_gap_pp": og - wg, "direction_disagrees": (oc > 0) - (oc < 0) != (wc > 0) - (wc < 0),
                        "sensitivity_included": pair["sensitivity_included"] and prev["sensitivity_included"]})
    summaries = {}
    for c in COUNTRIES:
        cp, cc = [p for p in pairs if p["country"] == c], [p for p in changes if p["country"] == c]
        summaries[c] = {"country_name": COUNTRIES[c], "all": summarize(cp, cc),
                        "sensitivity": summarize([p for p in cp if p["sensitivity_included"]],
                                                 [p for p in cc if p["sensitivity_included"]])}
    qa = {"requested_country_year_pairs": len(EXPECTED), "oecd_rows": len(oecd), "worldbank_rows": len(wb),
          "oecd_nonmissing": sum(r["persons"] is not None for r in oecd), "worldbank_nonmissing": sum(r["persons"] is not None for r in wb),
          "duplicate_keys": 0, "matched_pairs": len(pairs), "unmatched": unmatched,
          "oecd_status_counts": dict(Counter(r["attributes"].get("OBS_STATUS") for r in oecd)),
          "oecd_multiplier_counts": dict(Counter(r["attributes"]["UNIT_MULT"] for r in oecd)),
          "worldbank_footnote_rows": sum(bool(r["attributes"]["footnote"]) for r in wb),
          "warning_pair_count": sum(bool(p["warnings"]) for p in pairs),
          "sensitivity_excluded_pairs": sum(not p["sensitivity_included"] for p in pairs),
          "sensitivity_pair_count": sum(p["sensitivity_included"] for p in pairs),
          "change_pairs": len(changes), "sensitivity_change_count": sum(r["sensitivity_included"] for r in changes),
          "unit_check": "OECD PS × 10^UNIT_MULT → persons; World Bank Unit + total population definition → persons. Raw WB unit field is blank.",
          "no_imputation": True, "no_interpolation": True,
          "worldbank_lastupdated": wb_header["lastupdated"]}
    process = [
        {"step": 1, "title": "서버 자료에서 후보 선정", "status": "완료", "detail": "서버 DB의 OECD·World Bank·Eurostat·KOSIS 등록정보 6개를 근거로 검토. 인구를 선택하고 국가·기간을 수치 비교 전에 고정.", "evidence": "server-catalog-selection.json"},
        {"step": 2, "title": "공식 원자료 확보", "status": "완료", "detail": f"서버에 저장된 접근 경로에서 출발해 공식 API 관측값 {len(oecd)+len(wb)}개 확보. 서버 DB 자체에는 등록정보가 있었으며, 관측값은 이번에 추가로 내려받음.", "evidence": "raw/oecd-population.xml"},
        {"step": 3, "title": "정의·단위·기준일 대조", "status": "조건부 완료", "detail": "국가·연도·총성별·총연령을 맞추고 명 단위로 통일. 일본 2024년 기준일 및 독일 기준 변경은 주의 항목으로 보존.", "evidence": "oecd-country-metadata-extract.json"},
        {"step": 4, "title": "출처별 데이터 QA", "status": "완료", "detail": f"키 중복·결측·양수 여부·단위 배수·API 상태 코드·각주 확인. World Bank 단절 각주 {qa['worldbank_footnote_rows']}건. 빈 상태 필드는 정상 확인으로 취급하지 않음.", "evidence": "qa.json"},
        {"step": 5, "title": "국가·연도 키로 결합", "status": "완료", "detail": f"같은 국가의 같은 연도를 1:1 연결: {len(pairs)}쌍. 누락 {len(unmatched)}쌍. 보간·대체·임의 합산 없음.", "evidence": "paired-observations.json"},
        {"step": 6, "title": "실제 수치와 증감 비교", "status": "완료", "detail": f"명 차이·상대 차이·연간 증감·증가율 비교. 전체 {len(pairs)}쌍과 주의 항목 제외 {qa['sensitivity_pair_count']}쌍을 따로 계산.", "evidence": "result.json"},
        {"step": 7, "title": "온톨로지 반영 근거 정리", "status": "검토안 작성", "detail": "동일 주제·조건부 비교 가능 관계의 근거로 정리. 같은 수치·인과관계·독립 검증을 뜻하지 않음.", "evidence": "relationship-review.json"},
        {"step": 8, "title": "사람의 관계 승인", "status": "미진행", "detail": "국가별 정의와 개정 이력 검토 후 승인 필요. model.json 및 서버 관계 DB에 자동 확정하지 않음.", "evidence": "relationship-review.json"},
    ]
    relation = {"status": "analysis_completed_pending_human_review", "proposed_predicate": "conditionallyComparableWith",
                "from": "oecd:OECD.ELS.SAE:DSD_POPULATION@DF_POP_HIST|POP.PS._T._T.H",
                "to": "worldbank:source-2|SP.POP.TOTL", "concept": "annual national total population",
                "scope": {"countries": list(COUNTRIES), "years": [2010, 2024]},
                "conditions": ["country and year must match", "total sexes and ages", "normalize persons",
                               "preserve reference-date and break metadata", "preserve upstream source and revision vintage"],
                "evidence": ["result.json", "qa.json", "raw/worldbank-country-series-metadata.json", "oecd-country-metadata-extract.json"],
                "not_established": ["sameAs", "causes", "independent validation", "all portal datasets are comparable"],
                "reviewer": None, "reviewed_at": None, "model_json_modified": False, "server_db_modified": False}
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "topic": "OECD / World Bank 연간 총인구 관측값 비교",
              "scope": {"countries": COUNTRIES, "years": [2010, 2024], "selection": "purposive bounded pilot, not all portal or all topic search"},
              "qa": qa, "country_summaries": summaries, "pairs": pairs, "changes": changes,
              "receipts": receipts, "process": process, "relationship": relation,
              "formulas": {"difference_persons": "OECD - World Bank", "difference_pct": "100*(OECD-World Bank)/World Bank",
                           "mean_absolute_gap_pct": "mean(abs(difference_pct)) over matched years within each country",
                           "annual_change": "value(t)-value(t-1), consecutive years only",
                           "growth_pct": "100*(value(t)-value(t-1))/value(t-1)",
                           "sensitivity": "Exclude metadata-marked breaks/reference-date review rows; annual changes require both endpoints retained"},
              "limits": ["World Bank is a comparison denominator, not ground truth.",
                         "No independent population truth, accuracy score, hypothesis-test p-values or causality claim.",
                         "Shared national statistical upstream sources can produce agreement; source lineage is only partly resolved.",
                         "OECD A status does not cancel country metadata warnings; blank WB status is not proof of validation.",
                         "Sample restricted to two international portals and four countries; not a direct domestic-versus-foreign portal quality ranking.",
                         "Korea is included as a geographic observation; KOSIS is recorded as WB upstream, not a separately downloaded observation source.",
                         "No tolerance for sameAs approval was agreed; a small difference is not automatic equivalence."]}
    write_json(folder / "normalized-observations.json", oecd + wb)
    write_json(folder / "paired-observations.json", pairs)
    write_json(folder / "qa.json", qa)
    write_json(folder / "process.json", process)
    write_json(folder / "relationship-review.json", relation)
    write_json(folder / "result.json", result)
    print(json.dumps({"qa": qa, "results": summaries}, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    analyze(Path(sys.argv[1] if len(sys.argv) > 1 else "analysis/observation-comparison/20260915"))
