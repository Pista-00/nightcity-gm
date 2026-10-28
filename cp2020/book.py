"""사용자 룰북 등록 – 이 저장소는 룰북 내용을 담지 않는다.

흐름
1. import_pdf(): 사용자가 고른 PDF 에서 내 컴퓨터 안에서 텍스트를 뽑고, 맞는 책인지 확인한 뒤 색인을 만든다.
2. retrieve(): 매 턴 지금 상황과 관련된 부분만 찾아 AI GM 에게 준다 (기본 '색인' 모드).
3. extract_chargen(): 사용자 AI 로 캐릭터 생성 표(역할·스킬·월급·라이프패스)를 JSON 으로 뽑는다.
4. build_summary(): (선택) 사용자 AI 로 GM 레퍼런스 정리본을 만든다 ('정리본' 모드).

결과는 모두 book/ 폴더(git 제외)에만 저장된다. 원본 PDF 는 복사해 두지 않는다.
"""
import json
import math
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import chargen_data as D, jsonfix
from .ai_providers import Provider as _Provider, ProviderError

ai_read_image_base = _Provider.read_image

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "book"
META = BOOK / "book.json"
PAGES = BOOK / "pages.json"
INDEX = BOOK / "index.json"
SUMMARY = BOOK / "reference.md"
GEAR = BOOK / "gear.json"
PAGE_IMG = BOOK / "pages"            # 글자 없이 그림으로만 된 쪽의 이미지 (내 컴퓨터에만)
PAGE_TEXT = BOOK / "page_text.json"  # 그 쪽들을 AI 가 읽어 옮긴 글 {쪽번호: 글}
IMG_MIN_CHARS = 50                   # 이보다 글자가 적으면 그림 쪽으로 봄

# 이 책이 맞는지 확인하는 표지 (대소문자 무시). 일정 개수 이상 있으면 통과.
MARKERS = ["friday night firefight", "lifepath", "netrunn", "combat sense", "jury rig", "body type modifier",
           "night city", "career skills", "special abilit", "humanity", "cyberpsycho", "interface", "streetdeal",
           "awareness/notice", "eurodollar"]
MIN_MARKERS = 9
MIN_PAGES = 100

CHUNK = 1400
OVERLAP = 200


class BookError(RuntimeError):
    pass


def _tok(text: str):
    return re.findall(r"[a-z][a-z/&\-]{2,}", text.lower())


# ---------------------------------------------------------------- 상태
def meta() -> dict:
    return json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}


def status() -> dict:
    m = meta()
    return {"imported": bool(m), "file": m.get("file", ""), "pages": m.get("pages", 0),
            "markers": m.get("markers", []), "imported_at": m.get("imported_at", ""),
            "chargen": D.ready(), "summary": SUMMARY.exists(), "gear": GEAR.exists(),
            "summary_parts": m.get("summary_parts", 0), **image_status()}


def image_pages() -> list[int]:
    """글자가 거의 없는(그림으로 된) 쪽 번호(1부터)."""
    m = meta()
    if "image_pages" in m:
        return m["image_pages"]
    return [i + 1 for i, t in enumerate(_raw_pages()) if len(t.strip()) < IMG_MIN_CHARS]


def _page_text() -> dict:
    return json.loads(PAGE_TEXT.read_text(encoding="utf-8")) if PAGE_TEXT.exists() else {}


def _img_file(pno: int) -> Path:
    return PAGE_IMG / f"p{pno:03d}.jpg"


def image_status() -> dict:
    if not META.exists():
        return {"image_pages": [], "image_read": 0, "images_saved": False}
    ip, done = image_pages(), _page_text()
    return {"image_pages": ip, "image_read": sum(1 for p in ip if str(p) in done),
            "images_saved": any(_img_file(p).exists() for p in ip)}


def forget():
    for p in (META, PAGES, INDEX, SUMMARY, D.CHARGEN_FILE, GEAR, GEAR.with_name("gear.partial.json"), PAGE_TEXT):
        if p.exists():
            p.unlink()
    shutil.rmtree(PAGE_IMG, ignore_errors=True)


def _raw_pages() -> list[str]:
    return json.loads(PAGES.read_text(encoding="utf-8")) if PAGES.exists() else []


def pages() -> list[str]:
    """쪽별 글. 그림 쪽은 AI 가 읽어 옮긴 글로 채운다."""
    P = _raw_pages()
    for k, v in _page_text().items():
        i = int(k) - 1
        if v and 0 <= i < len(P):
            P[i] = f"[그림으로 된 쪽 – AI 가 읽어 옮김]\n{v}"
    return P


