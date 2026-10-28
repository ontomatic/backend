"""검증에 사용한 두 원본의 근거를 새 스킬 프롬프트에 주입한다."""
from pathlib import Path
from build_validation import ROOT, SOURCES

template = (ROOT.parent / "새_실행_프롬프트.md").read_text()
for source in SOURCES:
    text = template
    replacements = {
        "{{원본 파일 절대경로 또는 Drive 링크 목록}}": source["source_url"],
        "{{제품군명 -> 해당 원본 파일/모델명. 지정이 없으면 원본을 검토해 제안하고 확인 필요 항목을 표시}}": f'{source["category"]} -> {source["model"]} ({source["source_url"]})',
        "{{승인된 D안 PDF 경로 또는 접근 가능한 링크}}": str(ROOT.parent / "references/d_style.md") + " (D안 출력 계약; 원본 승인 PDF가 있는 환경에서는 함께 대조)",
        "{{절대경로}}": str(ROOT / "result_D"),
        "{{요청된 경우에만 폴더 링크. 없으면 업로드하지 않음}}": "이번 검증에서는 업로드하지 않음",
        "{{시안 1개 / 전체 제품군}}": "이 모델 1개 제품군의 10종 × 4형식 검증",
        "{{LOT·문서별 행 수, 기준일, seed; 미지정이면 목적에 맞는 값을 정해 명시}}": "FQC 7 LOT, IQC 4 LOT, 나머지 각 8행, 기준일 2026-10-27, 재현용 seed는 모델별 고정값",
    }
    for before, after in replacements.items():
        assert before in text, before
        text = text.replace(before, after)
    text = text.replace("아래 `{{...}}`를 실제 입력으로 채운 뒤 실행한다. 원본 내용을 확인하지 못한 칸은 추정으로 메우지 말고 `확인 필요` 상태로 둔다.", "이 프롬프트는 선택한 원본 파일의 확인된 사양으로 입력값을 채운 검증용 실행본이다.")
    facts = ["\n## 이 입력에서 확인한 사양 근거", "", f"원본: {source['source_url']}", ""]
    facts += [f"- {x['name']}: {x['value']} — {x['section']} {x['page']}쪽" if x["page"] else f"- {x['name']}: {x['value']} — 합성 검사 기준, vendor 사양 아님" for x in source["items"]]
    facts += ["", "상충·조건 구분:"] + [f"- {x}" for x in source["conflicts"]]
    facts += ["", "제외 항목:"] + [f"- {x}" for x in source["omissions"]]
    path = ROOT / f"{source['model']}_실행_프롬프트.md"
    path.write_text(text + "\n".join(facts) + "\n")
    print(path)
