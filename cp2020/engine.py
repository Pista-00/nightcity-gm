"""AI GM 진행 엔진 – 웹 화면과 독립적인 핵심 로직.

AI 출력 규약
  [[SCENE id="S01" title="" image="카탈로그id" location="" time=""]] 서술 [[/SCENE]]
  [[ROLL 1D10+14 | 설명]]   → 프로그램이 굴려 자동으로 결과를 돌려줌
  [[GM 메모]]               → 운영자 화면에만 표시
"""
import json
import re
from pathlib import Path

from . import ai_providers, book, chargen, chargen_data as D, dice, store

RULE_MODES = ["index", "summary", "none"]   # 색인(기본) / AI 정리본 / 없음
MAX_HISTORY = 40
MAX_AUTO_ROLL = 3

SCENE_RE = re.compile(r"\[\[SCENE(?P<attrs>[^\]]*)\]\](?P<body>.*?)\[\[/SCENE\]\]", re.S)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
ROLL_RE = re.compile(r"\[\[ROLL\s+([^|\]]+?)\s*(?:\|\s*([^\]]*))?\]\]")
GM_RE = re.compile(r"\[\[GM\s+(.*?)\]\]", re.S)
CHECK_RE = re.compile(r"\[\[CHECK(?P<attrs>[^\]|]*)(?:\|\s*(?P<why>[^\]]*))?\]\]")
TOKEN_RE = re.compile(r"(\[\[SCENE[^\]]*\]\].*?\[\[/SCENE\]\]|\[\[ROLL\s+[^\]]+\]\]|\[\[CHECK[^\]]*\]\]|\[\[GM\s+.*?\]\])", re.S)

INSTRUCTIONS = """\
너는 TRPG **사이버펑크 2020 (Cyberpunk 2.0.2.0)** 의 레퍼리(GM)다.
[룰북 발췌]·[룰 정리본]은 사용자가 등록한 자기 룰북에서 온 자료다. 판정은 이 자료를 따르고, 자료에 없는 부분은
레퍼리 재량으로 판정하되 그렇다고 짧게 밝혀라. 룰북 문장을 길게 그대로 옮겨 말하지 말고 요점만 설명하라.

## 진행 환경
- 운영자가 플레이어들의 말과 행동을 "이름: 행동" 형식으로 전달한다. 여러 명이 한 번에 올 수 있다.
- 플레이어가 굴린 주사위는 "[주사위] …" 로, 네가 요청한 굴림 결과는 "[프로그램 주사위 결과]" 로 온다.
- 캐릭터 생성은 프로그램의 캐릭터 화면에서 한다. 생성이 끝난 캐릭터는 [플레이어 캐릭터]에 나타난다.
- 출력은 한국어. 룰 용어는 처음 나올 때 영어를 괄호로 병기한다 (예: 회피(Dodge)).
- 플레이어 캐릭터의 행동·대사·감정을 대신 정하지 마라. 선택은 항상 플레이어에게 넘겨라.
- [진행 상태]의 경험 수준을 보고 규칙 설명의 양을 조절하라(처음 하는 사람이면 무엇을 굴리는지 쉽게).

## 분위기
- 항상 비가 오는 어둡고 편집증적인 도시. 극단적 빈부 대비. 선악이 모호한 선택.
- 3원칙: 스타일이 실력보다 중요 / 태도가 전부 / 벼랑 끝에서 살아라.
- 전투는 짧고 치명적이다. 그러나 공정하게. 규칙을 속이지 마라.
- [레퍼리 비밀] 내용은 플레이어가 알아낼 때까지 말하지 마라.
- 캐릭터의 라이프패스 훅(적·빚·옛 연인 등)을 이야기에 엮어라.

## 판정
- 플레이어 판정: 무엇을 굴릴지 쉽게 설명하고, 판정마다 CHECK 태그를 붙인 뒤 결과를 기다려라(아래 출력 규약 5).
  프로그램이 이 태그로 플레이어 화면의 주사위 창을 자동으로 채운다.
- 네가 굴려야 하는 판정(NPC 공격, 숨은 굴림, 피해 등)은 ROLL 태그로 요청하라. 결과를 받기 전에는 그 결과를 서술하지 마라.
- 1D10 자연 10 = 크리티컬(1D10 추가), 자연 1 = 펌블. 프로그램이 표시해 준다.
- 피해 처리: 부위(1D10) → 방어구 SP → 머리면 2배 → BTM → 상처 단계 → Stun/Death Save.

## 출력 규약 (프로그램이 읽는다 – 형식을 정확히)
1) 장면이 바뀔 때(장소 이동, 시간 경과, 전투 시작처럼 분위기가 크게 바뀔 때)만 장면 블록을 연다:
[[SCENE id="S01" title="장면 제목" image="이미지id" location="장소" time="시간"]]
플레이어에게 읽어줄 서술 3~8문장. (비밀·판정·규칙 설명은 넣지 않는다)
[[/SCENE]]
   - id 는 [진행 상태]의 "다음 장면 id" 를 쓴다. image 는 [이미지 카탈로그]에서 가장 잘 맞는 id 하나(없으면 "").
   - 장면 블록 뒤에 상황 정리와 "무엇을 하시겠습니까?" 같은 질문을 쓴다.
2) 네가 굴릴 주사위: 한 줄에 하나씩  [[ROLL 1D10+14 | 경비병 A 사격, 명중값 20]]
3) 운영자만 볼 메모(숨은 정보, 다음 전개 계획): [[GM 내용]]
4) 평소 응답은 짧게(대략 250단어 이내). 장면 서술은 조금 더 길어도 된다.
5) 플레이어 캐릭터에게 판정을 요청할 때: 한 줄에 하나씩
[[CHECK who="캐릭터 핸들" stat="REF" skill="Handgun" diff="20" mod="0" | 무엇을 위한 판정인지]]
   - who 는 [플레이어 캐릭터]의 핸들 그대로. stat 은 INT/REF/TECH/COOL/ATTR/LUCK/MA/BODY/EMP 중 하나.
   - skill 은 영어 스킬 이름 그대로(없으면 skill=""). diff 는 난이도(10/15/20/25/30), 대항 판정이면 diff 에 상대 값(모르면 diff="").
   - mod 는 상황 수정치만(없으면 0). 솔로의 Combat Sense(인지 판정)는 프로그램이 자동으로 더하므로 mod 에 넣지 마라.
   - 대항 판정에서 상대의 숨은 굴림이 먼저 필요하면 ROLL 결과를 받은 뒤 CHECK 를 한 번만 내라. 여러 명이 굴리면 태그를 여러 줄.
"""


