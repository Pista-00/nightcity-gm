"""NightCity GM – Cyberpunk 2020 용 비공식 AI GM 로컬 웹 앱.

    pip install -r requirements.txt
    python app.py            → 브라우저가 열림 (http://127.0.0.1:8020)

한 화면에서: AI·Notion 연결 → 캠페인·인원 설정 → 캐릭터 생성 → AI GM 진행.
이 서버는 내 컴퓨터(127.0.0.1)에서만 접속된다. 키는 브라우저로 다시 보내지 않는다.
"""
import argparse
import secrets
import tempfile
import threading
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file

from cp2020 import ai_providers, book, chargen, chargen_data as D, credentials, dice, engine, notion, store

app = Flask(__name__, static_folder="web", static_url_path="/static")
TOKEN = secrets.token_urlsafe(24)
ALLOWED_HOSTS = set()
_locks: dict[str, threading.Lock] = {}


def lock_for(key):
    return _locks.setdefault(key, threading.Lock())


# ---------------------------------------------------------------- 보안: 로컬 + 토큰
@app.before_request
def guard():
    host = (request.host or "").split(":")[0]
    if host not in ("127.0.0.1", "localhost"):
        abort(403)
    if request.path.startswith("/api/") and request.headers.get("X-App-Token") != TOKEN:
        abort(403)


@app.errorhandler(Exception)
def on_error(e):
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    if isinstance(e, D.BookMissing):
        return jsonify({"error": str(e), "book_missing": True}), 409
    msg = getattr(e, "description", None) if code < 500 and hasattr(e, "description") else str(e)
    if code >= 500:
        app.logger.exception(e)   # 터미널에 원인 출력
    return jsonify({"error": msg or e.__class__.__name__}), code


def body():
    return request.get_json(silent=True) or {}


def campaign(cid) -> store.Campaign:
    try:
        return store.Campaign(cid)
    except (ValueError, FileNotFoundError) as e:
        abort(404, str(e))


def session_of(c: store.Campaign, name=None):
    s = c.session_path(name)
    if s is None:
        abort(404, "세션이 없습니다.")
    return s


# ---------------------------------------------------------------- 페이지
@app.get("/")
def index():
    html = (store.ROOT / "web" / "index.html").read_text(encoding="utf-8")
    return html.replace("__APP_TOKEN__", TOKEN)


@app.get("/img/<image_id>")
def image(image_id):
    p = store.library_image(image_id)
    if not p:
        abort(404)
    return send_file(p, max_age=3600)


# ---------------------------------------------------------------- 상태·설정
@app.get("/api/state")
def state():
    s = store.settings()
    return jsonify({
        "settings": s,
        "providers": ai_providers.describe(),
        "credentials": credentials.status(),
        "campaigns": store.Campaign.all(),
        "claude_code": ai_providers.ClaudeCode.status(),
        "rules_modes": engine.RULE_MODES,
        "book": book.status(),
        "catalog": [{"id": i["id"], "title": i.get("title", ""), "tags": i.get("tags", []),
                     "has": bool(store.library_image(i["id"]))} for i in store.catalog()],
    })


@app.post("/api/keys")
def set_keys():
    b = body()
    for k, v in (b.get("keys") or {}).items():
        if k in credentials.LABELS and v:
            credentials.set(k, v, bool(b.get("persist")))
    return jsonify({"credentials": credentials.status()})


@app.post("/api/keys/forget")
def forget_keys():
    credentials.forget(body().get("keys"))
    return jsonify({"credentials": credentials.status()})


@app.post("/api/ai")
def set_ai():
    b = body()
    kw = {k: b[k] for k in ("provider", "model", "rules", "max_tokens", "notion_mode") if k in b}
    if "provider" in kw and kw["provider"] not in ai_providers.PROVIDERS:
        abort(400, "알 수 없는 AI")
    return jsonify({"settings": store.save_settings(**kw)})


@app.post("/api/claude-code/status")
def claude_code_status():
    return jsonify(ai_providers.ClaudeCode.status(refresh=True))


