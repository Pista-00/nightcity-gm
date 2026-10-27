"""캐릭터 생성 데이터.

이 저장소에는 룰북의 표(역할·스킬 목록·라이프패스·월급표 등)가 들어 있지 않다.
사용자가 자기 룰북 PDF 를 등록하면 cp2020.book 이 그 책에서 데이터를 추출해
book/chargen.json (로컬, git 제외)에 저장하고, 여기서는 그것을 읽어 제공한다.

    from cp2020 import chargen_data as D
    D.ROLES      # 룰북 등록 전이면 BookMissing 예외
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARGEN_FILE = ROOT / "book" / "chargen.json"

# 능력치 약어와 우리말 설명 (게임 용어 자체만 사용)
STATS = [
    ("INT", "지능", "문제 해결·관찰·기억"),
    ("REF", "반사신경", "사격·격투·운전"),
    ("TECH", "기술", "수리·기계 조작"),
    ("COOL", "침착", "공포·압박에 버티는 힘"),
    ("ATTR", "매력", "외모"),
    ("LUCK", "행운", "굴림에 보탤 수 있는 운"),
    ("MA", "이동력", "달리기 속도"),
    ("BODY", "신체", "체력·피해 감소"),
    ("EMP", "공감", "설득·카리스마"),
]
STAT_KEYS = [s[0] for s in STATS]

STAT_METHODS = {
    "cinematic": "고정 포인트 – 정해진 점수를 9개 능력치에 분배",
    "random": "랜덤 – 굴린 합계를 분배",
    "fast": "빠른 방식 – 능력치마다 굴린 숫자를 하나씩 배치",
}

# book/chargen.json 에 들어가는 키
BOOK_KEYS = ("ROLES", "SPECIAL_STAT", "SKILLS", "TECH_CHOICES", "SALARY", "CINEMATIC", "LP")


class BookMissing(RuntimeError):
    def __init__(self):
        super().__init__("룰북이 등록되지 않았습니다. ② 룰북 등록에서 내 룰북 PDF 를 등록하고 캐릭터 생성 데이터를 만드세요.")


_cache = {"mtime": None, "data": None}


def load():
    if not CHARGEN_FILE.exists():
        return None
    mt = CHARGEN_FILE.stat().st_mtime
    if _cache["mtime"] != mt:
        _cache["data"] = json.loads(CHARGEN_FILE.read_text(encoding="utf-8"))
        _cache["mtime"] = mt
    return _cache["data"]


def ready() -> bool:
    d = load()
    return bool(d and all(k in d for k in BOOK_KEYS))


def __getattr__(name):
    """D.ROLES 처럼 접근하면 등록된 룰북 데이터에서 꺼낸다 (PEP 562)."""
    if name in BOOK_KEYS or name == "SKILL_STAT":
        d = load()
        if not d:
            raise BookMissing()
        if name == "SKILL_STAT":
            m = {sk: st for st, lst in d["SKILLS"].items() for sk in lst}
            m.update(d.get("SPECIAL_STAT", {}))
            return m
        if name == "CINEMATIC":
            return {int(k): v for k, v in d["CINEMATIC"].items()}
        if name == "LP":
            lp = dict(d["LP"])
            lp["disaster_detail"] = {int(k): v for k, v in lp.get("disaster_detail", {}).items()}
            return lp
        return d[name]
    raise AttributeError(name)
