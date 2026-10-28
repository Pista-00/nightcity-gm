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
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import chargen_data as D

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "book"
META = BOOK / "book.json"
PAGES = BOOK / "pages.json"
INDEX = BOOK / "index.json"
SUMMARY = BOOK / "reference.md"
GEAR = BOOK / "gear.json"

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
            "summary_parts": m.get("summary_parts", 0)}


def forget():
    for p in (META, PAGES, INDEX, SUMMARY, D.CHARGEN_FILE, GEAR, GEAR.with_name("gear.partial.json")):
        if p.exists():
            p.unlink()


def pages() -> list[str]:
    return json.loads(PAGES.read_text(encoding="utf-8")) if PAGES.exists() else []


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
    PAGES.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    build_index(texts)
    m = {"file": filename, "pages": n, "markers": found, "imported_at": datetime.now().isoformat(timespec="seconds")}
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
def _pages_for(keywords, extra=1, budget=45000, limit_page=None, top=8):
    """키워드(가중치)가 많이 나오는 쪽과 그 이웃 쪽을 모아 텍스트로."""
    P = pages()
    weights = keywords if isinstance(keywords, dict) else {k: 1 for k in keywords}
    scored = []
    for i, t in enumerate(P):
        if limit_page and i + 1 > limit_page:
            break
        low = t.lower()
        s = sum(low.count(k.lower()) * w for k, w in weights.items())
        if s:
            scored.append((s, i))
    scored.sort(reverse=True)
    chosen = set()
    for _, i in scored[:top]:
        for j in range(i - extra, i + extra + 1):
            if 0 <= j < len(P):
                chosen.add(j)
    out, used = [], 0
    for i in sorted(chosen):
        if used + len(P[i]) > budget:
            break
        out.append(f"=== p.{i + 1} ===\n{P[i]}")
        used += len(P[i])
    return "\n".join(out)


def _ask_json(prov, task: str, source: str) -> dict:
    reply = prov.chat([("너는 TRPG 룰북에서 데이터를 정확히 옮겨 적는 도우미다. 요청한 JSON 객체 하나만 출력한다. "
                        "룰북에 있는 값만 쓰고 지어내지 않는다.", False),
                       (f"# 사용자가 등록한 룰북 발췌\n{source}", True)],
                      [{"role": "user", "content": task}])
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        raise BookError("AI 응답에서 JSON 을 찾지 못했습니다. 다시 시도하세요.")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise BookError(f"AI 가 만든 JSON 이 올바르지 않습니다({e}). 다시 시도하세요.") from None


def _need10(d, name):
    if not isinstance(d, list) or len(d) != 10:
        raise BookError(f"'{name}' 표는 1D10 결과 10개여야 하는데 {len(d) if isinstance(d, list) else '?'}개입니다. 다시 시도하세요.")


def extract_chargen(prov, progress=None) -> dict:
    if not PAGES.exists():
        raise BookError("먼저 룰북 PDF 를 등록하세요.")
    step = lambda msg, f: progress and progress(msg, f)  # noqa: E731
    out = {}

    step("역할·특수능력·커리어 스킬 추출 중", 0.05)
    src = _pages_for({"career skills": 20, "career package": 20, "pickup skills": 8, "special abilit": 6,
                      "awareness/notice": 2, "jury rig": 3, "streetdeal": 3, "combat sense": 3, "interface": 1},
                     extra=1, limit_page=120, top=5)
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
    src = _pages_for({"skill list": 20, "personal grooming": 4, "wardrobe": 3, "endurance": 2, "interrogation": 2,
                      "human perception": 2, "accounting": 3, "archery": 3, "aero tech": 3, "cryotank": 2,
                      "pick pocket": 2, "zoology": 3}, extra=1, limit_page=120, top=6)
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
    src = _pages_for({"occupation": 10, "salary": 6, "per month": 6, "unemployed": 6, "character points": 10,
                      "cinematic": 10, "major hero": 10, "minor hero": 10}, extra=1, limit_page=120, top=5)
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
    src = _pages_for(["lifepath", "dress", "hairstyle", "affectation", "ethnic", "family", "siblings", "parents",
                      "childhood", "motivations", "personality", "valued", "possession"], extra=1, limit_page=60)
    r1 = _ask_json(prov, """라이프패스 앞부분 표들을 한국어로 옮겨 JSON 으로. 각 표는 1D10 결과 1~10 순서의 문자열 10개 배열:
{"clothes": [], "hair": [], "affectation": [], "ethnic": [<출신(모국어)>], "family_rank": [], "parent_fate": [<부모에게 무슨 일이 있었나>],
 "family_tragedy": [<가문의 위기>], "childhood": [<유년기 환경>],
 "sibling_feel": [<형제에 대한 감정 10칸, 범위로 된 표는 칸마다 펼쳐서>],
 "personality": [], "valued_person": [], "value": [], "feel_people": [], "possession": []}""", src)

    step("라이프패스 표 추출 중 (2/2)", 0.82)
    src = _pages_for(["big problems", "big wins", "disaster", "lucky", "friends", "enemies", "romance", "tragic",
                      "problematic", "mutual"], extra=1, limit_page=60)
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
        src = _pages_for({"rof": 3, "rel": 2, "conc": 3, "avail": 3, "kendachi": 5, "minami": 2, "avenger": 6, "smg": 2, "assault": 2},
                         extra=1, limit_page=130, top=4, budget=50000)
        return _ask_list(prov, "weapons", "무기 표(권총·SMG·소총·샷건·중화기·특수·근접 무기)", src)

    def armor_src():
        return _pages_for({"kevlar": 4, "armor jacket": 5, "flak": 5, "metalgear": 6, "ev": 1, "techscanner": 6, "medkit": 6,
                           "mastoid": 6, "binoglasses": 6, "laptop": 3, "tech toolkit": 6}, extra=1, limit_page=130, top=5, budget=50000)

    def cyber1():
        src = _pages_for({"humanity cost": 4, "neural": 4, "kerenzikov": 6, "sandevistan": 6, "interface plugs": 6, "biomonitor": 6,
                          "nasal": 5, "grafted muscle": 6, "skin weave": 6, "smartgun link": 6, "fashionware": 6, "implant": 3},
                         extra=1, limit_page=130, top=6, budget=55000)
        return _ask_list(prov, "cyberware", "사이버웨어 표 중 패션웨어·뉴럴웨어(링크·부스터·플러그·칩 소켓 포함)·임플란트·바이오웨어", src,
                         "신경계 장치(링크·부스터·플러그·칩 소켓)는 requires 에 Neural Processor. Neural Processor 자체도 포함.")

    def cyber2():
        src = _pages_for({"cyberoptic": 5, "cyberaudio": 5, "cyberarm": 6, "cyberleg": 6, "wolvers": 6, "rippers": 4, "linear frame": 6,
                          "body plating": 6, "hydraulic": 6, "talon": 5}, extra=1, limit_page=130, top=6, budget=55000)
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
