"""AI 가 만든 JSON 을 너그럽게 읽기.

AI 는 가끔 문자열 안의 큰따옴표를 이스케이프하지 않거나(예: Nelspot "Wombat"), 끝에 쉼표를 남기거나,
출력이 길어 끝이 잘린 JSON 을 낸다. 표준 json 으로 먼저 읽고, 실패하면 json-repair 로 고쳐 읽는다.
"""
import json
import re


def extract(reply: str):
    """응답에서 JSON 객체 부분과 오류 메시지를 꺼낸다. (dict | None, 오류 문자열)"""
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        start = (reply or "").find("{")       # 끝이 잘려 닫는 괄호가 없는 경우
        if start < 0:
            return None, "AI 응답에서 JSON 을 찾지 못했습니다"
        text = reply[start:]
    else:
        text = m.group(0)
    try:
        d = json.loads(text)
        return (d, "") if isinstance(d, dict) else (None, "AI 응답이 JSON 객체가 아닙니다")
    except json.JSONDecodeError as e:
        err = f"AI 가 만든 JSON 이 올바르지 않습니다({e})"
    try:
        import json_repair
        d = json_repair.loads(text)
        if isinstance(d, dict) and d:
            return d, ""
    except Exception:  # noqa: BLE001
        pass
    return None, err


RETRY_HINT = ("\n\n주의: 직전 응답이 올바른 JSON 이 아니었다({err}). 문자열 안의 큰따옴표는 \\\" 로 이스케이프하거나 "
              "작은따옴표로 바꾸고, 끝 쉼표 없이 JSON 객체 하나만 다시 출력하라.")
