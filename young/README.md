# 품질관리 D안 프롬프트 스킬

제품 데이터시트를 읽고, 품질관리 문서 10종을 제품군별로 분리해 `.hwpx`, `.docx`, `.xlsx`, `.pdf`로 만들도록 지시하는 **독립형 프롬프트를 작성하는 스킬**입니다.

## 실제 사용

1. `SKILL.md`를 Codex 스킬로 사용하거나, `새_실행_프롬프트.md` 한 파일을 복사합니다.
2. 프롬프트의 `{{...}}` 입력 칸을 새 원본 파일, 제품군, 출력 위치로 채웁니다.
3. 원본 사양은 파일의 페이지·섹션까지 확인해 넣습니다. 확인되지 않은 값은 추정하지 않습니다.
4. 생성 결과는 `examples/validate_output.py`로 구조·XLSX 헤더를 확인하고, PDF/DOCX의 한글 렌더링 및 HWPX 실제 열기를 별도로 확인합니다.

`새_실행_프롬프트.md`는 10종 스키마와 결함 규칙을 자체 포함합니다. `references/`는 스킬 관리와 검증을 위한 분리된 규칙 사본입니다.

## 코드 구성

- `examples/validate_output.py`: 결과 폴더와 XLSX 헤더 구조 검사.
- `validation_two_sources/`: 미사용 원본 XNO-8080R·HCD-6080R에 적용한 프롬프트, 근거, 검증 결과, 재현 코드.
- `validation_two_sources/runtime/`: 검증용 합성 데이터·문서 생성 코드. 범용 생산용 생성기는 아닙니다.
- `package_release.py`: 필요한 원본 파일만 ZIP으로 묶고 SHA-256 목록을 기록합니다.

검증용 생성 결과와 QA 이미지는 `.gitignore` 및 ZIP 대상에서 제외합니다. 검증 결과와 제한사항은 `validation_two_sources/검증_결과.md`를 보세요.

검증 예시에는 실제 공유 Drive 파일 링크가 들어 있습니다. 공개 GitHub 저장소에 올릴 계획이면 링크 공개 범위를 확인하고 필요하면 예시 링크를 교체하세요.

## 재현

Python 의존성은 `requirements.txt`에 있습니다. macOS에서 원본 테스트의 문서 렌더링 코드가 사용한 한글 글꼴 경로가 필요합니다.

```bash
python validation_two_sources/make_prompts.py
python validation_two_sources/build_validation.py
python examples/validate_output.py validation_two_sources/result_D
python validation_two_sources/check_content.py
```

현재 검증은 구조·사양 대조를 통과했으나, DOCX 한글 시각 검사와 HWPX 한컴오피스 직접 열기 검사가 완료되지 않았습니다. 네 형식의 완성품 납품 여부는 별도 검증 결과에 따라 결정합니다.
