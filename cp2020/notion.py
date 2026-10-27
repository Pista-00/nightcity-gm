"""Notion 기록 – 추가만 한다(append-only). 기존 블록은 절대 수정·삭제하지 않는다.

Notion 구조 (캠페인마다)
  [사용자가 고른 상위 페이지]
    └ 🎲 <캠페인 이름>
        ├ 🧬 <캐릭터 핸들>        캐릭터 시트 (수정 시 "🔄 업데이트" 로 덧붙임)
        └ 📜 <N회차 – 제목>       세션 기록 + 플레이 중 보낸 장면(이미지 1장 + 서술)

룰북·이미지 라이브러리 전체·AI 대화 기록·GM 메모는 올리지 않는다.
"""
import re
import time
from datetime import datetime
from pathlib import Path

import requests

from . import chargen, credentials, store

API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


class NotionError(RuntimeError):
    pass


def parse_page_id(value: str) -> str:
    """페이지 URL 또는 ID(대시 포함 가능)에서 32자리 ID 추출."""
    value = (value or "").strip().split("?")[0].split("#")[0].rstrip("/")
    last = value.split("/")[-1]
    uuid = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", last)
    cand = uuid.group(0).replace("-", "") if uuid else last[-32:]
    if not re.fullmatch(r"[0-9a-fA-F]{32}", cand):
        raise NotionError("Notion 페이지 ID(32자리)를 찾지 못했습니다. 페이지 URL을 그대로 붙여넣으세요.")
    return cand.lower()


# ---------------------------------------------------------------- HTTP
def _headers(json_body=True):
    token = credentials.get("NOTION_TOKEN")
    if not token:
        raise NotionError("Notion 토큰이 없습니다. 설정에서 입력하세요.")
    h = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _req(method, url, **kw):
    for attempt in range(5):
        r = requests.request(method, url, timeout=60, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
            continue
        if not r.ok:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            raise NotionError(f"Notion {r.status_code}: {msg[:300]}")
        return r.json()
    raise NotionError("Notion 요청 재시도 초과")


def create_page(parent_id, title, icon=None):
    body = {"parent": {"page_id": parent_id},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title[:200]}}]}}}
    if icon:
        body["icon"] = {"type": "emoji", "emoji": icon}
    return _req("POST", f"{API}/pages", headers=_headers(), json=body)["id"]


def append_blocks(block_id, blocks):
    for i in range(0, len(blocks), 100):
        _req("PATCH", f"{API}/blocks/{block_id}/children", headers=_headers(), json={"children": blocks[i:i + 100]})


def upload_image(path: Path):
    up = _req("POST", f"{API}/file_uploads", headers=_headers(), json={})
    with open(path, "rb") as f:
        _req("POST", f"{API}/file_uploads/{up['id']}/send", headers=_headers(json_body=False),
             files={"file": (path.name, f, store.IMAGE_EXTS.get(path.suffix.lower(), "image/png"))})
    return {"object": "block", "type": "image", "image": {"type": "file_upload", "file_upload": {"id": up["id"]}}}


def check(page: str) -> dict:
    """토큰·페이지 접근 확인. {ok, title, error}"""
    try:
        pid = parse_page_id(page)
        data = _req("GET", f"{API}/pages/{pid}", headers=_headers())
        title = "".join(t.get("plain_text", "") for p in data.get("properties", {}).values()
                        if p.get("type") == "title" for t in p["title"])
        return {"ok": True, "title": title or "(제목 없음)", "page_id": pid}
    except Exception as e:
        hint = ""
        if "404" in str(e) or "Could not find" in str(e):
            hint = " – 페이지 ··· → Connections 에 연결을 추가했는지 확인하세요."
        elif "401" in str(e):
            hint = " – 토큰이 올바른지 확인하세요."
        return {"ok": False, "error": f"{e}{hint}"}


# ---------------------------------------------------------------- Markdown → blocks
def rich(text):
    parts = []
    for tok in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not tok:
            continue
        ann = {}
        if tok.startswith("**") and tok.endswith("**"):
            tok, ann = tok[2:-2], {"bold": True}
        elif tok.startswith("`") and tok.endswith("`"):
            tok, ann = tok[1:-1], {"code": True}
        for i in range(0, len(tok), 1900):
            item = {"type": "text", "text": {"content": tok[i:i + 1900]}}
            if ann:
                item["annotations"] = ann
            parts.append(item)
    return parts or [{"type": "text", "text": {"content": ""}}]


def blk(kind, text):
    return {"object": "block", "type": kind, kind: {"rich_text": rich(text)}}


def divider():
    return {"object": "block", "type": "divider", "divider": {}}


