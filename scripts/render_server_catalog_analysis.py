"""Build a Korean report and portable comparison page from the server census."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys

LABELS = {"title": "제목", "description": "설명", "publisher": "제공기관", "url": "자료 링크",
          "metadata_url": "수집 근거 링크", "native_id": "native_id 필드", "format": "형식",
          "license": "이용조건", "region": "지역", "period": "기간", "source_modified": "수정일", "subjects": "원문 분류"}


def pct(n, d):
    return f"{100*n/d:.1f}%" if d else "—"


def escape_md(value):
    return str(value).replace("|", " / ").replace("\n", " ")


def report_markdown(d):
    total = d["groups"]["all"]
    kr, foreign = d["groups"]["domestic"], d["groups"]["foreign_international"]
    n = total["analysis_rows"]
    q = total["quality_signals"]
    domestic_sources = [s for s in d["sources"] if s["country"] == "대한민국"]
    states = Counter(s.get("scan", {}).get("status", "미기재") for s in d["sources"])
    out = ["# 서버 데이터: 국내외 포털 전수 비교", "",
           f"분석 시각: {d['started_at']} ~ {d['finished_at']} (UTC). 입력: 실제 서버의 `catalog.sqlite3`.", "",
           "## 확인한 결과", "",
           f"서버의 등록정보 **{total['raw_rows']:,}건을 전부 읽어 분석**했다. 등록 출처는 {d['registered_sources']}곳이며 "
           f"{d['sources_with_rows']}곳에 자료가 있다. 서버의 기존 중복 표시 {total['duplicate_marked_rows']:,}건을 제외한 "
           f"**{n:,}건**을 내용 비교의 분모로 사용했다. 이는 전 세계 고유 데이터셋 수나 원자료 관측값 수가 아니다.", "",
           "| 구분 | 등록 출처 | 전체 등록정보 | 중복 표시 제외 후 | 전체 등록정보 중 비중 |",
           "|---|---:|---:|---:|---:|",
           f"| 국내 | {len(domestic_sources)} | {kr['raw_rows']:,} | {kr['analysis_rows']:,} | {pct(kr['raw_rows'],total['raw_rows'])} |",
           f"| 해외·국제기구 | {d['registered_sources']-len(domestic_sources)} | {foreign['raw_rows']:,} | {foreign['analysis_rows']:,} | {pct(foreign['raw_rows'],total['raw_rows'])} |", "",
           "국내·해외 구분은 포털 운영 주체의 국가 표기이며 자료의 지리적 범위를 뜻하지 않는다.", "",
           "**포털마다 한 건의 단위가 다르다.** 저장된 수집 범위에 따르면 World Bank는 데이터베이스·시리즈, "
           "OECD는 dataflow, WHO는 지표 정의, KOSIS는 통계표, 미국 Census는 연도판을 묶은 시리즈다. "
           "따라서 건수는 저장량을 설명하며 실제 제공 데이터의 양이나 국가별 데이터 개방 수준을 같은 단위로 비교한 수치가 아니다.", "",
           "## 메타데이터: 어떤 정보가 실제로 기재돼 있는가", "",
           "공백과 `미상`, `제공처 확인` 등 분석 사전에 정의한 기본 미확인 표기는 제외했다. 기재 여부를 측정한 것이며 정확성·표준 준수·라이선스 허가는 검증하지 않았다. "
           "다른 코드 형태의 미확인 값이나 구분자만 있는 문자열까지 의미적으로 검증한 기재율은 아니다.", "",
           "| 항목 | 전체 기재 건수 | 전체 기재율 | 국내 기재율 | 해외·국제기구 기재율 |",
           "|---|---:|---:|---:|---:|"]
    for key, label in LABELS.items():
        out.append(f"| {label} | {total['informative'].get(key,0):,} | {pct(total['informative'].get(key,0),n)} | "
                   f"{pct(kr['informative'].get(key,0),kr['analysis_rows'])} | {pct(foreign['informative'].get(key,0),foreign['analysis_rows'])} |")
    out += ["", "위 표는 자료 건수로 가중한 평균이다. 대형 포털의 영향을 확인하기 위해 **자료가 있는 포털마다 같은 비중을 준 평균**도 비교한다.", "",
            "| 항목 | 국내 포털 평균 | 해외·국제기구 포털 평균 |", "|---|---:|---:|"]
    for key in ("description", "license", "region", "period", "source_modified"):
        averages=[]
        for is_domestic in (True,False):
            rates=[s["metrics"]["field_rates_pct"][key] for s in d["sources"]
                   if (s["country"]=="대한민국")==is_domestic and s["metrics"]["analysis_rows"]]
            averages.append(f"{sum(rates)/len(rates):.1f}%" if rates else "—")
        out.append(f"| {LABELS[key]} | {averages[0]} | {averages[1]} |")
    out += ["", "`native_id`는 해당 이름의 메타데이터 필드만 측정했다. `external_id`·DB 기본 키 등 다른 식별자 필드의 존재 여부와 다르다. 예를 들어 서울 자료에는 다른 필드에 식별자가 있어도 이 항목은 0%로 나온다.", "",
            "기재 수치의 해석에 추가 검토가 필요한 실제 저장 값:", ""]
    for flag in interpretation_flags(d):
        out.append(f"- {flag['source_name']}의 `{flag['field']}` 값 `{flag['value']}`: **{flag['rows']:,}건**. {flag['interpretation']}")
    out += ["", f"지역과 기간이 모두 기재된 자료는 **{q.get('region_and_period_stated',0):,}건 ({pct(q.get('region_and_period_stated',0),n)})**이다. "
            "지역명·기간이 있다는 것만으로 지역코드 체계, 공간·시간 해상도, 모집단, 측정 단위가 맞는 것은 아니므로 조인 가능 건수로 해석하지 않는다.", "",
            f"확인한 최상위 명세·단위·결합 키 목록 중 값이 기재된 자료는 **{q.get('schema_or_join_key_declared',0):,}건**이다. "
            "이 수치는 JSON 최상위의 제한된 키 검사 결과이며, 설명문·외부 명세·중첩 구조에 정보가 없다는 뜻은 아니다.", "",
            "## 수정일과 수집 상태", "",
            f"완전한 날짜로 해석되는 수정일: **{q.get('modified_date_parseable',0):,}건**. "
            f"그중 미래 날짜: **{q.get('modified_date_future',0):,}건**. "
            f"기준일 이전 365일 내 수정일이 기재된 자료: **{q.get('modified_within_365_days',0):,}건** "
            f"(전체 비교 대상 대비 {pct(q.get('modified_within_365_days',0),n)}).", "",
            "수정일이 없으면 관측값이 오래됐다고 판단할 수 없다. 데이터 갱신 주기나 실제 관측 기간과의 일치 여부도 이번 분석에서 확인하지 않았다.", "",
            "저장된 수집 상태: " + ", ".join(f"`{s}` {v}곳" for s,v in states.items()) + ". 새로 외부 포털의 전체 목록과 대조한 결과는 아니다.", "",
            "| 보류 또는 자료 없는 출처 | 등록 건수 | 수집 상태 | 저장된 대조 상태 |",
            "|---|---:|---|---|"]
    for s in d["sources"]:
        if s.get("scan",{}).get("status") != "complete" or not s["metrics"]["raw_rows"]:
            out.append(f"| {escape_md(s['name'])} | {s['metrics']['raw_rows']:,} | {escape_md(s.get('scan',{}).get('status'))} | {escape_md(s.get('collection_audit',{}).get('status'))} |")
    out += ["", "## 개념 분류와 관계 검증", "",
            f"기존 주제로 분류된 자료: **{q.get('classified_rows',0):,}건**. 미분류: **{q.get('unclassified_rows',0):,}건**. "
            f"둘 이상의 주제가 붙은 자료: **{q.get('multiple_concept_rows',0):,}건**.", "",
            "저장된 매핑 상태별 수는 자료 건수와 다르며 한 자료에 여러 매핑이 붙을 수 있다.", "",
            "| 매핑 상태 | 저장 건수 |", "|---|---:|"]
    for status, count in sorted(total["mapping_status"].items()):
        out.append(f"| `{escape_md(status)}` | {count:,} |")
    out += ["", f"`approved` 매핑 중 검사한 검토자 필드가 없는 것은 **{q.get('approved_mapping_without_reviewer_field',0):,}건**이다. "
            f"검토자 필드가 있는 것은 **{q.get('approved_mapping_with_reviewer_field',0):,}건**이다. "
            "두 경우 모두 실제 사람이 의미·자료형·단위·분석 결과를 검토했는지는 별도 확인이 필요하다.", "",
            "| 주제 | 전체 자료 | 국내 자료 | 해외·국제기구 자료 |", "|---|---:|---:|---:|"]
    for cid, count in sorted(total["concept_counts"].items(), key=lambda x:-x[1]):
        out.append(f"| {d['concepts'][cid]} | {count:,} | {kr['concept_counts'].get(cid,0):,} | {foreign['concept_counts'].get(cid,0):,} |")
    out += ["", "복수 주제 분류가 있어 합계가 자료 수보다 커질 수 있다. 주제 구성에는 기존 분류 규칙·언어·수집 범위의 영향이 포함돼 있다.", "",
            "## 함께 살펴볼 연결 후보", "",
            "다음은 설명문에서 실제로 발견한 단서다. 한국어·영어 패턴으로 검사했으며 다국어 전체를 포괄하는 검사가 아니다.", "",
            "| 연결 단서 | 해당 설명이 있는 자료 | 검증해야 하는 내용 |", "|---|---:|---|"]
    for key, label, check in [
        ("administrative_area_code", "행정구역 코드", "코드 체계, 자릿수, 적용 시점, 행정구역 변경"),
        ("geographic_coordinates", "위도·경도·좌표계", "좌표계, 좌표 순서, 위치 정밀도와 공간 범위"),
        ("statistical_unit", "통계·측정 단위", "단위, 집계 대상, 모집단과 통계 정의")]:
        out.append(f"| {label} | {q.get('text_hint_'+key,0):,} | {check} |")
    out += ["", "같은 자료에 동시에 붙은 주제 중 출현 수가 많은 쌍:", "",
            "| 주제 A | 주제 B | 함께 붙은 자료 수 |", "|---|---|---:|"]
    for pair in d["topic_cooccurrence_examples"][:10]:
        out.append(f"| {d['concepts'][pair['concept_a']]} | {d['concepts'][pair['concept_b']]} | {pair['rows']:,} |")
    out += ["", "이는 **저장된 분류의 동시 출현**이다. 예를 들어 교통·환경 분류가 같이 붙어 있어도 교통량과 대기오염의 상관관계를 검증한 것은 아니다.", "",
            "## 포털별 비교표", "",
            "기재 점수는 8개 항목의 평균 기재율을 0~10으로 표현한 것이다. 원자료 품질이나 기관 신뢰도 순위가 아니다. "
            "유형별로 불필요한 항목과 수집기의 생략 가능성을 반영한 별도 QA가 필요하다.", "",
            "| 포털 | 원시 등록 | 비교 분모 | 기재 점수 /10 | 설명 | 지역 | 기간 | 이용조건 | 미분류 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in sorted(d["sources"], key=lambda x:-x["metrics"]["raw_rows"]):
        m=s["metrics"]; count=m["analysis_rows"]; val=m["metadata_documentation_score_0_10"]
        parts=[escape_md(s["name"]),f"{m['raw_rows']:,}",f"{count:,}",f"{val:.2f}" if val is not None else "—"]
        parts += [pct(m["informative"].get(k,0),count) for k in ("description","region","period","license")]
        parts.append(f"{m['quality_signals'].get('unclassified_rows',0):,}")
        out.append("| "+" | ".join(parts)+" |")
    out += ["", "## 다음 작업", "",
            "1. 통계표·지표·시리즈·데이터베이스·파일·API의 등록 단위를 구분하고, 온톨로지에 서로 다른 자료 유형으로 표현한다.",
            "2. 자료 수가 많지만 기간·지역·이용조건 등 기재가 부족한 출처를 골라 원문과 수집기를 대조한다. 포털에 없는 정보인지 수집에서 빠진 정보인지 먼저 구분한다.",
            "3. 통계 포털에는 지표 정의·모집단·측정 단위·주기·지역 코드, 공간 포털에는 좌표계·해상도·경계 버전, 범용 카탈로그에는 자료 유형·스키마·접근 경로 등 유형별 QA 기준을 적용한다. [유형별 QA 초안](../qa-policy.json)을 참고한다.",
            "4. [연결 단서 검토 후보](review-candidates.json)에서 원문 명세 확인을 시작하고, 상대 자료를 선정한 뒤 키·형식·기간·공간·단위가 맞는지 사람이 검토한다.",
            "5. 실제 상관분석이 필요하면 그다음에 특정 주제의 관측값을 확보하고 결측·표본·집계 조건을 맞춘다.", "",
            "## 재현 근거", "",
            f"- 스크립트 SHA-256: `{d.get('execution',{}).get('script_sha256','fixture')}`",
            f"- 읽은 행 스트림 SHA-256: `{d['provenance']['dataset_row_stream_sha256']}`",
            f"- SQL 등록 수와 실제 순회 수 일치: `{d['validation']['sql_counts_equal_scanned_counts']}`",
            f"- 분석 프로세스 최대 RSS: `{d['provenance'].get('max_rss_kib_linux')}` KiB (Linux 기준)",
            f"- 분석 중 다른 연결의 DB 변경 감지: `{d['provenance']['other_connection_change_observed']}`",
            "- 서버 원본 수정·관계 승인·원자료 다운로드: 하지 않음.",
            "- 집계 및 출처별 저장 근거: [report.json](report.json)",
            "- 측정 규칙과 실행 방법: [분석 안내](../README.md)", ""]
    return "\n".join(out)


def interpretation_flags(d):
    cases=[("eu","license","http://inspire.ec.europa.eu/metadata-codelist/ConditionsApplyingToAccessAndUse/conditionsUnknown",
            "조건 미확인을 나타내는 코드 URL도 1차 문자열 기재에 포함된다. 알려진 재사용 조건의 확보율로 해석하면 안 된다."),
           ("us","region",",,,","구분자만 있는 문자열이다. 1차 기재율에 포함되지만 실제 지역 범위로 사용할 수 없다."),
           ("worldbank","region","여러 국가·지역","포괄적 범위 표기다. 구체적인 국가 코드나 공간 해상도가 확보됐다는 뜻은 아니다."),
           ("eu","period","1900-01-01T00:00:00Z","실제 관측 범위인지 기본 날짜 표기인지 원문 검토가 필요하다. 자동 오류 판정은 하지 않았다.")]
    flags=[]
    for sid,field,value,meaning in cases:
        source=next((s for s in d['sources'] if s['id']==sid),None)
        if not source:continue
        item=next((x for x in source['metrics']['common_values'][field] if x['value']==value),None)
        if item:
            flags.append({'source_id':sid,'source_name':source['name'],'field':field,'value':value,'rows':item['rows'],
                          'interpretation':meaning,'status':'needs_semantic_review','counts_reclassified':False})
    return flags


def render(path):
    d=json.loads(path.read_text(encoding="utf-8"))
    path.with_name("REPORT.md").write_text(report_markdown(d),encoding="utf-8")
    compact={"started_at":d["started_at"],"finished_at":d["finished_at"],"groups":{},"sources":[],
             "concepts":d["concepts"],"similarities":d["topic_distribution_similarity"],
             "pairs":d["topic_cooccurrence_examples"],"labels":LABELS,"interpretation_flags":interpretation_flags(d)}
    keep=("raw_rows","analysis_rows","duplicate_marked_rows","informative","field_rates_pct","quality_signals",
          "concept_counts","mapping_status","metadata_documentation_score_0_10","common_values","examples","review_samples")
    for key,g in d["groups"].items():compact["groups"][key]={k:g[k] for k in keep}
    for s in d["sources"]:
        compact["sources"].append({k:s.get(k) for k in ("id","name","country","url","scan","collection_audit")}
                                 | {"metrics":{k:s["metrics"][k] for k in keep}})
    payload=json.dumps(compact,ensure_ascii=False,separators=(",",":" )).replace("<","\\u003c")
    template=Path(__file__).with_name("server_catalog_report.template.html").read_text(encoding="utf-8")
    assert template.count("__REPORT_DATA__")==1
    path.with_name("index.html").write_text(template.replace("__REPORT_DATA__",payload),encoding="utf-8")
    queue=[]
    checks={"administrative_area_code":["원문 칼럼 명세에서 실제 키 확인","코드 관리기관·체계·버전·기준일 확인","후보 자료와 키 값 범위·형식·행정구역 변경 대조"],
            "geographic_coordinates":["좌표 칼럼·자료형 확인","좌표계·축 순서·공간 정밀도 확인","후보 자료와 공간 범위·시점 대조"],
            "statistical_unit":["실제 지표 정의·관측 대상 확인","단위·모집단·집계 주기 확인","후보 자료와 관측 기간·표본 대조"]}
    for s in d["sources"]:
        for hint,examples in s["metrics"]["examples"].items():
            for item in examples:
                queue.append({"id":f"review:{s['id']}:{hint}:{item['id']}","candidate_kind":hint,"source":s["id"],
                              "dataset_id":item["id"],"title":item["title"],"url":item["url"],
                              "observed_text":item["matched_text"],"evidence_field":item["field"],
                              "status":"needs_source_schema_review","human_approved":False,
                              "proposed_partner_dataset":None,"joinability_verified":False,"correlation_tested":False,
                              "required_checks":checks[hint]})
    path.with_name("review-candidates.json").write_text(json.dumps({"generated_from":path.name,"scope":"bounded illustrative examples, not all hint matches",
                                                                   "candidate_count":len(queue),"candidates":queue},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    path.with_name('interpretation-flags.json').write_text(json.dumps({'scope':'observed examples requiring semantic review; not exhaustive',
                                                                     'flags':interpretation_flags(d)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({"markdown":str(path.with_name('REPORT.md')),"comparison":str(path.with_name('index.html'))}))


if __name__=="__main__":
    render(Path(sys.argv[1]))
