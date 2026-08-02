# MarketFlow

코스피·코스닥 전 종목의 **기간별 신고가 돌파 가능성**을 매 거래일 아침 6시(KST)에
갱신해 정적 사이트로 배포합니다.

**→ https://yejooni.github.io/marketflow**

## 무엇을 하는가

- 코스피·코스닥 **보통주 약 2,530종목**의 1년치 일봉(시·고·저·종·거래량·추정 거래대금) 수집
- 종목별 **네이버 테마** 최대 2개 매핑 (약 266개 테마)
- **1·3·6·12개월** 기간별 신고가 대비 위치, 추세 품질, 상대강도, 거래대금 증가율 산출
- 오늘 장중 신고가를 넘길 **돌파확률**을 과거 빈도로 추정 (백테스트 검증: ECE 0.70%p, AUC 0.913)
- 주도주 후보 랭킹 · 테마별 보기 · 종목 검색 · 키움 HTS 스타일 차트

## 구조

```
pipeline/
  config.py      기간·임계값 등 설정
  universe.py    KRX 상장목록 → 보통주 필터 (ETF/ETN/우선주/스팩 제외)
  prices.py      네이버 siseJson 일봉 수집 (스레드 8개, 전 종목 ~3분)
  themes.py      네이버 테마 스크레이핑
  analyze.py     지표·돌파확률·주도주 점수
  backtest.py    확률 모델 보정 검증
  build_site.py  web/data/*.json 생성
  run.py         오케스트레이터
web/             정적 사이트 (의존성 없는 순수 JS/캔버스)
docs/            모델 검증 문서
```

## 로컬 실행

```bash
pip install -r requirements.txt

python -m pipeline.run                  # 전 종목
python -m pipeline.run --limit 300      # 빠른 개발용
python -m pipeline.backtest             # 확률 모델 검증

cd web && python -m http.server 8765    # http://localhost:8765
```

## 배포

`.github/workflows/daily.yml` 이 매 거래일 21:00 UTC(= 06:00 KST)에 실행됩니다.
생성 데이터(~26MB)는 **커밋하지 않고** Pages 아티팩트로 바로 올리므로
저장소 히스토리가 커지지 않습니다. 수동 실행은 Actions 탭의 *Run workflow*.

## 데이터 주의사항

- **거래대금은 추정치**입니다. 일별 원본이 공개되지 않아 `거래량 × (시+고+저+종)/4`로
  재구성했으며 KRX 실제값 대비 중앙값 오차 0.70%로 검증했습니다.
- **돌파확률은 예측이 아니라 과거 빈도**입니다. 자세한 내용과 한계는
  [docs/model-validation.md](docs/model-validation.md) 및 사이트의 방법론 페이지 참조.
- 투자 판단의 책임은 이용자에게 있습니다.