def md_to_blocks(md):
    blocks, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("|"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\|[\s:\-|]+\|$", lines[i].strip()):
                    buf.append(lines[i].strip())
                i += 1
            i -= 1
            blocks.append({"object": "block", "type": "code",
                           "code": {"rich_text": rich("\n".join(buf)), "language": "plain text"}})
        elif s in ("---", "***"):
            blocks.append(divider())
        elif s.startswith("### "):
            blocks.append(blk("heading_3", s[4:]))
        elif s.startswith("## "):
            blocks.append(blk("heading_2", s[3:]))
        elif s.startswith("# "):
            blocks.append(blk("heading_1", s[2:]))
        elif s.startswith("> "):
            blocks.append(blk("quote", s[2:]))
        elif re.match(r"^[-*] ", s):
            blocks.append(blk("bulleted_list_item", s[2:]))
        elif re.match(r"^\d+[.)] ", s):
            blocks.append(blk("numbered_list_item", re.sub(r"^\d+[.)] ", "", s)))
        elif s:
            blocks.append(blk("paragraph", s))
        i += 1
    return blocks


# ---------------------------------------------------------------- 캠페인 페이지
def ready(c: store.Campaign) -> bool:
    return bool(credentials.get("NOTION_TOKEN") and c.meta.get("notion_page"))


def root_page(c: store.Campaign) -> str:
    st = c.notion_state
    parent = parse_page_id(c.meta.get("notion_page", ""))
    if st.get("root") and st.get("parent") == parent:
        return st["root"]
    st = {"parent": parent, "root": create_page(parent, f"🎲 {c.meta.get('name', c.id)}", "🌃"),
          "sessions": {}, "characters": {}, "log": []}
    c.save_notion_state(st)
    return st["root"]


def _delta_blocks(old: str, new: str, label="🔄 업데이트"):
    if new == old:
        return []
    if new.startswith(old):
        return md_to_blocks(new[len(old):])
    return [divider(), blk("heading_2", f"{label} ({datetime.now():%Y-%m-%d %H:%M})")] + md_to_blocks(new)


def sync_session(c: store.Campaign, session: Path) -> str:
    root = root_page(c)
    st = c.notion_state
    text = session.read_text(encoding="utf-8")
    rec = st["sessions"].get(session.name)
    if rec is None:
        title = next((l[2:] for l in text.splitlines() if l.startswith("# ")), session.stem)
        pid = create_page(root, title, "📜")
        append_blocks(pid, md_to_blocks(text))
        st["sessions"][session.name] = {"page_id": pid, "text": text}
    else:
        blocks = _delta_blocks(rec["text"], text)
        if blocks:
            append_blocks(rec["page_id"], blocks)
        rec["text"] = text
    c.save_notion_state(st)
    return st["sessions"][session.name]["page_id"]


def _log(c, **kw):
    st = c.notion_state
    st.setdefault("log", []).append({"time": store.now(), **kw})
    c.save_notion_state(st)


def send_scene(c: store.Campaign, scene: dict, session: Path) -> dict:
    page = sync_session(c, session)
    blocks = [divider(), blk("heading_2", f"🎬 {scene.get('id', '')} · {scene.get('title', '')}  ({datetime.now():%H:%M})")]
    meta = " · ".join(x for x in (scene.get("location"), scene.get("time")) if x)
    img = store.library_image(scene.get("image", ""))
    if img:
        blocks.append(upload_image(img))
    if meta:
        blocks.append(blk("paragraph", f"**{meta}**"))
    blocks += [blk("quote", l) for l in str(scene.get("narration", "")).splitlines() if l.strip()]
    append_blocks(page, blocks)
    _log(c, kind="scene", session=session.name, scene=scene.get("id"), image=scene.get("image"))
    return {"image": bool(img)}


def logged_upto(c: store.Campaign, session: Path) -> int:
    return int(c.notion_state.get("sessions", {}).get(session.name, {}).get("logged", 0))


def set_logged(c: store.Campaign, session: Path, n: int):
    st = c.notion_state
    rec = st.setdefault("sessions", {}).get(session.name)
    if rec is not None:
        rec["logged"] = n
        c.save_notion_state(st)


def log_progress(c: store.Campaign, session: Path, md: str):
    """진행 기록(행동·대화·판정·결과 요약)을 세션 페이지 끝에 추가."""
    page = sync_session(c, session)
    append_blocks(page, [blk("heading_3", f"📝 진행 기록  ({datetime.now():%H:%M})")] + md_to_blocks(md))
    _log(c, kind="progress", session=session.name)


def post_image(c: store.Campaign, image_id: str, caption: str, session: Path):
    img = store.library_image(image_id)
    if not img:
        raise NotionError(f"이미지 '{image_id}' 가 library/images 에 없습니다.")
    page = sync_session(c, session)
    append_blocks(page, [upload_image(img),
                         blk("quote", f"🖼 {caption or store.catalog_title(image_id)}  ({datetime.now():%H:%M})")])
    _log(c, kind="image", session=session.name, image=image_id)


def post_text(c: store.Campaign, session: Path, heading: str, md: str):
    page = sync_session(c, session)
    append_blocks(page, [divider(), blk("heading_2", heading)] + md_to_blocks(md))
    _log(c, kind="text", session=session.name, heading=heading)


def sync_character(c: store.Campaign, ch: dict) -> str:
    root = root_page(c)
    st = c.notion_state
    md = chargen.to_markdown(ch)
    rec = st["characters"].get(ch["id"])
    if rec is None:
        pid = create_page(root, f"{ch.get('handle', '')} – {ch.get('role', '')}", "🧬")
        append_blocks(pid, md_to_blocks(md))
        st["characters"][ch["id"]] = {"page_id": pid, "text": md}
    else:
        blocks = _delta_blocks(rec["text"], md, "🔄 시트 업데이트")
        if blocks:
            append_blocks(rec["page_id"], blocks)
        rec["text"] = md
    c.save_notion_state(st)
    return st["characters"][ch["id"]]["page_id"]