def _render_pages(pdf_path: Path, pnos: list[int], progress=None) -> bool:
    """그림 쪽을 JPEG 로 저장(긴 변 1800px). pypdfium2·Pillow 가 없으면 False."""
    shutil.rmtree(PAGE_IMG, ignore_errors=True)
    if not pnos:
        return True
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return False
    PAGE_IMG.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for k, pno in enumerate(pnos):
            if progress:
                progress(f"그림 쪽 이미지 저장 {k + 1}/{len(pnos)}", 0.9 + 0.08 * k / len(pnos))
            pg = pdf[pno - 1]
            w, h = pg.get_size()
            img = pg.render(scale=1800 / max(w, h, 1), grayscale=True).to_pil().convert("L")
            img.save(_img_file(pno), quality=80)
    except Exception:  # noqa: BLE001
        shutil.rmtree(PAGE_IMG, ignore_errors=True)
        return False
    finally:
        pdf.close()
    return True


# ---------------------------------------------------------------- 등록
def import_pdf(path: Path, filename: str, progress=None) -> dict:
    try:
        import pypdf
    except ImportError:
        raise BookError("pypdf 가 설치되지 않았습니다. pip install -r requirements.txt") from None
    try:
        reader = pypdf.PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")
        n = len(reader.pages)
    except Exception as e:  # noqa: BLE001
        raise BookError(f"PDF 를 열 수 없습니다: {e}") from None
    texts = []
    for i, pg in enumerate(reader.pages):
        try:
            texts.append(pg.extract_text() or "")
        except Exception:  # noqa: BLE001
            texts.append("")
        if progress and i % 10 == 0:
            progress(f"텍스트 추출 {i + 1}/{n}쪽", (i + 1) / n * 0.9)
    whole = "\n".join(texts).lower()
    found = [m for m in MARKERS if m in whole]
    if n < MIN_PAGES or len(found) < MIN_MARKERS:
        raise BookError(f"이 PDF 는 지원하는 룰북으로 확인되지 않았습니다 (쪽수 {n}, 확인된 표지 {len(found)}/{len(MARKERS)}). "
                        "텍스트가 들어 있는(검색 가능한) Cyberpunk 2020 코어 룰북 PDF 를 선택하세요.")
    BOOK.mkdir(exist_ok=True)
    img_pages = [i + 1 for i, t in enumerate(texts) if len(t.strip()) < IMG_MIN_CHARS]
    rendered = _render_pages(path, sorted(set(img_pages) | set(spec_pages(texts))), progress)
    if PAGE_TEXT.exists():          # 다른 PDF 일 수 있으니 예전 판독 결과는 버림
        PAGE_TEXT.unlink()
    PAGES.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    build_index(texts)
    m = {"file": filename, "pages": n, "markers": found, "imported_at": datetime.now().isoformat(timespec="seconds"),
         "image_pages": img_pages, "images_rendered": rendered}
    META.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress:
        progress("색인 완료", 1.0)
    return status()


