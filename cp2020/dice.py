"""사이버펑크 2020 주사위.

표현식: NdM, NdM+K, NdM-K, NdM/K(나눗셈 내림), 대소문자 무관. 예) 1D10+14, 3d6, 1D6/2, 2D6+3
- 1D10 단독 굴림(N=1, M=10)은 2020 규칙 적용: 자연 10 → 1D10 추가(크리티컬), 자연 1 → 펌블 표시
- 결과가 0 이하가 되면 1 (룰북의 수정 주사위 규칙)
"""
import random
import re

PATTERN = re.compile(r"^\s*(\d*)\s*[dD]\s*(\d+)\s*(?:([+\-/])\s*(\d+))?\s*$")


class DiceError(ValueError):
    pass


def roll(expr: str, rng=random, crit: bool = True) -> dict:
    """crit=False: 부위·피해·세이브·표 굴림처럼 크리티컬/펌블이 없는 굴림."""
    m = PATTERN.match(expr)
    if not m:
        raise DiceError(f"주사위 표현식을 이해하지 못했습니다: {expr!r} (예: 1D10+14, 3D6, 1D6/2)")
    n = int(m.group(1) or 1)
    sides = int(m.group(2))
    op, k = m.group(3), int(m.group(4) or 0)
    if not (1 <= n <= 100 and 2 <= sides <= 1000):
        raise DiceError("주사위 개수 1~100, 면 수 2~1000 범위만 지원합니다.")
    faces = [rng.randint(1, sides) for _ in range(n)]
    note = ""
    extra = []
    if crit and n == 1 and sides == 10:
        if faces[0] == 10:
            extra = [rng.randint(1, 10)]
            note = "크리티컬! (자연 10 → 1D10 추가)"
        elif faces[0] == 1:
            note = "펌블! (자연 1 → 펌블 표 1D10)"
    total = sum(faces) + sum(extra)
    if op == "+":
        total += k
    elif op == "-":
        total -= k
    elif op == "/":
        total //= max(k, 1)
    if op and total <= 0:
        total = 1
    detail = "+".join(map(str, faces)) + (f"(+{extra[0]})" if extra else "")
    mod = f"{op}{k}" if op else ""
    return {"expr": expr.strip().upper(), "faces": faces, "extra": extra, "total": total,
            "note": note, "text": f"{expr.strip().upper()} = [{detail}]{mod} → **{total}**" + (f"  {note}" if note else "")}