@app.post("/api/sub-status/<name>")
def sub_status(name):
    cls = ai_providers.PROVIDERS.get(name)
    if not cls or cls.kind != "subscription":
        abort(404)
    return jsonify(cls.status(refresh=True))


@app.get("/api/models")
def models():
    p = ai_providers.create(request.args.get("provider", ""))
    if p.missing():
        abort(400, f"먼저 준비하세요: {', '.join(credentials.LABELS.get(k, k) for k in p.missing())}")
    return jsonify({"models": p.list_models(), "default": p.default_model})


@app.post("/api/ai/test")
def ai_test():
    s = store.settings()
    p = ai_providers.create(s["provider"], s.get("model", ""), max_tokens=60)
    reply = p.chat([("짧게 한국어로 답한다.", False)], [{"role": "user", "content": "사이버펑크 2020 GM 준비됐어? 한 문장으로."}])
    return jsonify({"reply": reply})


# ---------------------------------------------------------------- 캠페인
@app.post("/api/campaigns")
def create_campaign():
    b = body()
    name = (b.get("name") or "").strip()
    if not name:
        abort(400, "캠페인 이름을 입력하세요.")
    page = (b.get("notion_page") or "").strip()
    if page:
        notion.parse_page_id(page)
    c = store.Campaign.create(name, page)
    store.save_settings(current_campaign=c.id)
    return jsonify(campaign_view(c))


def campaign_view(c: store.Campaign):
    chars = []
    for ch in c.characters():
        chars.append({**ch, "derived": chargen.derived(ch),
                      "notion": ch["id"] in c.notion_state.get("characters", {})})
    return {"id": c.id, "meta": c.meta, "characters": chars, "drafts": c.drafts,
            "sessions": [p.name for p in c.sessions()],
            "notion_ready": notion.ready(c)}


@app.get("/api/campaign/<cid>")
def get_campaign(cid):
    c = campaign(cid)
    store.save_settings(current_campaign=c.id)
    return jsonify(campaign_view(c))


@app.post("/api/campaign/<cid>/meta")
def update_meta(cid):
    c = campaign(cid)
    b = body()
    allowed = {k: b[k] for k in ("name", "players", "stat_method", "stat_points", "experience", "premise",
                                 "notion_page") if k in b}
    if allowed.get("notion_page"):
        notion.parse_page_id(allowed["notion_page"])
    if "players" in allowed:
        allowed["players"] = [{"name": str(p.get("name", "")).strip()[:40], "character": p.get("character", "")}
                              for p in allowed["players"] if str(p.get("name", "")).strip()]
    c.update(**allowed)
    return jsonify(campaign_view(c))


@app.post("/api/campaign/<cid>/notion/check")
def notion_check(cid):
    c = campaign(cid)
    page = body().get("notion_page") or c.meta.get("notion_page", "")
    if not page:
        abort(400, "Notion 페이지 URL을 입력하세요.")
    return jsonify(notion.check(page))


# ---------------------------------------------------------------- 캐릭터 생성
@app.get("/api/chargen/data")
def chargen_data():
    base = {"stats": D.STATS, "methods": D.STAT_METHODS}
    if not D.ready():   # 룰북 미등록: 표 없이 기본 정보만
        return jsonify({**base, "ready": False, "roles": {}, "skills": {}, "skill_stat": {}, "tech_choices": [],
                        "cinematic": {}})
    return jsonify({**base, "ready": True, "roles": D.ROLES, "skills": D.SKILLS, "skill_stat": D.SKILL_STAT,
                    "tech_choices": D.TECH_CHOICES, "cinematic": {str(k): v for k, v in D.CINEMATIC.items()}})


# ---------------------------------------------------------------- 룰북 등록 (사용자 PDF → 로컬 데이터)
JOBS: dict[str, dict] = {}