# ---------------------------------------------------------------- 프롬프트
def rules_block(mode: str, context: str) -> tuple[str, bool]:
    """(텍스트, 캐시여부). 사용자가 등록한 룰북에서 온 자료만 쓴다."""
    st = book.status()
    if not st["imported"] or mode == "none":
        return ("# [룰 자료 없음]\n룰북이 등록되지 않았다. 일반적인 지식으로 판정하되, 확실하지 않은 규칙은 "
                "'레퍼리 재량' 이라고 밝혀라.", False)
    if mode == "summary" and st["summary"]:
        return (f"# [룰 정리본 – 사용자 룰북에서 작성]\n{book.summary_text()}", True)
    found = book.retrieve(context)
    return (f"# [룰북 발췌 – 지금 상황과 관련된 쪽]\n{found or '(관련 구간을 찾지 못함)'}", False)


def catalog_text() -> str:
    return "\n".join(f"- {i['id']}: {i.get('title', '')}" for i in store.catalog()) or "(없음)"


def build_system(c: store.Campaign, session: Path, rules_mode: str, context: str = "", max_session_chars=6000):
    meta = c.meta
    chars = c.characters()
    players = meta.get("players", [])
    session_text = session.read_text(encoding="utf-8") if session and session.exists() else ""
    if len(session_text) > max_session_chars:
        session_text = "…(앞부분 생략)…\n" + session_text[-max_session_chars:]
    s00 = store.builtin_scene("S00")
    dynamic = (
        f"# [진행 상태]\n- 캠페인: {meta.get('name')}\n- 현재 세션: {session.stem if session else '-'}\n"
        f"- 다음 장면 id: {c.next_scene_id()}\n- 플레이어 경험: {meta.get('experience', '처음 하는 사람 위주')}\n"
        f"- 플레이어: {', '.join(p.get('name', '') for p in players) or '(미정)'}\n"
        f"- 캠페인 메모: {meta.get('premise', '') or '-'}\n\n"
        f"# [도입 장면 S00 – 0회차 세계관 소개에 사용]\n{(s00 or {}).get('narration', '')}\n"
        f"(이미지 id: {(s00 or {}).get('image', '')})\n\n"
        f"# [이미지 카탈로그]\n{catalog_text()}\n\n"
        f"# [플레이어 캐릭터]\n" + ("\n\n".join(chargen.gm_summary(ch) for ch in chars) or "(아직 없음 – 캐릭터 화면에서 생성 중)")
        + f"\n\n# [세션 기록]\n{session_text or '(비어 있음)'}"
    )
    rules, cache = rules_block(rules_mode, context)
    if cache:   # 정리본은 고정 내용이라 캐시
        return [(INSTRUCTIONS, False), (rules, True), (dynamic, False)]
    return [(INSTRUCTIONS, True), (dynamic + "\n\n" + rules, False)]


