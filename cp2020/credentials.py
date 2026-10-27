"""API 키·토큰 관리.

우선순위: 이번 실행 메모리 → 환경변수 → .env.local(저장소 루트, git 제외, 권한 600)
웹 화면에서 입력할 때 '이 컴퓨터에 저장'을 고르면 .env.local 에 저장하고, 아니면 실행 중에만 기억한다.
값은 절대 브라우저로 되돌려 보내지 않는다(설정 여부만 알려줌).
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"
_memory: dict[str, str] = {}

# 화면에 보여줄 이름
LABELS = {
    "ANTHROPIC_API_KEY": "Anthropic API 키",
    "OPENAI_API_KEY": "OpenAI API 키",
    "GEMINI_API_KEY": "Gemini API 키",
    "OLLAMA_URL": "Ollama 주소",
    "COMPAT_BASE_URL": "OpenAI 호환 API 주소",
    "COMPAT_API_KEY": "OpenAI 호환 API 키",
    "NOTION_TOKEN": "Notion API 토큰",
}
SECRET = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "COMPAT_API_KEY", "NOTION_TOKEN"}


def read_env_file() -> dict:
    data = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def _write(data: dict):
    if not data:
        if ENV_FILE.exists():
            ENV_FILE.unlink()
        return
    ENV_FILE.write_text("# 로컬 전용 – 절대 커밋하지 마세요 (.gitignore 대상)\n"
                        + "".join(f"{k}={v}\n" for k, v in data.items()), encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def get(name: str, default: str = "") -> str:
    return _memory.get(name) or os.environ.get(name) or read_env_file().get(name) or default


def source(name: str) -> str:
    """'memory' | 'env' | 'file' | ''"""
    if _memory.get(name):
        return "memory"
    if os.environ.get(name):
        return "env"
    if read_env_file().get(name):
        return "file"
    return ""


def set(name: str, value: str, persist: bool):
    value = (value or "").strip()
    if not value:
        return
    _memory[name] = value
    if persist:
        data = read_env_file()
        data[name] = value
        _write(data)


def forget(names=None):
    """names=None 이면 전부."""
    names = list(names or list(LABELS) + list(read_env_file()))
    for n in names:
        _memory.pop(n, None)
    data = {k: v for k, v in read_env_file().items() if k not in names}
    _write(data)


def status() -> dict:
    return {k: source(k) for k in LABELS}