def start_job(kind, fn):
    """오래 걸리는 작업을 백그라운드로. 같은 종류는 하나만."""
    cur = JOBS.get(kind)
    if cur and cur["status"] == "running":
        abort(409, "이미 진행 중입니다.")
    job = {"kind": kind, "status": "running", "msg": "시작", "progress": 0.0, "error": "", "started": store.now()}
    JOBS[kind] = job

    def progress(msg, frac):
        job["msg"], job["progress"] = msg, round(float(frac), 3)

    def run():
        try:
            fn(progress)
            job["status"], job["progress"] = "done", 1.0
        except Exception as e:  # noqa: BLE001
            app.logger.exception(e)
            job["status"], job["error"] = "error", str(e)

    threading.Thread(target=run, daemon=True).start()
    return job


@app.get("/api/book")
def book_status():
    return jsonify({"book": book.status(), "jobs": JOBS})


@app.post("/api/book/import")
def book_import():
    f = request.files.get("pdf")
    if not f or not f.filename.lower().endswith(".pdf"):
        abort(400, "PDF 파일을 선택하세요.")
    tmp = tempfile.NamedTemporaryFile(prefix="nc-book-", suffix=".pdf", delete=False)
    f.save(tmp.name)
    tmp.close()
    name = Path(f.filename).name

    def work(progress):
        try:
            book.import_pdf(Path(tmp.name), name, progress)
        finally:
            Path(tmp.name).unlink(missing_ok=True)   # 원본 사본은 남기지 않음
    return jsonify(start_job("import", work))


def _provider_for_book():
    s = store.settings()
    p = ai_providers.create(s.get("provider") or "claude-code", s.get("model", ""), max_tokens=8000)
    if p.missing() or not p.model:
        abort(400, "먼저 ① 에서 AI 를 연결하세요.")
    return p


@app.post("/api/book/chargen")
def book_chargen():
    prov = _provider_for_book()
    return jsonify(start_job("chargen", lambda progress: book.extract_chargen(prov, progress)))


@app.post("/api/book/summary")
def book_summary():
    prov = _provider_for_book()
    return jsonify(start_job("summary", lambda progress: book.build_summary(prov, progress)))


@app.post("/api/book/forget")
def book_forget():
    book.forget()
    JOBS.clear()
    return jsonify({"book": book.status()})


@app.post("/api/chargen/roll_stats")
def roll_stats():
    return jsonify(chargen.roll_stats(body().get("method", "random")))


@app.post("/api/chargen/lifepath")
def lifepath():
    age = body().get("age")
    return jsonify(chargen.roll_lifepath(int(age) if age else None))


@app.post("/api/chargen/money")
def money():
    b = body()
    return jsonify(chargen.starting_money(b.get("role", ""), int(b.get("level") or 1)))


@app.post("/api/chargen/check")
def check_char():
    b = body()
    ch = b.get("character", {})
    return jsonify({"problems": chargen.validate(ch, b.get("method", "cinematic"), int(b.get("points") or 75)),
                    "derived": chargen.derived(ch)})


@app.post("/api/campaign/<cid>/chargen/ai")
def chargen_ai(cid):
    c = campaign(cid)
    b = body()
    meta = c.meta
    return jsonify(engine.ai_character(b.get("concept", ""), b.get("character", {}),
                                       meta.get("stat_method", "cinematic"), int(meta.get("stat_points") or 75),
                                       b.get("character", {}).get("stat_pool") or {}))


@app.post("/api/campaign/<cid>/character")
def save_character(cid):
    c = campaign(cid)
    b = body()
    ch = b.get("character") or {}
    meta = c.meta
    problems = chargen.validate(ch, meta.get("stat_method", "cinematic"), int(meta.get("stat_points") or 75))
    if problems and not b.get("force"):
        return jsonify({"problems": problems, "saved": False})
    ch = c.save_character(ch)
    if b.get("draft_key"):
        c.save_draft(b["draft_key"], None)   # 정식 저장되면 임시본 삭제
    # 플레이어와 연결
    players = meta.get("players", [])
    for p in players:
        if p.get("name") == ch.get("player"):
            p["character"] = ch["id"]
    c.update(players=players)
    result = {"saved": True, "character": ch, "problems": problems}
    if b.get("notion") and notion.ready(c):
        try:
            notion.sync_character(c, ch)
            result["notion"] = "ok"
        except Exception as e:
            result["notion"] = f"Notion 기록 실패: {e}"
    return jsonify(result)