def build_index(texts):
    chunks = []
    for pno, t in enumerate(texts, 1):
        t = re.sub(r"[ \t]+", " ", t).strip()
        if len(t) < 40:
            continue
        for s in range(0, len(t), CHUNK - OVERLAP):
            part = t[s:s + CHUNK]
            if len(part) > 80:
                chunks.append({"page": pno, "text": part})
    df = Counter()
    for c in chunks:
        df.update(set(_tok(c["text"])))
    INDEX.write_text(json.dumps({"chunks": chunks, "df": df, "n": len(chunks)}, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- 검색 (색인 모드)
# 플레이 대화는 한국어, 룰북은 영어 → 상황 단어를 영어 룰 용어로 넓힘 (게임 용어만 사용)
KO_EN = {
    "사격": "shoot firearms to hit range point blank close medium long extreme",
    "권총": "handgun to hit range point blank close medium", "라이플": "rifle to hit range long extreme",
    "공격": "attack to hit range damage combat round", "명중": "to hit range modifiers aimed",
    "전투": "combat round initiative turn actions", "총격": "firearms to hit range autofire", "총": "firearms handgun rifle ammo", "쏘": "shoot to hit range",
    "자동": "autofire burst full auto", "연사": "autofire burst", "저격": "rifle aimed shot range",
    "근접": "melee brawling martial", "주먹": "brawling punch", "칼": "melee knife blade", "격투": "brawling martial arts",
    "회피": "dodge escape", "엄폐": "cover", "수류탄": "grenade explosive area", "폭발": "explosive blast",
    "부상": "damage wound location", "피해": "damage armor sp body type modifier", "상처": "wound state stun death save",
    "기절": "stun save", "사망": "death save mortal", "방어구": "armor sp stopping power", "치료": "medical first aid healing recovery",
    "의사": "medical tech trauma", "수술": "surgery medical tech", "사이버웨어": "cyberware humanity cost",
    "사이버사이코": "cyberpsychosis humanity", "휴머니티": "humanity cost", "넷": "net netrunning program ice",
    "해킹": "netrunning interface program ice", "넷러너": "netrunner interface cyberdeck", "데크": "cyberdeck program memory",
    "운전": "drive vehicle", "차량": "vehicle", "추격": "chase vehicle maneuver", "선제": "initiative", "이니셔티브": "initiative",
    "협박": "intimidate facedown reputation", "대치": "facedown cool reputation", "설득": "persuasion fast talk",
    "은신": "stealth hide evade", "인지": "awareness notice", "관찰": "awareness notice", "추적": "shadow track",
    "자물쇠": "pick lock", "수리": "repair basic tech jury rig", "경험치": "improvement points", "평판": "reputation",
    "가격": "cost eurodollars", "구매": "cost eurodollars", "장비": "gear cost weight", "마약": "drugs",
    "고문": "interrogation resist torture", "심문": "interrogation", "판정": "difficulty skill roll", "난이도": "difficulty",
}
CORE_QUERY = "task difficulty skill stat roll critical success fumble average difficult nearly impossible"


def _load_index():
    if not INDEX.exists():
        return None
    return json.loads(INDEX.read_text(encoding="utf-8"))


def _score(idx, words):
    n = idx["n"] or 1
    df = idx["df"]
    q = Counter(words)
    out = []
    for i, c in enumerate(idx["chunks"]):
        tf = Counter(_tok(c["text"]))
        s = sum(tf[w] * math.log(1 + n / (1 + df.get(w, 0))) * qn for w, qn in q.items() if tf[w])
        if s:
            out.append((s, i))
    out.sort(reverse=True)
    return out


def retrieve(context: str, budget_chars=11000, k=7) -> str:
    """대화 맥락에 맞는 룰북 구간들을 돌려준다(쪽 번호 포함)."""
    idx = _load_index()
    if not idx:
        return ""
    words = _tok(context)
    for ko, en in KO_EN.items():
        if ko in context:
            words += en.split() * 2
    picked, used = [], 0
    for _, i in _score(idx, _tok(CORE_QUERY))[:2] + _score(idx, words)[:k * 2]:
        if i in [p for p in picked]:
            continue
        txt = idx["chunks"][i]["text"]
        if used + len(txt) > budget_chars:
            break
        picked.append(i)
        used += len(txt)
        if len(picked) >= k + 2:
            break
    picked.sort(key=lambda i: idx["chunks"][i]["page"])
    return "\n\n".join(f"[p.{idx['chunks'][i]['page']}] {idx['chunks'][i]['text']}" for i in picked)


def summary_text() -> str:
    return SUMMARY.read_text(encoding="utf-8") if SUMMARY.exists() else ""


# ---------------------------------------------------------------- AI 로 캐릭터 생성 데이터 추출
# 표를 뽑을 때 쓰는 쪽 고르기 규칙(키워드 가중치). 등록할 때 이 규칙으로 고른 쪽은 이미지로 저장해 두고,
# 표를 만들 때 AI 가 그 이미지를 보고 옮긴 글을 쓴다(PDF 글자 추출은 표의 칸 순서가 뒤섞이는 일이 많음).
SPECS = {
    "roles": dict(keywords={"career skills": 20, "career package": 20, "pickup skills": 8, "special abilit": 6,
                            "awareness/notice": 2, "jury rig": 3, "streetdeal": 3, "combat sense": 3, "interface": 1},
                  limit_page=120, top=5),
    "skills": dict(keywords={"skill list": 20, "personal grooming": 4, "wardrobe": 3, "endurance": 2, "interrogation": 2,
                             "human perception": 2, "accounting": 3, "archery": 3, "aero tech": 3, "cryotank": 2,
                             "pick pocket": 2, "zoology": 3}, limit_page=120, top=6),
    "salary": dict(keywords={"occupation": 10, "salary": 6, "per month": 6, "unemployed": 6, "character points": 10,
                             "cinematic": 10, "major hero": 10, "minor hero": 10}, limit_page=120, top=5),
    "lifepath1": dict(keywords=["lifepath", "dress", "hairstyle", "affectation", "ethnic", "family", "siblings", "parents",
                                "childhood", "motivations", "personality", "valued", "possession"], limit_page=60),
    "lifepath2": dict(keywords=["big problems", "big wins", "disaster", "lucky", "friends", "enemies", "romance", "tragic",
                                "problematic", "mutual"], limit_page=60),
    "weapons": dict(keywords={"rof": 3, "rel": 2, "conc": 3, "avail": 3, "kendachi": 5, "minami": 2, "avenger": 6, "smg": 2,
                              "assault": 2, "weapons list": 15}, limit_page=130, top=4, budget=50000, vision=3),
    "armor_gear": dict(keywords={"kevlar": 4, "armor jacket": 5, "flak": 5, "metalgear": 6, "ev": 1, "techscanner": 6,
                                 "medkit": 6, "mastoid": 6, "binoglasses": 6, "laptop": 3, "tech toolkit": 6},
                       limit_page=130, top=5, budget=50000, vision=4),
    "cyber1": dict(keywords={"humanity cost": 4, "neural": 4, "kerenzikov": 6, "sandevistan": 6, "interface plugs": 6,
                             "biomonitor": 6, "nasal": 5, "grafted muscle": 6, "skin weave": 6, "smartgun link": 6,
                             "fashionware": 6, "implant": 3, "cyberware list": 15, "h.loss": 40, "id code": 30}, limit_page=130, top=6,
                   budget=55000, vision=3, vision_next=True),
    "cyber2": dict(keywords={"cyberoptic": 5, "cyberaudio": 5, "cyberarm": 6, "cyberleg": 6, "wolvers": 6, "rippers": 4,
                             "linear frame": 6, "body plating": 6, "hydraulic": 6, "talon": 5, "cyberware list": 15,
                             "h.loss": 40, "id code": 30}, limit_page=130, top=6, budget=55000, vision=3, vision_next=True),
}


def _scored(texts, keywords, limit_page=None) -> list[int]:
    """키워드 점수가 높은 순서의 쪽 번호(0부터)."""
    weights = keywords if isinstance(keywords, dict) else {k: 1 for k in keywords}
    scored = []
    for i, t in enumerate(texts):
        if limit_page and i + 1 > limit_page:
            break
        sc = sum(t.lower().count(k.lower()) * w for k, w in weights.items())
        if sc:
            scored.append((sc, i))
    scored.sort(reverse=True)
    return [i for _, i in scored]


def _choose(texts, keywords, extra=1, limit_page=None, top=8, budget=45000, vision=0, vision_next=False) -> list[int]:
    """키워드(가중치)가 많이 나오는 쪽과 그 이웃 쪽 번호(0부터)."""
    weights = keywords if isinstance(keywords, dict) else {k: 1 for k in keywords}
    scored = []
    for i, t in enumerate(texts):
        if limit_page and i + 1 > limit_page:
            break
        low = t.lower()
        sc = sum(low.count(k.lower()) * w for k, w in weights.items())
        if sc:
            scored.append((sc, i))
    scored.sort(reverse=True)
    chosen = set()
    for _, i in scored[:top]:
        for j in range(i - extra, i + extra + 1):
            if 0 <= j < len(texts):
                chosen.add(j)
    return sorted(chosen)


def _vision_pages(texts, sp) -> list[int]:
    """이미지로 읽을 쪽(1부터): 점수 상위 vision 개."""
    n = sp.get("vision", 0)
    top = [i + 1 for i in _scored(texts, sp["keywords"], sp.get("limit_page"))[:n]] if n else []
    if sp.get("vision_next"):          # 표가 다음 쪽으로 이어지는 경우
        top += [p + 1 for p in top if p < len(texts)]
    return sorted(set(top))


def spec_pages(texts) -> list[int]:
    """표 규칙이 이미지로 읽는 쪽(1부터) – 등록할 때 이미지로 저장할 쪽."""
    return sorted({p for sp in SPECS.values() for p in _vision_pages(texts, sp)})


def _vision_ok(prov) -> bool:
    return prov is not None and type(prov).read_image is not ai_read_image_base and not getattr(prov, "_no_vision", False)


def _transcribe(prov, pnos, progress=None, frac=(0.0, 1.0)) -> None:
    """이미지로 저장된 쪽 중 아직 안 읽은 것을 AI 가 읽어 page_text.json 에 저장."""
    done = _page_text()
    todo = [p for p in pnos if str(p) not in done and _img_file(p).exists()]
    for k, pno in enumerate(todo):
        if progress:
            progress(f"{pno}쪽 표를 이미지로 읽는 중 ({k + 1}/{len(todo)})", frac[0] + (frac[1] - frac[0]) * k / len(todo))
        try:
            text = prov.read_image(READ_PROMPT, [_img_file(pno)]).strip()
        except ProviderError as e:
            if "지원하지 않습니다" in str(e):
                prov._no_vision = True     # 이미지 못 보는 AI 면 글자 추출본으로 진행
                return
            if _skippable(e):
                continue                   # 이 쪽은 건너뛰고 글자 추출본 사용(다음에 다시 시도)
            raise
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text).strip()
        done[str(pno)] = "" if text in ("", "(글 없음)") else text
        PAGE_TEXT.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")


def _skippable(e) -> bool:
    """AI 가 이 쪽만 거절한 경우(콘텐츠 필터 등) – 작업 전체를 멈추지 않고 건너뜀."""
    m = str(e).lower()
    return any(k in m for k in ("content filtering", "content_filter", "content policy", "safety", "recitation",
                                "blocked", "invalid_prompt"))


def _src(name, prov=None, progress=None, frac=(0.0, 1.0)) -> str:
    """규칙 name 으로 쪽을 골라 글로 합침. prov 가 이미지를 볼 수 있으면 표 쪽을 먼저 이미지로 읽음."""
    sp = dict(SPECS[name])
    budget = sp.pop("budget", 45000)
    raw = _raw_pages()
    chosen = _choose(raw, budget=budget, **sp)
    if _vision_ok(prov):
        want = set(_vision_pages(raw, SPECS[name])) | {i + 1 for i in chosen if len(raw[i].strip()) < IMG_MIN_CHARS}
        _transcribe(prov, sorted(want), progress, frac)
    P = pages()
    out, used = [], 0
    for i in chosen:
        if used + len(P[i]) > budget:
            break
        out.append(f"=== p.{i + 1} ===\n{P[i]}")
        used += len(P[i])
    return "\n".join(out)


def _ask_json(prov, task: str, source: str) -> dict:
    system = [("너는 TRPG 룰북에서 데이터를 정확히 옮겨 적는 도우미다. 요청한 JSON 객체 하나만 출력한다. "
               "룰북에 있는 값만 쓰고 지어내지 않는다. 문자열 안에 큰따옴표가 있으면(예: 무기 이름의 별명) \\\" 로 이스케이프한다.", False),
              (f"# 사용자가 등록한 룰북 발췌\n{source}", True)]
    err = ""
    for attempt in range(2):     # JSON 이 깨지면 고쳐 읽고, 그래도 안 되면 한 번 더 요청
        reply = prov.chat(system, [{"role": "user", "content": task + (jsonfix.RETRY_HINT.format(err=err) if attempt else "")}])
        d, err = jsonfix.extract(reply)
        if d is not None:
            return d
    raise BookError(f"{err}. 다시 시도하세요.")


def _need10(d, name):
    if not isinstance(d, list) or len(d) != 10:
        raise BookError(f"'{name}' 표는 1D10 결과 10개여야 하는데 {len(d) if isinstance(d, list) else '?'}개입니다. 다시 시도하세요.")


def extract_chargen(prov, progress=None) -> dict:
    if not PAGES.exists():
        raise BookError("먼저 룰북 PDF 를 등록하세요.")
    step = lambda msg, f: progress and progress(msg, f)  # noqa: E731
    out = {}

    step("역할·특수능력·커리어 스킬 추출 중", 0.05)
    src = _src("roles", prov, progress, (0.02, 0.15))
    r = _ask_json(prov, """역할(Role) 10개의 데이터를 JSON 으로:
{"ROLES": {"<영어 역할명>": {"ko": "<한국어 이름>", "special": "<특수능력 영어 이름>",
   "desc": "<역할 설명, 한국어 한 문장, 직접 요약>", "skills": [<특수능력을 제외한 커리어 스킬 9개, 영어 이름>]}},
 "SPECIAL_STAT": {"<특수능력 영어 이름>": "<붙는 능력치 약어 INT/REF/TECH/COOL/ATTR/LUCK/MA/BODY/EMP, 없으면 '-'>"}}
규칙: 'A 또는 B' 중 고르는 스킬은 "A|B" 한 항목으로. '기술 스킬 중 아무거나' 처럼 자유 선택 칸은 "TECH_CHOICE" 로 칸 수만큼.
스킬 이름은 룰북 표기 그대로(예: "Awareness/Notice", "Education & Gen. Knowledge", "Persuasion & Fast Talk").""", src)
    roles = r.get("ROLES") or {}
    if len(roles) < 8 or any(len(v.get("skills", [])) != 9 for v in roles.values()):
        raise BookError("역할 데이터가 불완전합니다(역할 수 또는 커리어 스킬 9개 확인 실패). 다시 시도하세요.")
    out["ROLES"], out["SPECIAL_STAT"] = roles, r.get("SPECIAL_STAT") or {}

    step("스킬 목록 추출 중", 0.3)
    src = _src("skills", prov, progress, (0.22, 0.3))
    r = _ask_json(prov, """마스터 스킬 목록을 능력치별로 JSON 으로:
{"SKILLS": {"ATTR": [...], "BODY": [...], "COOL": [...], "EMP": [...], "INT": [...], "REF": [...], "TECH": [...]},
 "TECH_CHOICES": [<테키가 자유 선택할 수 있는 기술 계열 스킬 목록>]}
특수능력은 넣지 않는다. 스킬 이름은 룰북 표기 그대로. 무술은 "Martial Arts" 한 항목으로.""", src)
    sk = r.get("SKILLS") or {}
    if sum(len(v) for v in sk.values()) < 40:
        raise BookError("스킬 목록이 너무 적습니다. 다시 시도하세요.")
    # 커리어 스킬이 목록에 없으면 (표기 차이) TECH/INT 등에 보정하지 않고 그대로 둔다 – 화면에서 표시만 영향
    out["SKILLS"] = {k: sk.get(k, []) for k in ("ATTR", "BODY", "COOL", "EMP", "INT", "REF", "TECH")}
    out["TECH_CHOICES"] = r.get("TECH_CHOICES") or out["SKILLS"]["TECH"]

    step("월급표·능력치 포인트 추출 중", 0.5)
    src = _src("salary", prov, progress, (0.42, 0.5))
    r = _ask_json(prov, f"""두 표를 JSON 으로:
{{"SALARY": {{"<역할명 – 반드시 다음 중 하나: {', '.join(roles)}>": [<특수능력 1~5, 6, 7, 8, 9, 10 일 때 월급 숫자 6개>]}},
 "CINEMATIC": {{"<포인트 숫자>": "<등급 이름 한국어 (영어)>"}}}}""", src)
    sal = {k: v for k, v in (r.get("SALARY") or {}).items() if k in roles and isinstance(v, list) and len(v) == 6}
    if len(sal) < len(roles) - 1:
        raise BookError("월급표 추출이 불완전합니다. 다시 시도하세요.")
    out["SALARY"] = sal
    out["CINEMATIC"] = r.get("CINEMATIC") or {}
    if not out["CINEMATIC"]:
        raise BookError("능력치 포인트 표를 찾지 못했습니다. 다시 시도하세요.")

    step("라이프패스 표 추출 중 (1/2)", 0.65)
    src = _src("lifepath1", prov, progress, (0.6, 0.66))
    r1 = _ask_json(prov, """라이프패스 앞부분 표들을 한국어로 옮겨 JSON 으로. 각 표는 1D10 결과 1~10 순서의 문자열 10개 배열:
{"clothes": [], "hair": [], "affectation": [], "ethnic": [<출신(모국어)>], "family_rank": [], "parent_fate": [<부모에게 무슨 일이 있었나>],
 "family_tragedy": [<가문의 위기>], "childhood": [<유년기 환경>],
 "sibling_feel": [<형제에 대한 감정 10칸, 범위로 된 표는 칸마다 펼쳐서>],
 "personality": [], "valued_person": [], "value": [], "feel_people": [], "possession": []}""", src)

    step("라이프패스 표 추출 중 (2/2)", 0.82)
    src = _src("lifepath2", prov, progress, (0.8, 0.84))
    r2 = _ask_json(prov, """라이프패스 인생 사건 표들을 한국어로 옮겨 JSON 으로. 각 표는 1D10 결과 1~10 순서의 문자열 10개 배열이고,
범위로 된 표(예: 1-4 ...)는 칸마다 펼쳐서 10개를 채운다. 'Roll 1D10x100' 은 {d10x100}, 'Roll 1D10 개월' 등은 {d10} 로 표기.
{"disaster": [<재난 10개>], "disaster_detail": {"<재난 배열 인덱스 0~9>": [<그 재난의 세부 표 10칸>]},
 "disaster_response": [<어떻게 대응하나 10칸>], "lucky": [<행운 10개>], "friend": [<친구 관계 10개>],
 "enemy_who": [], "enemy_cause": [], "enemy_angry": [<누가 화났나 10칸>], "enemy_do": [<마주치면 10칸>], "enemy_power": [<동원 전력 10칸>],
 "romance": [<10칸, 값은 반드시 '행복한 연애' / '비극적인 연애' / '문제 있는 연애' / '가벼운 만남' 중 하나>],
 "romance_tragic": [], "romance_problem": [], "mutual": [<상호 감정 10개>]}""", src)
    lp = {**r1, **r2}
    for key in ("clothes", "hair", "affectation", "ethnic", "family_rank", "parent_fate", "family_tragedy", "childhood",
                "sibling_feel", "personality", "valued_person", "value", "feel_people", "possession", "disaster",
                "disaster_response", "lucky", "friend", "enemy_who", "enemy_cause", "enemy_angry", "enemy_do",
                "enemy_power", "romance", "romance_tragic", "romance_problem", "mutual"):
        _need10(lp.get(key), key)
    lp["disaster_detail"] = {str(int(k)): v for k, v in (lp.get("disaster_detail") or {}).items()
                             if isinstance(v, list) and len(v) == 10}
    out["LP"] = lp

    D.CHARGEN_FILE.parent.mkdir(exist_ok=True)
    D.CHARGEN_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    step("완료", 1.0)
    return status()


# ---------------------------------------------------------------- AI 로 장비·사이버웨어 목록 추출
GEAR_SCHEMA = {
    "weapons": '{"name","group":"<분류 한국어 예: 중 자동권총>","type":"권총|기관단총|소총|샷건|중화기|근접|특수","skill":"<사용 스킬 영어>","wa","conceal","avail","damage","shots","rof","rel","range","cost":<숫자>,"cost_text"}',
    "armor": '{"name","loc":"<보호 부위 한국어>","sp":<숫자>,"ev":"<숫자>","soft":<칼날에 약한 소프트 아머면 true>,"cost":<숫자>,"cost_text"}',
    "gear": '{"name":"<한국어 이름>","group":"<분류 한국어: 도구/개인 전자/데이터/통신/감시/보안/의료/차량/패션/넷러닝/탄약>","cost":<숫자>,"cost_text","note":"<짧은 효과 한국어>"}',
    "cyberware": '{"name":"<영어 이름>","group":"<분류 한국어: 패션웨어/뉴럴웨어/임플란트/바이오웨어/사이버무기/사이버옵틱/사이버옵틱 옵션/사이버오디오/사이버오디오 옵션/사이버림/사이버림 옵션/사이버림 손/사이버림 발/사이버림 내장/사이버림 무기/리니어 프레임/바디 플레이팅>","surgery":"N|M|MA|CR","cost":<숫자>,"cost_text","hl":"<휴머니티 손실: 주사위 식(예 2D6, 1D6/2) 또는 숫자>","effect":"<효과 한국어 한 줄>","requires":"<먼저 필요한 장치: Neural Processor / Cyberoptic / Cyberaudio / Cyberarm/Cyberleg 또는 빈칸>"}',
}


def _ask_list(prov, key, what, src, extra=""):
    r = _ask_json(prov, f"""{what} 를 룰북 표에서 빠짐없이 옮겨 JSON 으로:
{{"{key}": [{GEAR_SCHEMA[key]}, ...]}}
cost 는 따옴표 없는 정수(예 1000, 쉼표·eb·$ 금지. 범위면 낮은 값, '/레벨' 등 단위는 cost_text 에), 없는 값은 "". 표에 있는 항목만. {extra}""", src)
    return [x for x in (r.get(key) or []) if isinstance(x, dict) and x.get("name")]


READ_PROMPT = """이 이미지는 사용자가 소유한 TRPG 룰북의 한 쪽이다. 게임 진행용 데이터로 정리하라.
- 표: 머리글 행부터 한 행씩, 칸 사이를 ' | ' 로 구분해 적는다. 표 안의 분류 제목 행(예 LIGHT AUTOPISTOLS)도 그 자리에.
  이름·숫자·기호(예 250.00, 1D6+1, -1, 2,000, (MA))는 보이는 그대로 정확히. 칸이 비었으면 빈칸.
- 본문 문단: 원문을 옮기지 말고, 게임 규칙과 수치만 한국어로 짧게 요약(항목 이름은 영어 원문 유지).
- 그림·장식뿐이면 '(글 없음)' 한 줄만.
- 설명이나 머리말 없이 결과만 출력."""


def read_image_pages(prov, progress=None, force=False) -> dict:
    """그림으로만 된 쪽을 AI 에게 이미지로 보여 주고 글로 옮겨 둔다. 끊기면 다시 눌러 이어서."""
    if not PAGES.exists():
        raise BookError("먼저 룰북 PDF 를 등록하세요.")
    ip = image_pages()
    if not ip:
        return status()
    if not any(_img_file(p).exists() for p in ip):
        raise BookError("그림 쪽 이미지가 없습니다. 이 기능이 생기기 전에 등록한 PDF 이면 같은 PDF 를 한 번 다시 등록하세요"
                        "(만들어 둔 캐릭터 생성 표·장비 목록은 그대로 남습니다).")
    done = {} if force else _page_text()
    todo = [p for p in ip if str(p) not in done]
    skipped = []
    for k, pno in enumerate(todo):
        if progress:
            progress(f"{pno}쪽 읽는 중 ({k + 1}/{len(todo)})", k / len(todo))
        f = _img_file(pno)
        try:
            text = prov.read_image(READ_PROMPT, [f]).strip() if f.exists() else ""
        except ProviderError as e:
            if not _skippable(e):
                raise
            skipped.append(pno)
            continue
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text).strip()
        done[str(pno)] = "" if text in ("", "(글 없음)") else text
        PAGE_TEXT.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    if progress:
        progress("색인 다시 만드는 중", 0.98)
    build_index(pages())
    if skipped:
        raise BookError(f"AI 가 {', '.join(map(str, skipped))}쪽 읽기를 거절했습니다(나머지는 완료). 다시 누르면 그 쪽만 다시 시도합니다.")
    return status()