# ---------------------------------------------------------------- 대화 기록
class Transcript:
    def __init__(self, path: Path):
        self.path = path
        self.items = []
        if path.exists():
            self.items = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def add(self, role, content, **meta):
        item = {"role": role, "content": content, "time": store.now(), **meta}
        self.items.append(item)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def rewrite(self):
        self.path.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in self.items), encoding="utf-8")

    def for_ai(self):
        msgs = [{"role": i["role"], "content": i["content"]} for i in self.items[-MAX_HISTORY:]]
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        merged = []
        for m in msgs:
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1]["content"] += "\n\n" + m["content"]
            else:
                merged.append(dict(m))
        return merged


# ---------------------------------------------------------------- 파싱
def segments(text: str, scene_ids=None) -> list[dict]:
    """AI 응답을 화면용 조각으로 나눈다."""
    out, k = [], 0
    scene_ids = list(scene_ids or [])
    for part in TOKEN_RE.split(text):
        if not part:
            continue
        if part.startswith("[[SCENE"):
            m = SCENE_RE.match(part)
            a = dict(ATTR_RE.findall(m.group("attrs")))
            sid = scene_ids[k] if k < len(scene_ids) else a.get("id", "")
            k += 1
            out.append({"kind": "scene", "id": sid, "title": a.get("title", ""), "image": a.get("image", ""),
                        "location": a.get("location", ""), "time": a.get("time", ""),
                        "narration": m.group("body").strip()})
        elif part.startswith("[[ROLL"):
            m = ROLL_RE.match(part)
            out.append({"kind": "rollreq", "expr": m.group(1).strip(), "why": (m.group(2) or "").strip()})
        elif part.startswith("[[CHECK"):
            m = CHECK_RE.match(part)
            a = dict(ATTR_RE.findall(m.group("attrs"))) if m else {}
            out.append({"kind": "check", "who": a.get("who", ""), "stat": a.get("stat", "").upper(),
                        "skill": a.get("skill", ""), "diff": a.get("diff", ""), "mod": a.get("mod", "0"),
                        "why": ((m.group("why") if m else "") or "").strip()})
        elif part.startswith("[[GM"):
            out.append({"kind": "gm", "text": GM_RE.match(part).group(1).strip()})
        elif part.strip():
            out.append({"kind": "text", "text": part.strip()})
    return out


def view(item: dict) -> dict:
    v = {k: item.get(k) for k in ("role", "time", "kind", "actor")}
    if item["role"] == "assistant":
        v["segments"] = segments(item["content"], item.get("scenes"))
    else:
        v["text"] = item["content"]
    return v


