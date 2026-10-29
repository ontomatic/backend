# 데이터 계약

루트에 manifest.json을 두고 `03_정답및평가자료`에 gold·evaluation·sources를 둔다. scripts는 루트 또는 메타 폴더를 받는다.

## 제품

```json
{"product_id":"P001","identity_id":"I001","family_id":"F001","source_id":"S01","synthetic":true,"variant_type":"base","class_path":["Product","아날로그카메라","돔"],"class_id":"아날로그카메라/돔","attributes":{"model":"AV-01X-400","product_code":"SYN-2026-0001","power_w":4.2}}
```

같은 identity의 기술 attributes는 name/model/product_code를 제외하고 같아야 한다. 같은 family의 다른 identity는 의미 있는 기술 차이를 가져야 한다. 변형에는 parent_product_id를 둔다. 출처 근거와 합성 필드 생성 이력을 기록한다.

## Manifest

document_id, product_id, group(1~5), department, source_id와 files를 가진 객체의 배열이다. files는 pdf/xlsx/docx/csv를 루트 상대 경로로 연결한다. 경로를 명령으로 실행하지 않는다. `..`로 루트를 벗어나거나 같은 파일을 여러 형식으로 연결하지 않는다.

## 문서 정답

```json
{"document_id":"P001-D1","product_id":"P001","class_id":"아날로그카메라/돔","document_group":1,"omitted_fields":[],"mutations":[],"fields":{"power_w":{"label":"최대 소비전력","section":"전원","value":4200,"unit":"mW","value_norm":4.2,"unit_norm":"W","pdf_page":1,"quote":"4200 mW","xlsx_cell":"C18","xlsx_mode":"value","csv_row":15,"csv_column":"F"}}}
```

누락은 필드를 삭제하는 대신 value/value_norm/unit/unit_norm/quote/위치를 모두 null로 둔다. 문서값은 실제 기재값이고 제품 기준과의 충돌은 별도로 기록한다. 숫자·문자열·boolean을 구분한다. unit_norm은 단위 없는 명시된 필드에서는 빈 문자열, 누락에서는 null이다.

레코드는 `bom.0.quantity`, `inspections.0.measured`, `releases.0.version`, `doc.revision`처럼 구분한다. scope를 product_spec/business_record/document_control로 나눌 수 있다. 전체 필드 점수와 사양만의 점수를 구분한다.

CSV v2는 `문서번호,모델명,구분,기록번호,항목,값,단위,비고`이며 값 F열·단위 G열이다. XLSX narrative 모드는 한 셀의 문장에서 값을 추출한다. PDF 페이지는 실제 최종 페이지이고 Word 페이지는 고정하지 않는다. 표의 값 셀만 quote로 쓰면 label·section을 같이 보존한다.

## 단위

| 원단위 | 정규화 | 배수 |
|---|---|---:|
| cm | mm | 10 |
| mm | mm | 1 |
| mW | W | 0.001 |
| W | W | 1 |
| g | g | 1 |
| g0 | g0 | 1 |

g는 질량, g0는 가속도다. 가로/세로 px와 유효화소 총량은 다른 속성이다. 지원 여부는 true/false, 누락은 null이다.

## 쌍과 충돌

gold/pairs.json은 product_a/product_b/label 배열이다. label은 duplicate/similar/unrelated다. 자기 쌍·역순 중복을 제외한다. unrelated가 이번 실험에서 어떤 의미인지 명시한다.

gold/conflicts.json은 product_id/key/document_a/document_b/value_a/value_b를 보존한다. 단위 정규화 후에도 실제로 다른지 확인한다. 단위만 다른 동일값은 충돌이 아니다.

evaluation/splits.json의 products는 product_id→train/dev/test다. 같은 family는 같은 split에 둔다. 쌍은 양쪽이 모두 선택된 split인 경우만 평가한다.

## 예측

```json
{"documents":{"P001-D1":{"class_id":"아날로그카메라/돔","fields":{"power_w":{"value_norm":4.2,"unit_norm":"W"}}}},"pairs":[],"conflicts":[]}
```

정규화 값과 단위가 함께 맞아야 정답이다. 누락도 명시적 null 출력이 있어야 맞다. 문서 누락은 전체 필드 오답이다. 숫자 허용오차는 상대·절대 1e-6이다. 골드에 없는 필드·누락 필드의 non-null을 환각으로 집계한다. 명시된 필드의 잘못된 값은 필드 오답이며 이 환각 정의와 다르다.

oracle 정답 예측은 코드 자체 점검이다. 100%가 실제 모델 성능은 아니다. 현재 scorer는 인용·위치 정확도를 채점하지 않는다. 형식별 예측 JSON을 따로 만든다.