def extract_gear(prov, progress=None) -> dict:
    if not PAGES.exists():
        raise BookError("먼저 룰북 PDF 를 등록하세요.")
    step = lambda msg, f: progress and progress(msg, f)  # noqa: E731
    # 단계별 결과를 임시 저장 → 사용량 한도 등으로 끊겨도 다시 누르면 이어서 진행
    part = GEAR.with_name("gear.partial.json")
    out = json.loads(part.read_text(encoding="utf-8")) if part.exists() else {}

    def run(key, msg, f, fn):
        if key in out:
            step(msg + " (이전 결과 사용)", f)
            return
        step(msg, f)
        out[key] = fn()
        part.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    def weapons():
        src = _src("weapons", prov, progress, (0.05, 0.2))
        return _ask_list(prov, "weapons", "무기 표(권총·SMG·소총·샷건·중화기·특수·근접 무기)", src,
                         "가격은 무기 목록 표(WEAPONS LIST 등)의 Cost 열에서. 무기 설명 문단에는 가격이 없으니 표와 이름을 맞춰 채운다.")

    def armor_src():
        return _src("armor_gear", prov, progress, (0.25, 0.35))

    def cyber1():
        src = _src("cyber1", prov, progress, (0.55, 0.65))
        return _ask_list(prov, "cyberware", "사이버웨어 표 중 패션웨어·뉴럴웨어(링크·부스터·플러그·칩 소켓 포함)·임플란트·바이오웨어", src,
                         "신경계 장치(링크·부스터·플러그·칩 소켓)는 requires 에 Neural Processor. Neural Processor 자체도 포함.")

    def cyber2():
        src = _src("cyber2", prov, progress, (0.75, 0.82))
        return _ask_list(prov, "cyberware", "사이버웨어 표 중 사이버무기·사이버옵틱(+옵션)·사이버오디오(+옵션)·사이버림(+옵션·손·발·내장·림 무기)·리니어 프레임·바디 플레이팅", src,
                         "옵틱 옵션은 requires Cyberoptic, 오디오 옵션은 Cyberaudio, 림 옵션·손·발·내장·림 무기는 Cyberarm/Cyberleg.")

    run("weapons", "무기 표 추출 중", 0.05, weapons)
    run("armor", "방어구 표 추출 중", 0.25, lambda: _ask_list(prov, "armor", "방어구 표", armor_src()))
    run("gear", "장비 표 추출 중", 0.4, lambda: _ask_list(prov, "gear", "일반 장비 표(패션·도구·개인 전자·데이터·통신·감시·보안·의료·차량)",
                                                      armor_src(), "가구·음식·주거·생활비·엔터테인먼트는 제외."))
    run("cyber1", "사이버웨어 추출 중 (1/2)", 0.55, cyber1)
    run("cyber2", "사이버웨어 추출 중 (2/2)", 0.75, cyber2)
    cy = out.pop("cyber1") + out.pop("cyber2")
    seen, out["cyberware"] = set(), []
    for c in cy:
        k = c["name"].lower()
        if k not in seen:
            seen.add(k)
            out["cyberware"].append(c)
    if len(out["weapons"]) < 15 or len(out["cyberware"]) < 40:
        part.unlink(missing_ok=True)  # 결과가 부실하면 다음엔 처음부터
        raise BookError(f"추출이 불완전합니다(무기 {len(out['weapons'])}개, 사이버웨어 {len(out['cyberware'])}개). 다시 시도하세요.")
    for x in out["weapons"] + out["armor"] + out["gear"] + out["cyberware"]:
        if not isinstance(x.get("cost"), int) or not x["cost"]:
            m = re.search(r"\d[\d,]*", f'{x.get("cost") or ""} {x.get("cost_text") or ""}')
            x.setdefault("cost_text", str(x.get("cost") or ""))
            x["cost"] = int(m.group().replace(",", "")) if m else 0
    out["notes"] = {"cyberware": "HL 주사위를 굴려 휴머니티 손실로 기록. 10 누적마다 EMP −1."}
    GEAR.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    part.unlink(missing_ok=True)
    step("완료", 1.0)
    return status()