# ---------------------------------------------------------------- 게임 진행
class Game:
    def __init__(self, c: store.Campaign, session: Path):
        self.c, self.session = c, session
        self.tr = Transcript(c.transcript_path(session))

    def provider(self):
        s = store.settings()
        if not s.get("provider"):
            raise RuntimeError("먼저 설정에서 GM 을 맡을 AI 를 고르세요.")
        p = ai_providers.create(s["provider"], s.get("model", ""), max_tokens=int(s.get("max_tokens") or 2000))
        miss = p.missing()
        if miss:
            raise RuntimeError(f"{p.label} 연결 정보가 없습니다: {', '.join(miss)}")
        if not p.model:
            raise RuntimeError("모델을 고르세요.")
        return p

    def _call(self, prov):
        ctx = "\n".join(i["content"] for i in self.tr.items[-6:])
        blocks = build_system(self.c, self.session, store.settings().get("rules", "index"), ctx)
        return prov.chat(blocks, self.tr.for_ai())

    def _assistant(self, reply: str) -> list[dict]:
        """응답 저장 + 장면 저장. 새로 생긴 기록 항목들을 돌려준다."""
        scene_ids = []
        for m in SCENE_RE.finditer(reply):
            sc = self.c.save_scene(dict(ATTR_RE.findall(m.group("attrs"))), m.group("body"))
            scene_ids.append(sc["id"])
        return [self.tr.add("assistant", reply, scenes=scene_ids)]

    def turn(self, text: str, actor: str = "", kind: str = "player") -> list[dict]:
        prov = self.provider()
        new = [self.tr.add("user", text, kind=kind, actor=actor)]
        reply = self._call(prov)
        new += self._assistant(reply)
        for _ in range(MAX_AUTO_ROLL):
            rolls = ROLL_RE.findall(reply)
            if not rolls:
                break
            lines = []
            for expr, why in rolls:
                try:
                    lines.append(f"- {why.strip() or expr}: {dice.roll(expr)['text']}")
                except dice.DiceError as e:
                    lines.append(f"- {why.strip() or expr}: 굴림 실패 ({e})")
            new.append(self.tr.add("user", "[프로그램 주사위 결과 – GM 요청분]\n" + "\n".join(lines), kind="auto_roll"))
            reply = self._call(prov)
            new += self._assistant(reply)
        return new

    def retry(self) -> list[dict]:
        if not self.tr.items or self.tr.items[-1]["role"] != "assistant":
            raise RuntimeError("다시 생성할 응답이 없습니다.")
        self.tr.items.pop()
        self.tr.rewrite()
        prov = self.provider()
        return self._assistant(self._call(prov))

    def undo(self) -> int:
        n = 0
        while self.tr.items:
            it = self.tr.items.pop()
            n += 1
            if it["role"] == "user" and it.get("kind") != "auto_roll":
                break
        self.tr.rewrite()
        return n

    # ---- Notion 진행 기록용 요약
    @staticmethod
    def _plain(item) -> str:
        """GM 메모 제거, 장면·굴림 태그를 읽기 쉬운 문장으로."""
        t = GM_RE.sub("", item["content"])
        t = SCENE_RE.sub(lambda m: f"(장면 전환: {dict(ATTR_RE.findall(m.group('attrs'))).get('title', '')}) "
                                   f"{m.group('body').strip()}", t)
        t = ROLL_RE.sub(lambda m: f"(GM 판정 요청: {m.group(2) or m.group(1)})", t)
        t = CHECK_RE.sub(lambda m: f"(판정 요청: {(m.group('why') or '').strip()})", t)
        who = "GM" if item["role"] == "assistant" else ("주사위" if item.get("kind") == "auto_roll" else (item.get("actor") or "플레이어"))
        return f"[{who}] {t.strip()}"

    def digest(self, start: int, end: int) -> str:
        """items[start:end] 에서 일어난 일을 플레이어용 진행 기록 불릿으로 요약."""
        part = self.tr.items[start:end]
        if not part:
            return ""
        prov = self.provider()
        log = "\n\n".join(self._plain(i) for i in part)
        names = ", ".join(ch.get("handle", "") for ch in self.c.characters())
        prompt = (
            "아래는 TRPG 진행 기록의 일부다. 플레이어들이 나중에 읽을 '진행 기록'을 한국어 마크다운 불릿으로 정리하라.\n"
            "- 각 줄은 **[행동]**, **[대화]**, **[판정]**, **[사건]**, **[획득·변화]** 중 하나로 시작한다.\n"
            "- 누가(캐릭터 이름) 무엇을 했고 그 결과가 어땠는지 구체적으로 쓴다. 시간 순서대로.\n"
            "- [대화]는 누가 누구와 무슨 이야기를 했는지 요점, 중요한 대사는 짧게 인용.\n"
            "- [판정]은 '누가 무엇으로 굴려 몇 → 성공/실패와 그 결과'.\n"
            "- GM 비밀, 숨겨진 정보, 앞으로의 전개 예상, 규칙 설명, '무엇을 하시겠습니까' 같은 질문은 쓰지 않는다.\n"
            "- 3~12줄. 불릿만 출력한다.\n"
            f"- 플레이어 캐릭터: {names or '(미정)'}\n\n{log}")
        return prov.chat([("너는 사이버펑크 2020 캠페인의 기록 담당이다. 요청한 형식만 출력한다.", False)],
                         [{"role": "user", "content": prompt}]).strip()

    def summarize(self) -> str:
        """세션 요약 + IP 제안을 만들어 세션 기록에 덧붙인다."""
        prov = self.provider()
        log = "\n\n".join(f"{'GM' if i['role'] == 'assistant' else '플레이어'}: {GM_RE.sub('', i['content'])}"
                          for i in self.tr.items[-120:])
        prompt = ("아래는 이번 세션의 진행 기록이다. 플레이어에게 공개할 세션 요약을 한국어 마크다운으로 써라.\n"
                  "형식: '## 세션 요약' 아래 5~10개 불릿(주요 사건 순서대로), '## 남은 떡밥' 2~5개 불릿, "
                  "'## IP 제안' 캐릭터별 한 줄(스킬명 +IP, 이유). GM 비밀은 쓰지 마라.\n\n" + log)
        md = prov.chat([("너는 사이버펑크 2020 GM 의 기록 담당이다.", False)], [{"role": "user", "content": prompt}])
        with open(self.session, "a", encoding="utf-8") as f:
            f.write("\n" + md.strip() + "\n")
        return md


