"""캐릭터 생성 규칙: 능력치 굴림, 파생치, 검증, 라이프패스, 시작 자금, 시트 출력."""
import random
import re

from . import chargen_data as D

def _roles() -> dict:
    try:
        return D.ROLES
    except D.BookMissing:
        return {}


def _skill_stat() -> dict:
    try:
        return D.SKILL_STAT
    except D.BookMissing:
        return {}


BTM_TABLE = [(2, 0, "매우 약함"), (4, -1, "약함"), (7, -2, "보통"), (9, -3, "강함"), (10, -4, "매우 강함")]


def d10(rng=random):
    return rng.randint(1, 10)


# ---------------------------------------------------------------- 능력치
def roll_stats(method: str, rng=random) -> dict:
    if method == "random":
        rolls = [d10(rng) for _ in range(9)]
        return {"method": "random", "rolls": rolls, "points": sum(rolls)}
    if method == "fast":
        vals = []
        for _ in range(9):
            v = d10(rng)
            while v <= 2:
                v = d10(rng)
            vals.append(v)
        return {"method": "fast", "values": sorted(vals, reverse=True)}
    raise ValueError("알 수 없는 방식")


def derived(ch: dict) -> dict:
    st = ch.get("stats", {})
    ma, body, emp = st.get("MA", 0) or 0, st.get("BODY", 0) or 0, st.get("EMP", 0) or 0
    hl = sum(int(c.get("hl") or 0) for c in ch.get("cyberware", []))
    humanity = emp * 10 - hl
    cur_emp = max(0, -(-humanity // 10)) if humanity > 0 else 0   # 올림: 10 잃을 때마다 −1
    btm, btm_label = 0, ""
    for limit, mod, label in BTM_TABLE:
        if body <= limit:
            btm, btm_label = mod, label
            break
    run = ma * 3
    return {"run": run, "leap": run // 4, "humanity": humanity, "humanity_max": emp * 10, "hl": hl,
            "emp_current": min(emp, cur_emp), "btm": btm, "body_label": btm_label, "save": body,
            "carry": body * 10, "lift": body * 40, "pickup_points": (st.get("INT", 0) or 0) + (st.get("REF", 0) or 0)}


def career_skill_slots(role: str) -> list[str]:
    r = D.ROLES.get(role)
    if not r:
        return []
    return [r["special"]] + r["skills"]


def validate(ch: dict, method: str, points: int = 75) -> list[str]:
    """문제 목록(빈 리스트면 OK)."""
    errs = []
    st = ch.get("stats", {})
    vals = [st.get(k) for k in D.STAT_KEYS]
    if any(not isinstance(v, int) for v in vals):
        errs.append("능력치 9개를 모두 입력하세요.")
        return errs
    if any(v < 2 or v > 10 for v in vals):
        errs.append("능력치는 2~10 사이여야 합니다.")
    pool = ch.get("stat_pool") or {}
    if method == "cinematic" and sum(vals) != points:
        errs.append(f"능력치 합계가 {sum(vals)} 입니다 ({points} 이어야 함).")
    if method == "random" and pool.get("points") and sum(vals) != pool["points"]:
        errs.append(f"능력치 합계가 {sum(vals)} 입니다 (굴린 값 {pool['points']} 이어야 함).")
    if method == "fast" and pool.get("values") and sorted(vals) != sorted(pool["values"]):
        errs.append("굴린 숫자 9개를 능력치에 하나씩 배치하세요.")
    role = ch.get("role")
    if role not in D.ROLES:
        errs.append("역할을 고르세요.")
    else:
        career = ch.get("career", {})
        total = sum(int(v or 0) for v in career.values())
        if total != 40:
            errs.append(f"커리어 스킬 포인트 {total}/40 – 40점을 모두 쓰세요.")
        if int(career.get(D.ROLES[role]["special"], 0) or 0) < 1:
            errs.append(f"특수능력 {D.ROLES[role]['special']} 에 최소 1점을 주세요.")
        pick = ch.get("pickup", {})
        ptotal = sum(int(v or 0) for v in pick.values())
        allowed = derived(ch)["pickup_points"]
        if ptotal > allowed:
            errs.append(f"픽업 스킬 {ptotal}/{allowed} – 초과했습니다.")
        if set(pick) & set(career):
            errs.append("픽업 스킬 포인트는 커리어 스킬에 쓸 수 없습니다.")
    for sk, v in {**ch.get("career", {}), **ch.get("pickup", {})}.items():
        if int(v or 0) > 10:
            errs.append(f"{sk}: 시작 시 스킬은 최대 10 입니다.")
    cash = (ch.get("money") or {}).get("cash")
    spent = sum(int(i.get("cost") or 0) * int(i.get("qty") or 1) for i in ch.get("items", []))
    if cash and spent > cash:
        errs.append(f"장비·사이버웨어 예산 초과: {spent:,}eb 사용 / 시작 자금 {cash:,}eb")
    if not (ch.get("handle") or "").strip():
        errs.append("핸들(별명)을 입력하세요.")
    return errs


# ---------------------------------------------------------------- 시작 자금
def starting_money(role: str, special_level: int, rng=random) -> dict:
    table = D.SALARY.get(role)
    if not table:
        return {}
    lvl = max(1, min(10, int(special_level or 1)))
    salary = table[0] if lvl <= 5 else table[lvl - 5]
    roll = rng.randint(1, 6)
    months = max(1, roll // 3)
    job = rng.randint(1, 6)
    return {"salary": salary, "months_roll": roll, "months": months, "cash": salary * months,
            "job_roll": job, "unemployed": job >= 5}


# ---------------------------------------------------------------- 라이프패스
def _t(key, rng):
    return D.LP[key][d10(rng) - 1]


def _fill(text, rng):
    return text.replace("{d10x100}", str(d10(rng) * 100)).replace("{d10}", str(d10(rng)))


def roll_lifepath(age: int | None = None, rng=random) -> dict:
    lp = {}
    lp["style"] = f"옷: {_t('clothes', rng)} / 머리: {_t('hair', rng)} / 장식: {_t('affectation', rng)}"
    lp["ethnic"] = _t("ethnic", rng)
    fam = [f"가문: {_t('family_rank', rng)}"]
    if d10(rng) >= 7:
        fam.append(f"부모: {_t('parent_fate', rng)}")
    else:
        fam.append("부모: 생존")
    if d10(rng) <= 6:
        fam.append(f"가문의 위기: {_t('family_tragedy', rng)}")
    else:
        fam.append("가문 상태: 무난함")
    fam.append(f"유년기: {_t('childhood', rng)}")
    n = d10(rng)
    if n >= 8:
        fam.append("형제: 외동")
    else:
        sib = []
        for _ in range(n):
            sex = "남" if d10(rng) % 2 == 0 else "여"
            a = d10(rng)
            rel = "손위" if a <= 5 else "손아래" if a <= 9 else "쌍둥이"
            sib.append(f"{rel} {sex}형제({_t('sibling_feel', rng)})")
        fam.append("형제: " + ", ".join(sib))
    lp["family"] = fam
    lp["motivations"] = [f"성격: {_t('personality', rng)}", f"가장 소중한 사람: {_t('valued_person', rng)}",
                         f"가장 중시하는 것: {_t('value', rng)}", f"사람들에 대한 감정: {_t('feel_people', rng)}",
                         f"아끼는 소지품: {_t('possession', rng)}"]
    if age is None:
        age = rng.randint(1, 6) + rng.randint(1, 6) + 16
    events = []
    for year in range(17, age + 1):
        r = d10(rng)
        if r <= 3:
            if d10(rng) % 2 == 0:
                text = "행운 – " + _fill(_t("lucky", rng), rng)
            else:
                i = d10(rng) - 1
                text = "재난 – " + _fill(D.LP["disaster"][i], rng)
                if i in D.LP["disaster_detail"]:
                    text += f" ({_fill(D.LP['disaster_detail'][i][d10(rng) - 1], rng)})"
                text += f" → {_t('disaster_response', rng)}"
        elif r <= 6:
            if d10(rng) <= 5:
                text = f"친구 – {_t('friend', rng)}"
            else:
                text = (f"적 – {_t('enemy_who', rng)} / 원인: {_t('enemy_cause', rng)} / {_t('enemy_angry', rng)} / "
                        f"마주치면: {_t('enemy_do', rng)} / 동원 전력: {_t('enemy_power', rng)}")
        elif r <= 8:
            kind = _t("romance", rng)
            text = f"연애 – {kind}"
            if kind.startswith("비극"):
                text += f": {_t('romance_tragic', rng)} → {_t('mutual', rng)}"
            elif kind.startswith("문제"):
                text += f": {_t('romance_problem', rng)}"
        else:
            text = "별일 없는 한 해"
        events.append({"age": year, "text": text})
    lp["age"] = age
    lp["events"] = events
    return lp


# ---------------------------------------------------------------- 출력
def skill_line(skills: dict, st: dict) -> str:
    parts = []
    for sk, v in sorted(skills.items(), key=lambda x: -int(x[1] or 0)):
        if int(v or 0) > 0:
            stat = _skill_stat().get(re.sub(r"\s*\(.*\)$", "", sk), "")
            base = st.get(stat, 0) if stat in st else 0
            parts.append(f"{sk} +{v}" + (f" ({stat} {base}→계 {base + int(v)})" if stat in st else ""))
    return ", ".join(parts) or "-"


def to_markdown(ch: dict, full=True) -> str:
    st, dv = ch.get("stats", {}), derived(ch)
    role = _roles().get(ch.get("role"), {})
    lines = [f"# {ch.get('handle', '')} – {role.get('ko', ch.get('role', ''))} ({ch.get('role', '')})", ""]
    lines += [f"**플레이어:** {ch.get('player', '')}  ", f"**본명/나이:** {ch.get('name', '')} / {ch.get('age', '')}", ""]
    lines += ["## 능력치", "| " + " | ".join(D.STAT_KEYS) + " |", "|" + "---|" * 9,
              "| " + " | ".join(str(st.get(k, "")) for k in D.STAT_KEYS) + " |", ""]
    lines += [f"- RUN {dv['run']}m / LEAP {dv['leap']}m",
              f"- 휴머니티 {dv['humanity']}/{dv['humanity_max']} (현재 EMP {dv['emp_current']})",
              f"- Save {dv['save']} / BTM {dv['btm']} ({dv['body_label']})",
              f"- 운반 {dv['carry']}kg / 데드리프트 {dv['lift']}kg", ""]
    lines += ["## 스킬", f"- 특수능력: {role.get('special', '')} +{ch.get('career', {}).get(role.get('special', ''), 0)}",
              f"- 커리어: {skill_line({k: v for k, v in ch.get('career', {}).items() if k != role.get('special')}, st)}",
              f"- 픽업: {skill_line(ch.get('pickup', {}), st)}", ""]
    if ch.get("cyberware"):
        lines += ["## 사이버웨어"] + [f"- {c.get('name', '')} (휴머니티 −{c.get('hl', 0)})" for c in ch["cyberware"]] + [""]
    if ch.get("gear"):
        lines += ["## 장비"] + [f"- {g.strip()}" for g in str(ch["gear"]).splitlines() if g.strip()] + [""]
    m = ch.get("money") or {}
    if m:
        lines += ["## 자금", f"- 현금 {m.get('cash', 0)}eb (월급 {m.get('salary', 0)}eb × {m.get('months', 0)}개월)"
                  + (" – 현재 실직 중" if m.get("unemployed") else ""), ""]
    lp = ch.get("lifepath") or {}
    if full and lp:
        lines += ["## 라이프패스"] + ([lp["story"], ""] if lp.get("story") else []) + [f"- 스타일: {lp.get('style', '')}", f"- 출신: {lp.get('ethnic', '')}"]
        lines += [f"- {x}" for x in lp.get("family", [])] + [f"- {x}" for x in lp.get("motivations", [])]
        ev = [e for e in lp.get("events", []) if "별일 없는" not in e.get("text", "")]
        if ev:
            lines += ["", "### 인생 사건"] + [f"- {e['age']}세: {e['text']}" for e in ev]
        lines.append("")
    if ch.get("notes"):
        lines += ["## 메모", str(ch["notes"]), ""]
    return "\n".join(lines)


LOC_KO = {"head": "머리", "torso": "몸통", "rarm": "오른팔", "larm": "왼팔", "rleg": "오른다리", "lleg": "왼다리"}


def gm_summary(ch: dict) -> str:
    """AI GM 에게 줄 압축 시트."""
    st, dv = ch.get("stats", {}), derived(ch)
    role = _roles().get(ch.get("role"), {})
    lp = ch.get("lifepath") or {}
    hooks = [e["text"] for e in lp.get("events", []) if e.get("text", "").startswith(("재난", "적", "연애 – 비극", "연애 – 문제"))]
    s = ch.get("status", {})
    return "\n".join([
        f"### {ch.get('handle')} (플레이어: {ch.get('player', '')}) – {ch.get('role')}",
        "능력치: " + " ".join(f"{k}{st.get(k, '')}" for k in D.STAT_KEYS),
        f"파생: RUN {dv['run']} / BTM {dv['btm']} / Save {dv['save']} / 휴머니티 {dv['humanity']}",
        f"특수능력: {role.get('special', '')} +{ch.get('career', {}).get(role.get('special', ''), 0)}",
        "스킬: " + skill_line({k: v for k, v in {**ch.get('career', {}), **ch.get('pickup', {})}.items()
                              if k != role.get('special')}, st),
        "사이버웨어: " + (", ".join(c.get("name", "") for c in ch.get("cyberware", [])) or "없음"),
        "장비: " + (" / ".join(g.strip() for g in str(ch.get("gear", "")).splitlines() if g.strip()) or "-"),
        *([("부위별 받은 피해: " + ", ".join(f"{LOC_KO.get(k, k)} {v}" for k, v in s["loc_damage"].items()))] if s.get("loc_damage") else []),
        *([("절단·파괴된 부위: " + ", ".join(LOC_KO.get(k, k) for k in s["severed"]))] if s.get("severed") else []),
        *([("상태이상·버프: " + "; ".join(f"{c.get('name')}({c.get('kind', '')}{' – ' + c['why'] if c.get('why') else ''})" for c in s["conditions"]))] if s.get("conditions") else []),
        f"상태: 피해 {s.get('damage', 0)}/40(현재 누적값 – DAMAGE·HEAL 반영 완료), LUCK 사용 {s.get('luck_used', 0)}/{st.get('LUCK', 0)}, Rep {s.get('rep', 0)}",
        "라이프패스 훅: " + ("; ".join(hooks[:5]) or "-"),
        *([f"배경 이야기: {str(lp['story'])[:600]}"] if lp.get("story") else []),
    ])