@app.post("/api/campaign/<cid>/draft")
def save_draft(cid):
    c = campaign(cid)
    b = body()
    key = str(b.get("key") or "")[:80]
    if not key:
        abort(400, "key 필요")
    c.save_draft(key, b.get("draft"))
    return jsonify({"ok": True})


@app.delete("/api/campaign/<cid>/character/<chid>")
def delete_character(cid, chid):
    c = campaign(cid)
    c.delete_character(chid)
    return jsonify(campaign_view(c))


@app.post("/api/campaign/<cid>/character/<chid>/status")
def char_status(cid, chid):
    c = campaign(cid)
    ch = c.character(chid) or abort(404)
    st = ch.get("status", {})
    for k in ("damage", "luck_used", "rep", "ip", "cash"):
        if k in body():
            st[k] = int(body()[k] or 0)
    ch["status"] = st
    return jsonify(c.save_character(ch))


@app.post("/api/campaign/<cid>/character/<chid>/notion")
def char_notion(cid, chid):
    c = campaign(cid)
    ch = c.character(chid) or abort(404)
    notion.sync_character(c, ch)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 플레이
def game(c, name):
    return engine.Game(c, session_of(c, name))


@app.get("/api/campaign/<cid>/play")
def play_state(cid):
    c = campaign(cid)
    g = game(c, request.args.get("session"))
    st = c.notion_state
    sent = {(l.get("scene")) for l in st.get("log", []) if l.get("kind") == "scene"}
    return jsonify({"session": g.session.name, "sessions": [p.name for p in c.sessions()],
                    "log": [engine.view(i) for i in g.tr.items], "sent_scenes": sorted(x for x in sent if x),
                    "scenes": [{k: s.get(k) for k in ("id", "title", "image", "location", "time")} for s in c.scenes()],
                    "session_text": g.session.read_text(encoding="utf-8"),
                    "unlogged": (len(g.tr.items) - notion.logged_upto(c, g.session)) if notion.ready(c) else None})


def flush_progress(c, g, upto: int) -> bool:
    """마지막 기록 이후 ~ upto 직전까지의 진행을 AI 로 요약해 Notion 에 기록."""
    notion.sync_session(c, g.session)            # 세션 페이지 확보
    start = min(notion.logged_upto(c, g.session), len(g.tr.items))
    upto = min(upto, len(g.tr.items))
    if upto - start < 2:                           # 기록할 만한 주고받기가 없음
        return False
    md = g.digest(start, upto)
    if md:
        notion.log_progress(c, g.session, md)
    notion.set_logged(c, g.session, upto)
    return True


def item_index(g, sid):
    for i, it in enumerate(g.tr.items):
        if it["role"] == "assistant" and sid in (it.get("scenes") or []):
            return i
    return None


def record_scene(c, g, sid):
    """장면 기록: 그 전까지의 진행 요약 → 장면(이미지+서술)."""
    idx = item_index(g, sid)
    if idx is not None:
        flush_progress(c, g, idx)
    res = notion.send_scene(c, c.scene(sid), g.session)
    if idx is not None and idx > notion.logged_upto(c, g.session):
        notion.set_logged(c, g.session, idx)
    return res