# ---------------------------------------------------------------- AI 캐릭터 도우미
def ai_character(concept: str, base: dict, method: str, points: int, pool: dict) -> dict:
    s = store.settings()
    prov = ai_providers.create(s.get("provider") or "claude", s.get("model", ""), max_tokens=3000)
    if prov.missing() or not prov.model:
        raise RuntimeError("먼저 설정에서 AI 를 연결하세요.")
    roles = "\n".join(f"- {k} ({v['ko']}): 특수능력 {v['special']} / 커리어 {', '.join(v['skills'])}" for k, v in D.ROLES.items())
    if method == "cinematic":
        rule = f"능력치 9개 합계 정확히 {points}, 각 2~10"
    elif method == "random":
        rule = f"능력치 9개 합계 정확히 {pool.get('points')}, 각 2~10"
    else:
        rule = f"능력치 9개에 다음 숫자를 하나씩 배치: {pool.get('values')}"
    prompt = f"""사이버펑크 2020 캐릭터를 만들어라. 플레이어의 콘셉트: {concept or '(자유)'}
현재 입력된 값(참고, 비어 있으면 자유): {json.dumps({k: base.get(k) for k in ('handle', 'role', 'name', 'age')}, ensure_ascii=False)}

규칙
- {rule}. 능력치 키: {', '.join(D.STAT_KEYS)}
- role 은 다음 중 하나:
{roles}
- career: 특수능력 + 커리어 스킬 9개에 정확히 40점(각 0~10, 특수능력 최소 1). "A|B" 는 하나를 골라 그 이름으로, TECH_CHOICE 는 {', '.join(D.TECH_CHOICES)} 중에서.
- pickup: 커리어가 아닌 스킬에 (REF+INT) 점 이하. 스킬 이름은 [스킬 목록]의 영어 이름 그대로.
- cyberware: [{{"name": "", "hl": 휴머니티 손실 숫자, "cost": eb}}] 1~3개, gear: 장비 목록 문자열(줄바꿈 구분, 가격 eb 포함), 합계가 시작 자금 범위(약 2000~6000eb) 안.
- notes: 성격·외모·말버릇 2~3문장 (한국어)
[스킬 목록] {json.dumps(D.SKILLS, ensure_ascii=False)}

JSON 객체 하나만 출력: {{"handle","name","age","role","stats":{{}},"career":{{}},"pickup":{{}},"cyberware":[],"gear":"","notes":""}}"""
    gear_rules = book.retrieve("weapons armor cyberware cost eurodollars humanity cost handgun jacket gear list "
                               + concept, budget_chars=16000, k=10) or "(룰북 미등록)"
    reply = prov.chat([("너는 사이버펑크 2020 캐릭터 생성 도우미다. 요청한 JSON 만 출력한다.", False),
                       (f"# 장비·사이버웨어 참고\n{gear_rules}", True)],
                      [{"role": "user", "content": prompt}])
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        raise RuntimeError("AI 응답에서 JSON 을 찾지 못했습니다.")
    data = json.loads(m.group(0))
    ch = {**base, **{k: v for k, v in data.items() if v not in (None, "")}}
    ch["stats"] = {k: int(ch.get("stats", {}).get(k, 0) or 0) for k in D.STAT_KEYS}
    return {"character": ch, "problems": chargen.validate(ch, method, points)}
