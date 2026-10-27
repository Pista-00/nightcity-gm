"""AI 제공자 연결 – 어떤 AI로 GM을 돌릴지 고를 수 있게 하는 공통 인터페이스.

지원
- claude-code : Claude 구독 계정(Pro·Max 등) – 내 컴퓨터에 설치·로그인한 Claude Code 를 통해 호출 (기본, 키 불필요)
- chatgpt-codex : ChatGPT 계정 – 내 컴퓨터에 설치·로그인한 OpenAI Codex CLI 를 통해 호출 (키 불필요)
- claude  : Anthropic Messages API (룰북 시스템 프롬프트에 프롬프트 캐싱 적용)
- openai  : OpenAI Chat Completions API
- gemini  : Google Gemini API (generateContent)
- ollama  : 내 컴퓨터의 Ollama (키 불필요, 기본 http://localhost:11434)
- compat  : OpenAI 호환 API (OpenRouter, LM Studio, vLLM 등 – 주소와 키를 입력)

모든 제공자는 같은 형식을 쓴다.
  messages = [{"role": "user"|"assistant", "content": "..."}]
  provider.chat(system_blocks, messages) -> str
system_blocks = [(텍스트, 캐시여부)] – 큰 고정 블록(룰북)은 캐시 대상으로 표시.
키는 credentials 에서 읽는다(웹 화면에서 입력). 각 제공자의 NEEDS 에 필요한 값이 정의돼 있다.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time

import requests

from . import credentials

TIMEOUT = 300


class ProviderError(RuntimeError):
    pass


def _check(r: requests.Response):
    if not r.ok:
        raise ProviderError(f"{r.status_code}: {r.text[:600]}")
    return r.json()


class Provider:
    name = ""
    kind = "api"          # "subscription" | "api"
    label = ""
    default_model = ""
    NEEDS: list[tuple[str, bool]] = []   # (키 이름, 필수 여부)
    hint = ""

    def __init__(self, model: str = "", max_tokens: int = 2000, temperature: float = 0.9):
        self.model = model or self.default_model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def missing(self) -> list[str]:
        return [k for k, req in self.NEEDS if req and not credentials.get(k)]

    def connect(self) -> bool:
        """키를 읽어 온다. 필요한 값이 없으면 False."""
        return not self.missing()

    def list_models(self) -> list[str]:
        return []

    def chat(self, system_blocks, messages) -> str:
        raise NotImplementedError

    @staticmethod
    def join_system(system_blocks) -> str:
        return "\n\n".join(t for t, _ in system_blocks if t)


# ---------------------------------------------------------------- Claude
class Claude(Provider):
    name, label = "claude", "Claude API (Anthropic 키)"
    default_model = "claude-sonnet-5-5"
    URL = "https://api.anthropic.com/v1"

    NEEDS = [("ANTHROPIC_API_KEY", True)]
    hint = "console.anthropic.com → API Keys"

    def _h(self):
        return {"x-api-key": credentials.get("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"}

    def list_models(self):
        data = _check(requests.get(f"{self.URL}/models", headers=self._h(), params={"limit": 100}, timeout=30))
        return [m["id"] for m in data.get("data", [])]

    def chat(self, system_blocks, messages):
        system = []
        for text, cache in system_blocks:
            if not text:
                continue
            b = {"type": "text", "text": text}
            if cache:
                b["cache_control"] = {"type": "ephemeral"}
            system.append(b)
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system, "messages": messages}
        data = _check(requests.post(f"{self.URL}/messages", headers=self._h(), json=body, timeout=TIMEOUT))
        return "".join(c.get("text", "") for c in data.get("content", []) if c.get("type") == "text")


# ---------------------------------------------------------------- OpenAI / 호환
class OpenAI(Provider):
    name, label = "openai", "GPT (OpenAI)"
    default_model = ""  # 목록에서 선택
    URL = "https://api.openai.com/v1"
    KEY = "OPENAI_API_KEY"
    token_param = "max_completion_tokens"

    NEEDS = [("OPENAI_API_KEY", True)]
    hint = "platform.openai.com → API keys"

    @property
    def base(self):
        return self.URL

    def _h(self):
        h = {"Content-Type": "application/json"}
        key = credentials.get(self.KEY)
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def list_models(self):
        data = _check(requests.get(f"{self.base}/models", headers=self._h(), timeout=30))
        return sorted(m["id"] for m in data.get("data", []))

    def chat(self, system_blocks, messages):
        msgs = [{"role": "system", "content": self.join_system(system_blocks)}] + messages
        body = {"model": self.model, "messages": msgs, self.token_param: self.max_tokens}
        data = _check(requests.post(f"{self.base}/chat/completions", headers=self._h(), json=body, timeout=TIMEOUT))
        return data["choices"][0]["message"].get("content") or ""


class Compat(OpenAI):
    name, label = "compat", "OpenAI 호환 API (OpenRouter·LM Studio 등)"
    token_param = "max_tokens"
    KEY = "COMPAT_API_KEY"
    NEEDS = [("COMPAT_BASE_URL", True), ("COMPAT_API_KEY", False)]
    hint = "예: https://openrouter.ai/api/v1 , http://localhost:1234/v1 (LM Studio)"

    @property
    def base(self):
        return credentials.get("COMPAT_BASE_URL").rstrip("/")


# ---------------------------------------------------------------- Gemini
class Gemini(Provider):
    name, label = "gemini", "Gemini (Google)"
    default_model = ""
    URL = "https://generativelanguage.googleapis.com/v1beta"

    NEEDS = [("GEMINI_API_KEY", True)]
    hint = "aistudio.google.com → Get API key"

    def _h(self):
        return {"x-goog-api-key": credentials.get("GEMINI_API_KEY"), "Content-Type": "application/json"}

    def list_models(self):
        data = _check(requests.get(f"{self.URL}/models", headers=self._h(), params={"pageSize": 200}, timeout=30))
        return [m["name"].removeprefix("models/") for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]

    def chat(self, system_blocks, messages):
        contents = [{"role": "model" if m["role"] == "assistant" else "user",
                     "parts": [{"text": m["content"]}]} for m in messages]
        body = {"systemInstruction": {"parts": [{"text": self.join_system(system_blocks)}]},
                "contents": contents,
                "generationConfig": {"maxOutputTokens": self.max_tokens, "temperature": self.temperature}}
        data = _check(requests.post(f"{self.URL}/models/{self.model}:generateContent",
                                    headers=self._h(), json=body, timeout=TIMEOUT))
        cands = data.get("candidates") or []
        if not cands:
            raise ProviderError(f"응답 없음: {str(data)[:300]}")
        return "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))


# ---------------------------------------------------------------- Ollama
class Ollama(Provider):
    name, label = "ollama", "Ollama (내 컴퓨터의 로컬 모델)"
    default_model = ""

    NEEDS = [("OLLAMA_URL", False)]
    hint = "내 컴퓨터에서 Ollama 실행 (기본 http://localhost:11434). 긴 문맥 모델 권장"

    @property
    def URL(self):
        return credentials.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")

    def list_models(self):
        data = _check(requests.get(f"{self.URL}/api/tags", timeout=10))
        return [m["name"] for m in data.get("models", [])]

    def chat(self, system_blocks, messages):
        msgs = [{"role": "system", "content": self.join_system(system_blocks)}] + messages
        body = {"model": self.model, "messages": msgs, "stream": False,
                "options": {"num_ctx": 32768, "num_predict": self.max_tokens, "temperature": self.temperature}}
        data = _check(requests.post(f"{self.URL}/api/chat", json=body, timeout=TIMEOUT))
        return data.get("message", {}).get("content", "")


# ---------------------------------------------------------------- Claude 구독 계정 (Claude Code)
class ClaudeCode(Provider):
    """Claude Code CLI 의 헤드리스 모드(claude -p)를 호출한다.

    - 인증은 사용자가 한 번 해 둔 Claude Code 로그인(구독 계정)을 그대로 쓴다. API 키 불필요.
    - 도구·MCP·설정 파일을 모두 끈 상태로, 빈 임시 폴더에서 '대화 모델'로만 쓴다.
    - 대화 기록은 매번 하나의 텍스트로 묶어 보낸다(세션 저장 안 함).
    """
    name, kind, label = "claude-code", "subscription", "Claude 구독 계정 (Claude Code 로그인)"
    default_model = "sonnet"
    hint = "Pro·Max·Team 등 유료 Claude 구독으로 사용 – API 키 불필요 (무료 플랜 불가)"
    MODELS = ["sonnet", "opus", "haiku"]
    _status_cache: tuple[float, dict] | None = None

    @staticmethod
    def binary():
        """claude 실행 파일 찾기. 더블클릭 실행 등으로 PATH 가 짧아도 흔한 설치 위치를 직접 확인한다."""
        if os.environ.get("CLAUDE_CODE_BIN"):
            return os.environ["CLAUDE_CODE_BIN"]
        found = shutil.which("claude")
        if found:
            return found
        home = os.path.expanduser("~")
        cands = [
            f"{home}/.local/bin/claude",            # 공식 설치 스크립트 (맥·리눅스)
            f"{home}/.claude/local/claude",          # 예전 로컬 설치
            "/opt/homebrew/bin/claude",              # Homebrew (Apple Silicon)
            "/usr/local/bin/claude",                 # Homebrew (Intel) / npm
            f"{home}/.npm-global/bin/claude",
            f"{home}/.bun/bin/claude",
            os.path.join(home, ".local", "bin", "claude.exe"),                       # 윈도우 공식 설치
            os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd"),         # 윈도우 npm
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", "claude.exe"),
        ]
        for c in cands:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        # 마지막으로 로그인 셸의 PATH 로 찾기 (zsh/bash 설정에만 PATH 가 있는 경우)
        if os.name != "nt":
            for sh in ("/bin/zsh", "/bin/bash"):
                if os.path.exists(sh):
                    try:
                        r = subprocess.run([sh, "-lic", "command -v claude"], capture_output=True, text=True, timeout=10)
                        path = (r.stdout.strip().splitlines() or [""])[-1]
                        if path.startswith("/") and os.path.isfile(path):
                            return path
                    except Exception:  # noqa: BLE001
                        pass
        return None

    @staticmethod
    def _env():
        # 다른 Claude Code 세션 안에서 실행될 때 그 세션의 설정·기억이 섞이지 않도록 CLAUDE* 변수 제거
        # (인증·프록시·설정 폴더 관련 값만 유지)
        keep = ("OAUTH", "TOKEN", "BASE_URL", "CONFIG_DIR", "CA_CERT", "PROXY")
        env = {k: v for k, v in os.environ.items()
               if not (k.startswith("CLAUDE") and not any(x in k for x in keep))}
        # API 키가 환경에 있으면 Claude Code 가 그걸 쓰므로, 구독 로그인을 쓰도록 제거
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        # npm 으로 설치한 경우 같은 폴더의 node 가 필요하므로 claude 가 있는 폴더를 PATH 앞에 추가
        exe = ClaudeCode.binary()
        if exe:
            env["PATH"] = os.path.dirname(exe) + os.pathsep + env.get("PATH", "")
        return env

    @classmethod
    def status(cls, refresh=False) -> dict:
        if cls._status_cache and not refresh and time.time() - cls._status_cache[0] < 60:
            return cls._status_cache[1]
        exe = cls.binary()
        st = {"installed": bool(exe), "loggedIn": False, "authMethod": "", "version": ""}
        if exe:
            try:
                v = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8",
                                   timeout=30, env=cls._env())
                st["version"] = v.stdout.strip().split("\n")[0]
                a = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True,
                                   encoding="utf-8", timeout=30, env=cls._env())
                data = json.loads(a.stdout[a.stdout.find("{"):] or "{}")
                st["loggedIn"] = bool(data.get("loggedIn"))
                st["authMethod"] = data.get("authMethod", "")
            except Exception as e:  # noqa: BLE001
                st["error"] = str(e)[:200]
        cls._status_cache = (time.time(), st)
        return st

    def missing(self):
        st = self.status()
        if not st["installed"]:
            return ["Claude Code 설치"]
        if not st["loggedIn"]:
            return ["Claude Code 로그인"]
        return []

    def list_models(self):
        return list(self.MODELS)

    @staticmethod
    def _as_prompt(messages) -> str:
        if len(messages) == 1:
            return messages[0]["content"]
        parts = ["아래는 지금까지의 진행 기록이다. 마지막 [플레이어] 입력에 GM 으로서 답하라.\n"]
        for m in messages:
            parts.append(f"[{'GM' if m['role'] == 'assistant' else '플레이어'}]\n{m['content']}\n")
        return "\n".join(parts)

    def chat(self, system_blocks, messages):
        exe = self.binary()
        if not exe:
            raise ProviderError("Claude Code 가 설치되어 있지 않습니다.")
        with tempfile.TemporaryDirectory(prefix="cp2020-gm-") as tmp:
            sys_file = os.path.join(tmp, "system.md")
            with open(sys_file, "w", encoding="utf-8") as f:
                f.write(self.join_system(system_blocks))
            cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--system-prompt-file", sys_file,
                   "--no-session-persistence", "--strict-mcp-config", "--setting-sources", ""]
            if self.model:
                cmd += ["--model", self.model]
            try:
                r = subprocess.run(cmd, input=self._as_prompt(messages), capture_output=True, text=True,
                                   encoding="utf-8", cwd=tmp, timeout=600, env=self._env())
            except subprocess.TimeoutExpired:
                raise ProviderError("Claude Code 응답 시간 초과 (10분)") from None
        out = r.stdout.strip()
        line = next((l for l in reversed(out.splitlines()) if l.startswith("{")), "")
        try:
            data = json.loads(line)
        except ValueError:
            raise ProviderError(f"Claude Code 오류: {(r.stderr or out)[:500]}") from None
        if data.get("is_error") or data.get("subtype") not in (None, "success"):
            hint = out.splitlines()[0] if out else ""
            raise ProviderError(f"Claude Code 오류: {data.get('result') or hint or r.stderr[:300]}")
        return data.get("result", "")


def _find_cli(name: str, env_var: str, extra: list[str]) -> str | None:
    """CLI 실행 파일 찾기: 환경변수 → PATH → 흔한 설치 위치 → 로그인 셸 PATH."""
    if os.environ.get(env_var):
        return os.environ[env_var]
    found = shutil.which(name)
    if found:
        return found
    for c in extra:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    if os.name != "nt":
        for sh in ("/bin/zsh", "/bin/bash"):
            if os.path.exists(sh):
                try:
                    r = subprocess.run([sh, "-lic", f"command -v {name}"], capture_output=True, text=True, timeout=10)
                    path = (r.stdout.strip().splitlines() or [""])[-1]
                    if path.startswith("/") and os.path.isfile(path):
                        return path
                except Exception:  # noqa: BLE001
                    pass
    return None


# ---------------------------------------------------------------- ChatGPT 구독 계정 (Codex CLI)
class ChatGPTCodex(Provider):
    """OpenAI Codex CLI 의 비대화형 모드(codex exec)를 호출한다.

    - 인증은 사용자가 한 번 해 둔 `codex login`(ChatGPT 계정 로그인)을 그대로 쓴다. API 키 불필요.
    - 빈 임시 폴더에서 읽기 전용 샌드박스·사용자 설정 무시·세션 저장 안 함으로 실행하고,
      마지막 답변만 파일로 받아 온다.
    """
    name, kind, label = "chatgpt-codex", "subscription", "ChatGPT 구독 계정 (Codex 로그인)"
    default_model = "default"
    hint = "ChatGPT 계정으로 사용 – API 키 불필요 (사용량은 ChatGPT 요금제 한도에서 차감)"
    MODELS = ["default"]          # default = Codex 기본 모델. 다른 모델은 이름을 직접 입력
    _status_cache: tuple[float, dict] | None = None

    @staticmethod
    def binary():
        home = os.path.expanduser("~")
        return _find_cli("codex", "CODEX_BIN", [
            "/opt/homebrew/bin/codex", "/usr/local/bin/codex", f"{home}/.npm-global/bin/codex",
            f"{home}/.local/bin/codex", f"{home}/.bun/bin/codex",
            os.path.join(os.environ.get("APPDATA", ""), "npm", "codex.cmd"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", "codex.exe"),
        ])

    @classmethod
    def _env(cls):
        env = dict(os.environ)
        env.pop("OPENAI_API_KEY", None)        # ChatGPT 로그인을 쓰도록
        exe = cls.binary()
        if exe:                                # npm 설치면 같은 폴더의 node 필요
            env["PATH"] = os.path.dirname(exe) + os.pathsep + env.get("PATH", "")
        return env

    @classmethod
    def status(cls, refresh=False) -> dict:
        if cls._status_cache and not refresh and time.time() - cls._status_cache[0] < 60:
            return cls._status_cache[1]
        exe = cls.binary()
        st = {"installed": bool(exe), "loggedIn": False, "authMethod": "", "version": ""}
        if exe:
            try:
                v = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8",
                                   timeout=30, env=cls._env())
                st["version"] = v.stdout.strip().split("\n")[0]
                a = subprocess.run([exe, "login", "status"], capture_output=True, text=True, encoding="utf-8",
                                   timeout=30, env=cls._env())
                text = (a.stdout + a.stderr).strip()
                st["loggedIn"] = a.returncode == 0 and "not logged in" not in text.lower()
                low = text.lower()
                st["authMethod"] = "chatgpt" if "chatgpt" in low else ("api_key" if "api key" in low else "")
                st["detail"] = text.splitlines()[0] if text else ""
            except Exception as e:  # noqa: BLE001
                st["error"] = str(e)[:200]
        cls._status_cache = (time.time(), st)
        return st

    def missing(self):
        st = self.status()
        if not st["installed"]:
            return ["Codex CLI 설치"]
        if not st["loggedIn"]:
            return ["Codex 로그인"]
        return []

    def list_models(self):
        return list(self.MODELS)

    def chat(self, system_blocks, messages):
        exe = self.binary()
        if not exe:
            raise ProviderError("Codex CLI 가 설치되어 있지 않습니다.")
        prompt = ("# 지시사항 (반드시 따를 것)\n" + self.join_system(system_blocks) +
                  "\n\n# 중요\n파일을 읽거나 명령을 실행하지 말고, 위 지시에 따라 답변 텍스트만 출력하라.\n\n# 대화\n" +
                  ClaudeCode._as_prompt(messages))
        with tempfile.TemporaryDirectory(prefix="cp2020-gm-") as tmp:
            out = os.path.join(tmp, "answer.txt")
            cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
                   "--ignore-user-config", "--ignore-rules", "--color", "never", "-C", tmp, "-o", out]
            if self.model and self.model != "default":
                cmd += ["-m", self.model]
            cmd.append("-")
            try:
                r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                   cwd=tmp, timeout=600, env=self._env())
            except subprocess.TimeoutExpired:
                raise ProviderError("Codex 응답 시간 초과 (10분)") from None
            answer = open(out, encoding="utf-8").read().strip() if os.path.exists(out) else ""
        if r.returncode != 0 or not answer:
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-5:]
            raise ProviderError("Codex 오류: " + (" / ".join(tail) or f"종료 코드 {r.returncode}"))
        return answer


PROVIDERS = {cls.name: cls for cls in (ClaudeCode, ChatGPTCodex, Claude, OpenAI, Gemini, Ollama, Compat)}


def describe() -> list[dict]:
    return [{"name": c.name, "kind": c.kind, "label": c.label, "default_model": c.default_model, "hint": c.hint,
             "status": c.status() if c.kind == "subscription" else None,
             "needs": [{"key": k, "required": r, "label": credentials.LABELS.get(k, k),
                        "secret": k in credentials.SECRET, "set": bool(credentials.get(k))} for k, r in c.NEEDS]}
            for c in PROVIDERS.values()]


def create(name: str, model: str = "", **kw) -> Provider:
    if name not in PROVIDERS:
        raise ProviderError(f"알 수 없는 제공자: {name} (가능: {', '.join(PROVIDERS)})")
    return PROVIDERS[name](model, **kw)
