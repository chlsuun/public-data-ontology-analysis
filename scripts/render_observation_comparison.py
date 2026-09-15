"""Render Korean observation analysis, offline HTML, and exportable figures."""
import base64
from html import escape
import json
from pathlib import Path
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent
SOURCES = [
    ("OECD 인구 데이터·구조 명세", "https://sdmx.oecd.org/public/rest/dataflow/OECD.ELS.SAE/DSD_POPULATION@DF_POP_HIST/1.0?references=all"),
    ("OECD 국가별 기준·개정 설명표", "https://www.oecd.org/content/dam/oecd/en/data/datasets/employability-data/MD_POPHIST.xlsx"),
    ("World Bank 지표 정의·단위", "https://api.worldbank.org/v2/sources/2/series/SP.POP.TOTL/metadata?format=json"),
    ("World Bank 국가별 상위 출처", "https://api.worldbank.org/v2/sources/2/country/KOR;JPN;DEU;USA/series/SP.POP.TOTL/metadata?format=json"),
    ("World Bank 인구 추정 방법 설명", "https://blogs.worldbank.org/en/opendata/understanding-population-estimates-in-the-world-development-indi"),
    ("Eurostat 인구 통계 기준", "https://webgate.ec.europa.eu/eurostat/cache/metadata/en/demo_pop_esms.htm"),
]


def figures(d, folder):
    font = Path("C:/Windows/Fonts/malgun.ttf")
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams.update({"axes.unicode_minus": False, "font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.alpha": .17,
                         "figure.facecolor": "white", "savefig.facecolor": "white", "svg.fonttype": "none"})
    colors = ["#2459b5", "#d36b28"]
    for mode in ("levels", "gaps", "growth"):
        fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
        for ax, (c, name) in zip(axes.flat, d["scope"]["countries"].items()):
            pairs = [r for r in d["pairs"] if r["country"] == c]
            changes = [r for r in d["changes"] if r["country"] == c]
            if mode == "levels":
                for key, label, color, style in zip(["oecd", "worldbank"], ["OECD", "World Bank"], colors, ["-", "--"]):
                    ax.plot([r["year"] for r in pairs], [r[key]/1e6 for r in pairs], label=label,
                            color=color, linestyle=style, linewidth=2, marker="o" if key == "worldbank" else None, markersize=3)
                ax.set_ylabel("인구 (백만 명)")
            elif mode == "gaps":
                ax.plot([r["year"] for r in pairs], [r["difference_pct"] for r in pairs], color=colors[0], marker="o", markersize=4)
                caution = [r for r in pairs if not r["sensitivity_included"]]
                ax.scatter([r["year"] for r in caution], [r["difference_pct"] for r in caution], color=colors[1], marker="s", s=65, zorder=5, label="기준일·단절 주의")
                ax.axhline(0, color="#555", linewidth=.8)
                ax.set_ylim(-.2, .82)
                ax.set_ylabel("(OECD - WB) / WB (%)")
            else:
                for key, label, color, style in zip(["oecd_growth_pct", "worldbank_growth_pct"], ["OECD", "World Bank"], colors, ["-", "--"]):
                    ax.plot([r["year"] for r in changes], [r[key] for r in changes], label=label, color=color,
                            linestyle=style, linewidth=2, marker="o", markersize=3)
                ax.axhline(0, color="#555", linewidth=.8)
                ax.set_ylabel("전년 대비 인구 증가율 (%)")
            for r in pairs:
                if not r["sensitivity_included"]:
                    ax.axvspan(r["year"]-.3, r["year"]+.3, color="#e7a765", alpha=.12, zorder=0)
            ax.set_title(name, loc="left", weight="bold")
            ax.set_xticks([2010, 2014, 2018, 2022, 2024])
            ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        axes.flat[0].legend(loc="best", frameon=False)
        title = {"levels": "두 기관의 연간 총인구 추이", "gaps": "같은 국가·연도에도 수치가 다른가?", "growth": "어느 해에 인구가 늘거나 줄었다고 판단하는가?"}[mode]
        note = "백만 명 단위. 국가별 세로축 범위가 다름. 값이 같으면 두 선이 겹침." if mode == "levels" else "국가별 세로축 동일. World Bank는 비교 기준이며 참값을 뜻하지 않음." if mode == "gaps" else "연속 연도만 계산. 음영은 기준일·단절 주의 연도. 국가별 세로축 범위가 다름."
        fig.suptitle(title + "\n" + note, fontsize=14)
        fig.savefig(folder / f"{mode}.png", dpi=155)
        fig.savefig(folder / f"{mode}.svg")
        plt.close(fig)