@app.post("/api/campaign/<cid>/play/turn")
def play_turn(cid):
    c = campaign(cid)
    b = body()
    text = (b.get("text") or "").strip()
    if not text:
        abort(400, "내용을 입력하세요.")
    with lock_for(cid):
        g = game(c, b.get("session"))
        new = g.turn(text, b.get("actor", ""), b.get("kind", "player"))
    result = {"new": [engine.view(i) for i in new], "auto_sent": []}
    if store.settings().get("notion_mode") == "always" and notion.ready(c):
        with lock_for(cid):
            for item in new:
                for sid in item.get("scenes") or []:
                    try:
                        record_scene(c, g, sid)
                        result["auto_sent"].append(sid)
                    except Exception as e:
                        result["notion_error"] = str(e)
    result["unlogged"] = len(g.tr.items) - notion.logged_upto(c, g.session) if notion.ready(c) else 0
    return jsonify(result)


@app.post("/api/campaign/<cid>/play/log")
def play_log(cid):
    c = campaign(cid)
    if not notion.ready(c):
        abort(400, "Notion 이 연결되지 않았습니다.")
    with lock_for(cid):
        g = game(c, body().get("session"))
        done = flush_progress(c, g, len(g.tr.items))
    return jsonify({"logged": done, "unlogged": 0 if done else len(g.tr.items) - notion.logged_upto(c, g.session)})


@app.post("/api/campaign/<cid>/play/retry")
def play_retry(cid):
    c = campaign(cid)
    with lock_for(cid):
        new = game(c, body().get("session")).retry()
    return jsonify({"new": [engine.view(i) for i in new]})


@app.post("/api/campaign/<cid>/play/undo")
def play_undo(cid):
    c = campaign(cid)
    with lock_for(cid):
        n = game(c, body().get("session")).undo()
    return jsonify({"removed": n})


@app.post("/api/roll")
def roll():
    b = body()
    try:
        r = dice.roll(b.get("expr", ""))
    except dice.DiceError as e:
        abort(400, str(e))
    return jsonify(r)


@app.post("/api/campaign/<cid>/scene/send")
def scene_send(cid):
    c = campaign(cid)
    b = body()
    sid = b.get("scene_id", "")
    c.scene(sid) or abort(404, "장면 없음")
    if not notion.ready(c):
        abort(400, "Notion 이 연결되지 않았습니다 (토큰 + 캠페인 페이지).")
    with lock_for(cid):
        g = game(c, b.get("session"))
        return jsonify(record_scene(c, g, sid))


@app.post("/api/campaign/<cid>/image/send")
def image_send(cid):
    c = campaign(cid)
    b = body()
    if not notion.ready(c):
        abort(400, "Notion 이 연결되지 않았습니다.")
    notion.post_image(c, b.get("image_id", ""), b.get("caption", ""), session_of(c, b.get("session")))
    return jsonify({"ok": True})


@app.post("/api/campaign/<cid>/session/new")
def session_new(cid):
    c = campaign(cid)
    p = c.new_session((body().get("title") or "새 회차").strip())
    return jsonify({"session": p.name, "sessions": [s.name for s in c.sessions()]})


@app.post("/api/campaign/<cid>/session/note")
def session_note(cid):
    c = campaign(cid)
    b = body()
    c.append_log(session_of(c, b.get("session")), (b.get("text") or "").strip())
    return jsonify({"ok": True})


@app.post("/api/campaign/<cid>/session/summarize")
def session_summarize(cid):
    c = campaign(cid)
    with lock_for(cid):
        g = game(c, body().get("session"))
        if notion.ready(c):
            try:
                flush_progress(c, g, len(g.tr.items))   # 남은 진행부터 기록
            except Exception as e:  # noqa: BLE001
                app.logger.warning("진행 기록 실패: %s", e)
        md = g.summarize()
    return jsonify({"summary": md})


@app.post("/api/campaign/<cid>/session/sync")
def session_sync(cid):
    c = campaign(cid)
    if not notion.ready(c):
        abort(400, "Notion 이 연결되지 않았습니다.")
    notion.sync_session(c, session_of(c, body().get("session")))
    return jsonify({"ok": True})


def main():
    ap = argparse.ArgumentParser(description="NightCity GM")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    url = f"http://127.0.0.1:{a.port}/"
    print(f"\n  NightCity GM  →  {url}\n  (끝내려면 Ctrl+C)\n")
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=a.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
