# 공공데이터 관측값 비교

[실제 수치와 과정 보기](20260915/index.html) · [설명 보고서](20260915/REPORT.md)

서버 카탈로그에 등록된 공식 접근 경로를 출발점으로 OECD와 World Bank의
국가별 연간 총인구를 확보했다. 2010~2024년 한국·일본·독일·미국 각 60개,
총 120개 관측값을 국가·연도로 60쌍 연결했다. 전체 포털 등록정보 분석에서
실제 관측값 분석으로 내려간 첫 사례다. 두 국제 포털의 지표 비교이며 국내외
전체 포털의 원자료를 전수 비교한 결과는 아니다.

서버 데이터베이스에는 쓰지 않는다. 수치 분석 결과는 관계 검토안으로 저장하며
사람의 승인은 따로 기록해야 한다. 기준일·단절 주의 항목과 전체 비교 결과를
함께 보존한다. 차이가 작은 해만 임의로 선택하거나 결측을 보간하지 않는다.

## 파일과 과정

- `server-catalog-selection.json`: 서버에서 읽은 후보 6개와 원래 식별자.
- `analysis-plan.json`: 숫자 차이 계산 전에 정한 주제·국가·기간.
- `raw/`: 공식 API 원응답, OECD 국가 설명표, 각 요청의 시각·헤더·SHA-256 기록.
- `oecd-country-metadata-extract.json`: OECD 설명표에서 읽은 행·셀 위치. 원본은 읽기 전용으로 유지.
- `normalized-observations.json`: 원값·원단위·상태를 보존한 명 단위 관측값.
- `paired-observations.json`: 국가·연도별 1:1 결합, 차이, 주의 항목.
- `qa.json`, `result.json`: 출처별 검사 결과와 전체/주의 항목 제외 통계.
- `process.json`, `relationship-review.json`: 단계별 증거와 승인 대기 관계 검토안.
- `index.html`: 네트워크 없이 차트·과정·국가 필터를 사용할 수 있는 보고서.
- `levels`, `gaps`, `growth`의 PNG·SVG: 공유·문서 삽입용 분석 그림.

HTML 안에 데이터와 이미지를 넣었다. HTML만 전달하면 핵심 결과를 볼 수 있고,
근거 링크까지 전달하려면 날짜 폴더 전체를 전달한다.

## 재현

수치 분석은 Python 표준 라이브러리만 사용하며 이미 저장된 원응답을 읽는다.

```powershell
python scripts/analyze_observation_comparison.py analysis/observation-comparison/20260915
```

그림 생성은 matplotlib가 필요하다. 저장소 루트에서 별도의 가상환경에
의존성을 설치한다. Python 3.12 이상과 Node.js 22 이상을 사용한다.

```bash
python -m pip install -r requirements.txt
python scripts/render_observation_comparison.py
python scripts/test_observation_comparison.py
node scripts/check_observation_report.mjs
```

openpyxl은 공식 설명표를 읽고 추출 내용을 대조하는 검증에만 사용한다.
그래프를 다시 생성하는 환경에는 한글 글꼴이 필요하다. 포함된 PNG·SVG·HTML은
다운로드한 그대로 열 수 있다.

화면 코드의 국가 필터·주의 항목 필터·JSON 내보내기·근거 링크는
`scripts/check_observation_report.mjs`로 오프라인 검사한다. 그림 3종은 PNG로
확인했다. 브라우저 보안 정책이 로컬 file URL 방문을 거절해 실제 브라우저
레이아웃은 자동 검증하지 못했다. 검증 범위는 `ui-validation.json`에 명시했다.

원응답을 다시 받으려면 `scripts/fetch_observation_evidence.py URL 새출력경로`를
사용한다. 기존 바이트를 덮어쓰지 않고, 같은 경로가 있으면 URL과 해시를 확인한다.
다른 날짜의 수치를 섞지 않도록 새 날짜 폴더에서 수집하고 국가 설명표·메타데이터도
다시 검토해야 한다. 이 스크립트는 현 스냅샷의 명세에 맞춘 첫 분석이다.