def markdown(d):
    qa = d["qa"]
    out = ["# 실제 관측값 비교: OECD와 World Bank 총인구", "",
           "서버 카탈로그에서 후보를 골라 공식 API의 실제 관측값까지 내려가 비교했다. **한국·미국은 15년치가 모두 같았고, 일본·독일은 일부 차이가 있었다. 독일 2022·2023년은 증가·감소 방향도 달랐다.**", "",
           "범위: 한국·일본·독일·미국, 2010~2024년, 연간 총인구. 각 기관 60개, 총 120개 관측값을 60쌍으로 연결했다. 이 결과는 두 국제 포털의 한 지표에 대한 사례 분석이며 전체 포털 품질 순위가 아니다.", "",
           "## 목적과 선정 이유", "",
           "같은 개념으로 연결한 두 자료가 실제로 얼마나 같은지, 서로 대체해서 써도 되는지 검토할 근거를 만든다. 사용자는 현재 확보 가능한 후보 중 비교 조건이 가장 맞는 주제를 요청했다. 서버에 등록된 인구·고용 후보 가운데 총인구는 국가·연도·총성별·총연령·명 단위로 조건을 맞출 수 있어 선정했다. 전 주제·전 포털의 최적성을 증명한 선택은 아니다.", "",
           "서버 DB의 원래 자료는 등록정보다. 그 안의 OECD 접근 경로와 World Bank WDI 식별자를 출발점으로 이번에 공식 관측값을 별도로 내려받았다. 로컬의 임의 샘플값은 사용하지 않았다.", "",
           "## 과정", ""]
    for stage in d["process"]:
        out.append(f"{stage['step']}. **{stage['title']} — {stage['status']}**: {stage['detail']} [근거]({stage['evidence']})")
    out += ["", "## 실제 비교 결과", "",
            "차이율 = 100 × (OECD − World Bank) / World Bank. 아래 평균은 15개 연도별 절대 차이율의 평균이다. World Bank는 계산의 분모이며 참값으로 지정한 것은 아니다.", "",
            "| 국가 | 쌍 수 | 평균 절대 차이 (명) | 평균 절대 차이율 | 최대 절대 차이율 | 완전히 같은 연도 |",
            "|---|---:|---:|---:|---:|---:|"]
    for s in d["country_summaries"].values():
        a=s["all"]
        out.append(f"| {s['country_name']} | {a['n']} | {a['mae_persons']:,.1f} | {a['mean_absolute_gap_pct']:.6f}% | {a['max_absolute_gap_pct']:.6f}% | {a['exact_equal_pairs']} |")
    out += ["", "한국·미국의 수치 일치는 이 수집 시점과 선택 범위에서 확인한 결과다. World Bank는 한국 자료의 상위 출처로 KOSIS, 미국은 U.S. Census Bureau를 명시한다. OECD 설명도 국가 통계 계열을 가리키므로 상위 원천이 겹칠 가능성이 있다. OECD의 국가별 세부 출처·판본까지 같다는 사실은 확정하지 않았다. 따라서 서로 독립된 두 조사로 정확성이 검증됐다고 해석하지 않는다.", "",
            "### 수치 차이가 분석 결론을 바꾸는 사례", "",
            "| 독일 | OECD 인구 | World Bank 인구 | OECD 전년 증감 | World Bank 전년 증감 |",
            "|---|---:|---:|---:|---:|"]
    for y in (2022, 2023):
        p = next(p for p in d["pairs"] if p["country"] == "DEU" and p["year"] == y)
        c = next(c for c in d["changes"] if c["country"] == "DEU" and c["year"] == y)
        out.append(f"| {y} | {p['oecd']:,} | {p['worldbank']:,} | {c['oecd_change']:+,} | {c['worldbank_change']:+,} |")
    out += ["", "2022년 차이는 620,174명(약 0.746%)이다. 두 해 모두 World Bank 원자료에 통계 계열 단절 각주가 있다. 기준 변경과 개정 판본 차이를 조사해야 할 근거이며, 어느 기관이 틀렸는지나 차이의 정확한 원인이 입증된 것은 아니다.", "",
            "## QA와 주의 항목 제외 비교", "",
            f"요청 범위에서 양쪽 모두 60/60값 존재, 중복 키 0개, 미연결 0쌍이다. OECD 상태 A(일반 값)는 60건이지만 국가별 설명의 예외를 없애주지 않는다. World Bank의 빈 상태값을 정상 검증 완료로 간주하지 않았다. 기준일·단절 항목은 {qa['sensitivity_excluded_pairs']}쌍을 보수적으로 제외하여 {qa['sensitivity_pair_count']}쌍을 재계산했다. 원자료는 삭제하지 않았다.", "",
            "- 제외: 일본 2024년(10월 추정치 안내), 독일 2011·2022·2023년(계열 단절), 독일 2024년(1월 1일 추정치를 바탕으로 산출). 독일 2023년에는 두 종류의 주의가 겹친다.",
            "- 한국 2021~2024년의 새 추정치 반영은 개정 안내로 보존했다. 개정됐다는 이유만으로 제외하지 않았다.",
            "- 연간 변화 비교는 바로 전년 자료가 있는 경우에만 계산한다. 제외 후에는 양 끝 연도가 모두 남은 구간만 사용한다. 빠진 연도를 건너뛰어 1년 변화로 취급하지 않는다.", "",
            "| 국가 | 전체 평균 절대 차이율 | 주의 항목 제외 후 | 남은 연도 수 | 남은 연간 변화 구간 |",
            "|---|---:|---:|---:|---:|"]
    for s in d["country_summaries"].values():
        a,b=s['all'],s['sensitivity']
        out.append(f"| {s['country_name']} | {a['mean_absolute_gap_pct']:.6f}% | {b['mean_absolute_gap_pct']:.6f}% | {b['n']} | {b['change_n']} |")
    out += ["", "독일의 차이가 주의 구간에 집중됨을 확인했다. 주의 구간을 제외해 수치가 가까워졌다는 이유로 해당 연도를 잘못된 데이터로 판정하지 않는다. 허용 오차나 자동 승인 기준도 이번에 임의로 만들지 않았다.", "",
            "## 상관계수의 쓰임", "",
            "국가별 인구 수준 상관계수와 연간 증감 상관계수를 보조 진단으로 계산했다. 독일은 수준 r≈0.992, 증감 r≈0.900이지만 두 해에는 증감 방향이 다르다. 상관계수가 높아도 값이 같거나 서로 대체 가능하다는 뜻이 아니다. 시계열의 자기상관을 고려한 모형·인과 추론·p값 검정은 수행하지 않았다.", "",
            "## 온톨로지에서 네가 검토할 부분", "",
            "1. 두 지표가 ‘연간 국가 총인구’를 측정한다는 의미 연결의 정의·근거를 확인한다.",
            "2. 국가 코드·연도·단위·기준일·개정 판본이 맞는 조건을 관계에 붙인다.",
            "3. 실제 수치가 다른 구간은 출처의 각주와 국가 통계 원본을 확인해 비교 가능 범위를 좁히거나 보류한다.",
            "4. 검토자와 판단 근거를 기록한 뒤 조건부 비교 관계를 승인한다. 이번 결과만으로 sameAs·인과관계를 승인하지 않는다.", "",
            "검토안은 [relationship-review.json](relationship-review.json)에 작성했다. model.json과 서버 DB의 확정 관계는 수정하지 않았다.", "",
            "## 이번에 채택하지 않은 후보", "",
            "- KOSIS 주민등록인구: 주민등록 기준과 연간 총 거주인구 추정 기준이 자동으로 같지 않다. 직접 관측값 다운로드·수치 비교는 이번 범위에 포함하지 않았다.",
            "- Eurostat demo_pjan: 1월 1일 기준으로 연중 추정치와 바로 일치시키지 않았다.",
            "- Eurostat demo_gind: 세부 지표·단위 확인이 더 필요하여 다음 후보로 남겼다. 접속 실패로 분류하지 않았다.",
            "- KOSIS 실업률: 연령·구직 기간·계절조정 등의 조건 매칭을 별도로 해야 하므로 이번 첫 사례에서는 보류했다.", "",
            "## 근거와 재현", "",
            "[원자료 결합표](paired-observations.json), [정규화 관측값](normalized-observations.json), [출처별 QA](qa.json), [전체 결과](result.json), [분석 계획](analysis-plan.json). 요청 URL·시각·HTTP 응답·SHA-256은 raw 폴더의 receipt.json에 저장했다. 내려받기 성공은 재배포 허가나 품질 승인을 뜻하지 않는다. World Bank 메타데이터에는 CC BY-4.0 표기가 있으며 OECD를 포함한 상위 자료의 조건은 공개 재배포 단계에서 별도 확인할 항목이다.", ""]
    out.extend(f"- [{label}]({url})" for label,url in SOURCES)
    return "\n".join(out)+"\n"


def main(folder):
    d=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    figures(d, folder)
    (folder/'REPORT.md').write_text(markdown(d),encoding='utf-8')
    template=(ROOT/'observation_comparison.template.html').read_text(encoding='utf-8')
    template=template.replace('__DATA__',json.dumps(d,ensure_ascii=False).replace('<','\\u003c'))
    for mode in ('levels','gaps','growth'):
        template=template.replace(f'__{mode.upper()}__','data:image/png;base64,'+base64.b64encode((folder/f'{mode}.png').read_bytes()).decode())
    links=''.join(f'<li><a href="{escape(url,quote=True)}" target="_blank" rel="noopener">{escape(label)}</a></li>' for label,url in SOURCES)
    template=template.replace('__SOURCES__',links)
    (folder/'index.html').write_text(template,encoding='utf-8')
    print(json.dumps({'html':str(folder/'index.html'),'figures':3,'pairs':len(d['pairs'])}))


if __name__=='__main__':
    main(Path(sys.argv[1] if len(sys.argv)>1 else 'analysis/observation-comparison/20260915'))
