"""이미지 라이브러리(library/catalog.yml)를 OpenAI 이미지 API로 미리 생성한다.

- library/images/<id>.(png|jpg|jpeg|webp) 가 이미 있는 항목은 건너뜀 (직접 올린 이미지 보존)
- 인자: --only id1,id2  특정 항목만 / --regenerate  있어도 다시 생성 / --dry-run  목록만 출력
- 실패(콘텐츠 정책 거절 등)한 항목은 로그만 남기고 계속 진행, 마지막에 실패 목록 출력
"""
import argparse
import base64
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "library" / "catalog.yml"
OUT_DIR = ROOT / "library" / "images"

MODEL = os.environ.get("OPENAI_IMAGE_MODEL") or "gpt-image-2.5-flare"
SIZE = os.environ.get("OPENAI_IMAGE_SIZE") or "1536x864"  # 16:9
QUALITY = os.environ.get("OPENAI_IMAGE_QUALITY") or "medium"
STYLE = os.environ.get("IMAGE_STYLE_SUFFIX") or (
    "1980s cyberpunk illustration style, neon and rain, cinematic lighting, "
    "consistent painterly comic-book look, 16:9, no text, no logos, no watermark"
)


def load_catalog():
    items = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or []
    ids = [i["id"] for i in items]
    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        raise SystemExit(f"catalog.yml 에 중복 id: {sorted(dup)}")
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="쉼표로 구분한 id 목록")
    ap.add_argument("--regenerate", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    items = [i for i in load_catalog() if not only or i["id"] in only]
    if only - {i["id"] for i in items}:
        print(f"[library] 카탈로그에 없는 id: {sorted(only - {i['id'] for i in items})}")
    def exists(i):
        return any((OUT_DIR / f"{i['id']}{e}").exists() for e in (".png", ".jpg", ".jpeg", ".webp"))
    todo = [i for i in items if args.regenerate or not exists(i)]
    print(f"[library] 생성 대상 {len(todo)}개 / 카탈로그 {len(items)}개 (model={MODEL}, size={SIZE}, quality={QUALITY})")
    if args.dry_run:
        for i in todo:
            print(f"  - {i['id']}: {i.get('title', '')}")
        return 0
    if not todo:
        return 0
    if not os.environ.get("OPENAI_API_KEY"):
        print("[library] OPENAI_API_KEY 없음 – 중단")
        return 1

    from openai import OpenAI

    client = OpenAI()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failed = []
    for i in todo:
        try:
            r = client.images.generate(model=MODEL, prompt=f"{i['prompt'].strip()}, {STYLE}",
                                       size=SIZE, quality=QUALITY)
            (OUT_DIR / f"{i['id']}.png").write_bytes(base64.b64decode(r.data[0].b64_json))
            print(f"[library] ✔ {i['id']}")
        except Exception as e:
            failed.append(i["id"])
            print(f"[library] ✘ {i['id']}: {e}")
    print(f"[library] 완료 – 성공 {len(todo) - len(failed)}, 실패 {len(failed)} {failed if failed else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
