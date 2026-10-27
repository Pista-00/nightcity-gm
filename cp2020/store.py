"""경로·설정·캠페인 데이터.

저장소(공통 도구)            : cp2020/, web/, rules/, library/, content/
로컬 전용(git 제외)          : .env.local(키), settings.json, campaigns/<id>/…

campaigns/<id>/
  campaign.json        이름, 플레이어, Notion 페이지, 진행 설정
  characters/<cid>.json
  sessions/NN-제목.md  세션 기록(플레이어 공개)
  scenes/S01-….yml     AI 가 연 장면
  transcripts/NN-….jsonl  AI 대화 기록(GM 메모 포함, 비공개)
  notion_state.json    Notion 페이지 id 등
"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CAMPAIGNS = ROOT / "campaigns"
SETTINGS = ROOT / "settings.json"
LIBRARY = ROOT / "library"
IMAGE_DIR = LIBRARY / "images"
CATALOG = LIBRARY / "catalog.yml"
CONTENT = ROOT / "content"
IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(text: str, fallback="item") -> str:
    s = re.sub(r"[^\w가-힣]+", "-", text or "").strip("-").lower()
    return s[:40] or fallback


def read_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- 전역 설정 (키 제외)
DEFAULT_SETTINGS = {"provider": "claude-code", "model": "sonnet", "rules": "index", "max_tokens": 2000,
                    "notion_mode": "always", "current_campaign": ""}


def settings() -> dict:
    return {**DEFAULT_SETTINGS, **(read_json(SETTINGS, {}) or {})}


def save_settings(**kw):
    s = settings()
    s.update(kw)
    write_json(SETTINGS, s)
    return s


# ---------------------------------------------------------------- 이미지 라이브러리
def catalog() -> list[dict]:
    if not CATALOG.exists():
        return []
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or []


def library_image(image_id: str):
    if not image_id or not re.fullmatch(r"[\w\-]+", image_id):
        return None
    for ext in IMAGE_EXTS:
        p = IMAGE_DIR / f"{image_id}{ext}"
        if p.exists():
            return p
    return None


def catalog_title(image_id: str) -> str:
    return next((i.get("title", image_id) for i in catalog() if i.get("id") == image_id), image_id)


# ---------------------------------------------------------------- 캠페인
class Campaign:
    def __init__(self, cid: str):
        if not re.fullmatch(r"[\w\-]+", cid or ""):
            raise ValueError("잘못된 캠페인 id")
        self.id = cid
        self.dir = CAMPAIGNS / cid
        if not (self.dir / "campaign.json").exists():
            raise FileNotFoundError(f"캠페인 없음: {cid}")

    # ---- 생성·목록
    @staticmethod
    def create(name: str, notion_page: str = "") -> "Campaign":
        base = slugify(name, "campaign")
        cid, n = base, 2
        while (CAMPAIGNS / cid).exists():
            cid, n = f"{base}-{n}", n + 1
        d = CAMPAIGNS / cid
        for sub in ("characters", "sessions", "scenes", "transcripts"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        write_json(d / "campaign.json", {
            "name": name, "created": now(), "players": [], "notion_page": notion_page,
            "stat_method": "cinematic", "stat_points": 75})
        c = Campaign(cid)
        c.new_session("세계관 소개 & 캐릭터 생성", number=0)
        return c

    @staticmethod
    def all() -> list[dict]:
        out = []
        if CAMPAIGNS.exists():
            for d in sorted(CAMPAIGNS.iterdir()):
                meta = read_json(d / "campaign.json")
                if meta:
                    out.append({"id": d.name, "name": meta.get("name", d.name), "created": meta.get("created")})
        return out

    # ---- 메타
    @property
    def meta(self) -> dict:
        return read_json(self.dir / "campaign.json", {})

    def update(self, **kw):
        m = self.meta
        m.update(kw)
        write_json(self.dir / "campaign.json", m)
        return m

    # ---- 캐릭터
    def characters(self) -> list[dict]:
        return [read_json(p) for p in sorted((self.dir / "characters").glob("*.json"))]

    def character(self, chid: str) -> dict | None:
        if not re.fullmatch(r"[\w\-]+", chid or ""):
            return None
        return read_json(self.dir / "characters" / f"{chid}.json")

    def save_character(self, ch: dict) -> dict:
        ch = dict(ch)
        if not re.fullmatch(r"[\w\-]+", str(ch.get("id") or "")):
            ch["id"] = uuid.uuid4().hex[:8]
        ch["updated"] = now()
        write_json(self.dir / "characters" / f"{ch['id']}.json", ch)
        return ch

    # ---- 작성 중인 캐릭터 (임시 저장, 규칙 검사 없음)
    @property
    def drafts(self) -> dict:
        return read_json(self.dir / "drafts.json", {}) or {}

    def save_draft(self, key: str, draft):
        d = self.drafts
        if draft is None:
            d.pop(key, None)
        else:
            d[key] = {**draft, "_saved": now()}
        write_json(self.dir / "drafts.json", d)

    def delete_character(self, chid: str):
        p = self.dir / "characters" / f"{chid}.json"
        if re.fullmatch(r"[\w\-]+", chid) and p.exists():
            p.unlink()

    # ---- 세션
    def sessions(self) -> list[Path]:
        return sorted((self.dir / "sessions").glob("*.md"))

    def session_path(self, name: str | None = None) -> Path | None:
        if name:
            p = self.dir / "sessions" / Path(name).name
            return p if p.exists() else None
        s = self.sessions()
        return s[-1] if s else None

    def new_session(self, title: str, number: int | None = None) -> Path:
        if number is None:
            nums = [int(m.group(1)) for p in self.sessions() if (m := re.match(r"(\d+)", p.name))]
            number = max(nums) + 1 if nums else 0
        p = self.dir / "sessions" / f"{number:02d}-{slugify(title, 'session')}.md"
        p.write_text(f"# {number}회차 – {title}\n\n**일시:** {datetime.now():%Y-%m-%d}\n\n## 진행 기록\n",
                     encoding="utf-8")
        return p

    def append_log(self, session: Path, text: str):
        content = session.read_text(encoding="utf-8")
        if "## 진행 기록" not in content:
            content += "\n## 진행 기록\n"
        session.write_text(content.rstrip("\n") + f"\n- {text}\n", encoding="utf-8")

    def transcript_path(self, session: Path) -> Path:
        return self.dir / "transcripts" / f"{session.stem}.jsonl"

    # ---- 장면
    def scenes(self) -> list[dict]:
        out = []
        for p in sorted((self.dir / "scenes").glob("S*.yml")):
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            d["_file"] = p.name
            out.append(d)
        return out

    def next_scene_id(self) -> str:
        nums = [int(m.group(1)) for p in (self.dir / "scenes").glob("S*.yml") if (m := re.match(r"S(\d+)", p.name))]
        return f"S{(max(nums) + 1) if nums else 1:02d}"

    def save_scene(self, attrs: dict, narration: str) -> dict:
        sid = attrs.get("id") or ""
        if not re.fullmatch(r"S\d+", sid) or list((self.dir / "scenes").glob(f"{sid}-*.yml")) \
                or (self.dir / "scenes" / f"{sid}.yml").exists():
            sid = self.next_scene_id()
        scene = {"id": sid, "title": attrs.get("title", ""), "location": attrs.get("location", ""),
                 "time": attrs.get("time", ""), "image": attrs.get("image", ""),
                 "narration": narration.strip() + "\n", "created": now()}
        slug = slugify(scene["title"], "")
        path = self.dir / "scenes" / f"{sid}{'-' + slug if slug else ''}.yml"
        path.write_text(yaml.safe_dump(scene, allow_unicode=True, sort_keys=False), encoding="utf-8")
        scene["_file"] = path.name
        return scene

    def scene(self, sid: str) -> dict | None:
        if sid == "S00":
            return builtin_scene("S00")
        return next((s for s in self.scenes() if s.get("id") == sid), None)

    # ---- Notion 상태
    @property
    def notion_state(self) -> dict:
        return read_json(self.dir / "notion_state.json", {}) or {}

    def save_notion_state(self, st: dict):
        write_json(self.dir / "notion_state.json", st)


def builtin_scene(sid: str) -> dict | None:
    for p in (CONTENT / "scenes").glob(f"{sid}*.yml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        d["_file"] = p.name
        return d
    return None
