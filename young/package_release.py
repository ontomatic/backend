"""스킬·실행 프롬프트·검증 코드만 재현 가능한 ZIP으로 묶는다."""
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEST = ROOT.parent / "품질관리_D안_프롬프트_스킬_확정본.zip"
INCLUDE = [
    "SKILL.md",
    "새_실행_프롬프트.md",
    "package_release.py",
    "README.md",
    "requirements.txt",
    ".gitignore",
    "references/qc_contract.md",
    "references/d_style.md",
    "examples/validate_output.py",
    "validation_two_sources/XNO-8080R_실행_프롬프트.md",
    "validation_two_sources/HCD-6080R_실행_프롬프트.md",
    "validation_two_sources/검증_결과.md",
    "validation_two_sources/validation_evidence.json",
    "validation_two_sources/validation_report.json",
    "validation_two_sources/build_validation.py",
    "validation_two_sources/make_prompts.py",
    "validation_two_sources/check_content.py",
    "validation_two_sources/runtime/generate_data.py",
    "validation_two_sources/runtime/render_files.py",
    "validation_two_sources/runtime/catalog.json",
    "validation_two_sources/runtime/data.json",
    "validation_two_sources/runtime/schema.json",
]


def main():
    manifest = {}
    with zipfile.ZipFile(DEST, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in INCLUDE:
            path = ROOT / relative
            data = path.read_bytes()
            manifest[relative] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            archive.writestr(f"qc-d-style-prompt-builder/{relative}", data)
        archive.writestr("qc-d-style-prompt-builder/MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"{DEST} ({DEST.stat().st_size} bytes, {len(INCLUDE)} files + manifest)")


if __name__ == "__main__":
    main()