# ---------------------------------------------------------------- (선택) AI 정리본
def build_summary(prov, progress=None, part_chars=60000) -> dict:
    P = pages()
    if not P:
        raise BookError("먼저 룰북 PDF 를 등록하세요.")
    parts, cur = [], []
    for i, t in enumerate(P, 1):
        cur.append(f"=== p.{i} ===\n{t}")
        if sum(map(len, cur)) > part_chars:
            parts.append("\n".join(cur))
            cur = []
    if cur:
        parts.append("\n".join(cur))
    notes = []
    for n, part in enumerate(parts, 1):
        if progress:
            progress(f"정리본 작성 중 {n}/{len(parts)}", (n - 1) / len(parts))
        notes.append(prov.chat(
            [("너는 TRPG 레퍼리를 위한 규칙 정리 담당이다. 원문을 옮겨 적지 말고 GM 이 판정에 쓸 핵심만 "
              "한국어 마크다운으로 간결하게 정리한다(공식·수치·표의 요점·예외). 세계관 설정은 짧게 요점만. 쪽 번호를 (p.N) 로 남긴다.", False)],
            [{"role": "user", "content": f"룰북 {n}/{len(parts)} 부분이다. GM 레퍼런스로 정리하라.\n\n{part}"}]).strip())
    SUMMARY.write_text("\n\n---\n\n".join(notes), encoding="utf-8")
    m = meta()
    m["summary_parts"] = len(parts)
    META.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress:
        progress("완료", 1.0)
    return status()
