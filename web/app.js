/* NightCity GM – single page UI (no build step). Unofficial fan tool for Cyberpunk 2020. */
"use strict";

const TOKEN = document.querySelector('meta[name="app-token"]').content;
const S = {
  tab: "connect", state: null, camp: null, cg: null,
  draft: null, problems: [], derived: null, aiBusy: false,
  play: { session: null, log: [], sessions: [], sent: new Set(), pending: [], busy: false, scenes: [], actor: "", sessionText: "", rolled: {}, checkState: {}, autoSend: true },
  showGM: true, imgTag: "",
};

// ------------------------------------------------------------------ helpers
async function api(method, path, data) {
  const res = await fetch(path, {
    method, headers: { "Content-Type": "application/json", "X-App-Token": TOKEN },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  let json = {};
  try { json = await res.json(); } catch (_) { /* empty */ }
  if (!res.ok) throw new Error(json.error || `${res.status} ${res.statusText}`);
  return json;
}
const GET = (p) => api("GET", p);
const POST = (p, d = {}) => api("POST", p, d);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const md = (s) => esc(s).replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");

function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}` }, msg);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "err" ? 7000 : 3500);
}
async function guard(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg, "ok"); return r; }
  catch (e) { toast(e.message, "err"); return null; }
}
function field(label, input, hint) {
  return h("div", { class: "field" }, h("label", {}, label), input, hint ? h("div", { class: "dim small" }, hint) : null);
}
function select(options, value, onchange, attrs = {}) {
  return h("select", { ...attrs, onchange: (e) => onchange(e.target.value) },
    options.map((o) => { const [v, l] = Array.isArray(o) ? o : [o, o]; return h("option", { value: v, selected: String(v) === String(value) }, l); }));
}

// ------------------------------------------------------------------ boot
async function load() {
  S.state = await GET("/api/state");
  if (!S.cg) S.cg = await GET("/api/chargen/data");
  const cur = S.state.settings.current_campaign;
  if (cur && S.state.campaigns.some((c) => c.id === cur)) {
    S.camp = await guard(() => GET(`/api/campaign/${encodeURIComponent(cur)}`));
  }
}
async function refreshCamp() { if (S.camp) S.camp = await GET(`/api/campaign/${encodeURIComponent(S.camp.id)}`); }

function aiReady() {
  const s = S.state.settings;
  const p = S.state.providers.find((x) => x.name === s.provider);
  if (p && p.kind === "subscription") return !!(s.model && p.status?.installed && p.status?.loggedIn);
  return !!(p && s.model && p.needs.every((n) => !n.required || S.state.credentials[n.key]));
}
const notionTokenSet = () => !!S.state.credentials.NOTION_TOKEN;
function charsDone() {
  if (!S.camp) return false;
  const players = S.camp.meta.players || [];
  return players.length > 0 && players.every((p) => S.camp.characters.some((c) => c.player === p.name));
}

const bookReady = () => !!(S.state.book?.imported && S.state.book?.chargen);
const STEPS = [
  ["connect", "AI 연결 · Notion(선택)", () => aiReady()],
  ["book", "룰북 등록", bookReady],
  ["campaign", "캠페인 · 인원", () => !!(S.camp && (S.camp.meta.players || []).length)],
  ["characters", "캐릭터 생성", charsDone],
  ["play", "게임 진행", () => false],
];

function render() {
  // top bar
  const cp = $("#campaignPicker");
  cp.replaceChildren(
    S.state.campaigns.length
      ? select([["", "— 캠페인 선택 —"], ...S.state.campaigns.map((c) => [c.id, c.name])], S.camp?.id || "", async (v) => {
          if (!v) return;
          await saveDraftNow();
          S.camp = await guard(() => GET(`/api/campaign/${encodeURIComponent(v)}`));
          S.play.session = null; S.draft = null;
          render();
        })
      : h("span", { class: "dim small" }, "캠페인 없음"));
  const s = S.state.settings;
  const prov = S.state.providers.find((p) => p.name === s.provider);
  $("#statusPills").replaceChildren(
    h("span", { class: `pill ${aiReady() ? "on" : "off"}`, onclick: () => go("connect") },
      aiReady() ? `AI: ${prov.kind === "subscription" ? (prov.name === "chatgpt-codex" ? "ChatGPT 구독" : "Claude 구독") : prov.label.split(" ")[0]} · ${s.model}` : "AI 미연결"),
    h("span", { class: `pill ${notionTokenSet() && S.camp?.notion_ready ? "on" : ""}`, onclick: () => go(notionTokenSet() ? "campaign" : "connect") },
      notionTokenSet() ? (S.camp?.notion_ready ? "Notion 연결됨" : "Notion 페이지 미지정 (선택)") : "Notion 사용 안 함 (선택)"));
  // steps
  $("#steps").replaceChildren(...STEPS.map(([id, label, done], i) =>
    h("div", { class: `step ${S.tab === id ? "active" : ""} ${done() ? "done" : ""}`, onclick: () => go(id) },
      h("span", { class: "num" }, done() ? "✓" : i + 1), h("span", {}, label))));
  // main
  const main = $("#main");
  main.className = S.tab === "play" ? "play-mode" : "";
  const view = { connect: viewConnect, book: viewBook, campaign: viewCampaign, characters: viewCharacters, play: viewPlay }[S.tab]();
  main.replaceChildren(view);
  if (S.tab === "play") scrollLog();
}
async function go(tab) {
  await saveDraftNow();
  if ((tab === "characters" || tab === "play") && !S.camp) { toast("먼저 캠페인을 만들거나 고르세요.", "err"); tab = "campaign"; }
  if (tab === "characters" && !S.cg?.ready) { toast("캐릭터 생성 표는 룰북을 등록한 뒤에 쓸 수 있습니다.", "err"); tab = "book"; }
  S.tab = tab;
  render();
  if (tab === "play") loadPlay();
  if (tab === "book") pollBook();
}

// ------------------------------------------------------------------ ① 연결
function viewConnect() {
  const s = S.state.settings;
  const cur = S.state.providers.find((p) => p.name === s.provider);
  const keyInputs = {};
  const persist = h("input", { type: "checkbox", checked: true });
  const modelList = h("datalist", { id: "modelList" });
  const modelInput = h("input", { type: "text", list: "modelList", class: "wide", value: s.model || cur?.default_model || "", placeholder: "모델 이름" });

  const pick = async (p) => {
    await guard(() => POST("/api/ai", { provider: p.name, model: p.default_model || "" }));
    await load(); render();
  };
  const subs = S.state.providers.filter((p) => p.kind === "subscription");
  const apis = S.state.providers.filter((p) => p.kind !== "subscription");
  const useSub = cur?.kind === "subscription";
  if (S.showApi === undefined) S.showApi = !!cur && !useSub;
  const SUB_GUIDE = {
    "claude-code": { tool: "Claude Code", install: ["맥: curl -fsSL https://claude.ai/install.sh | bash", "윈도우: irm https://claude.ai/install.ps1 | iex"],
      login: [h("span", { class: "mono" }, "claude"), " 실행 → ", h("b", {}, "Claude 구독 계정"), " 으로 로그인 → ", h("span", { class: "mono" }, "/exit")],
      doc: ["https://code.claude.com/docs/en/setup", "Claude Code 설치 문서"], okMethod: { oauth_token: "구독 계정" } },
    "chatgpt-codex": { tool: "Codex CLI", install: ["맥: brew install --cask codex  (또는 npm i -g @openai/codex)", "윈도우: npm i -g @openai/codex  (Node.js 필요)"],
      login: [h("span", { class: "mono" }, "codex login"), " 실행 → 브라우저에서 ", h("b", {}, "ChatGPT 계정"), " 으로 로그인"],
      doc: ["https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan", "ChatGPT 요금제로 Codex 사용하기"], okMethod: { chatgpt: "ChatGPT 계정", api_key: "API 키" } },
  };
  const subBox = (p) => {
    const g = SUB_GUIDE[p.name] || { tool: p.label, install: [], login: [], doc: ["#", ""], okMethod: {} };
    const cc = p.status || {};
    return h("div", { class: "card", style: "background:#0e1120;margin:8px 0 0" },
      h("div", { class: "row" },
        h("b", {}, `${g.tool} 상태`),
        cc.installed ? h("span", { class: "badge ok" }, `설치됨 ${cc.version || ""}`) : h("span", { class: "badge pink" }, "설치 필요"),
        cc.installed ? (cc.loggedIn ? h("span", { class: "badge ok" }, `로그인됨${g.okMethod[cc.authMethod] ? ` (${g.okMethod[cc.authMethod]})` : ""}`) : h("span", { class: "badge pink" }, "로그인 필요")) : null,
        h("button", { class: "sm", onclick: async (e) => {
          e.target.disabled = true; e.target.textContent = "확인 중…";
          const r = await guard(() => POST(`/api/sub-status/${p.name}`));
          if (r) p.status = r;
          if (p.name === "claude-code" && r) S.state.claude_code = r;
          render();
        } }, "다시 확인")),
      cc.installed && cc.loggedIn ? h("p", { class: "dim small", style: "margin:8px 0 0" }, "준비됐습니다. 사용량은 API 요금이 아니라 구독 사용 한도에서 차감됩니다.") :
        h("ol", { class: "small", style: "margin:10px 0 0;padding-left:18px;line-height:1.9" },
          h("li", {}, `${g.tool} 설치 – 터미널(맥) 또는 PowerShell(윈도우)에서:`,
            h("div", { class: "mono", style: "background:#07090f;padding:6px 10px;border-radius:6px;margin:4px 0" }, g.install.flatMap((l, i) => i ? [h("br"), l] : [l]))),
          h("li", {}, "로그인 – 터미널에서 ", ...g.login),
          h("li", {}, "이 화면에서 ‘다시 확인’"),
          h("li", { class: "dim" }, "자세한 안내: ", h("a", { href: g.doc[0], target: "_blank" }, g.doc[1]))));
  };

  const provCard = h("div", { class: "card" },
    h("h3", {}, "1 · GM 을 맡길 AI"),
    h("p", { class: "lead" }, "GM 을 맡길 AI 를 하나 고르세요. 구독 계정(Claude · ChatGPT)은 API 키 없이 로그인만으로 쓸 수 있습니다."),
    (() => {
      if (S.aiOpen === undefined) S.aiOpen = !cur;
      const badge = (p) => {
        if (p.kind !== "subscription") return h("span", { class: "badge" }, "API 키");
        const st = p.status || {};
        return st.installed && st.loggedIn ? h("span", { class: "badge ok" }, "로그인됨") : h("span", { class: "badge pink" }, st.installed ? "로그인 필요" : "설치 필요");
      };
      const opt = (p) => h("div", { class: `aisel-opt ${p.name === s.provider ? "sel" : ""}`, onclick: async () => {
          S.aiOpen = false;
          if (p.name !== s.provider) await pick(p); else render();
        } },
        h("div", { class: "row" }, h("b", {}, `${p.kind === "subscription" ? "⭐ " : ""}${p.label}`), badge(p)),
        h("div", { class: "small dim" }, p.hint));
      return h("div", { class: "aisel" },
        h("div", { class: `aisel-head ${S.aiOpen ? "open" : ""}`, onclick: () => { S.aiOpen = !S.aiOpen; render(); } },
          cur ? h("div", {}, h("div", { class: "row" }, h("b", {}, `${cur.kind === "subscription" ? "⭐ " : ""}${cur.label}`), badge(cur)),
                  h("div", { class: "small dim" }, cur.hint))
              : h("b", { class: "dim" }, "AI 를 고르세요"),
          h("span", { style: "flex:1" }),
          h("button", { class: "sm" }, S.aiOpen ? "▲ 닫기" : "▼ 다른 AI 선택")),
        S.aiOpen ? h("div", { class: "aisel-list" },
          h("div", { class: "aisel-group" }, "구독 계정 – API 키 불필요"), subs.map(opt),
          h("div", { class: "aisel-group" }, "API 키로 연결"), apis.map(opt)) : null);
    })(),
    useSub ? subBox(cur) : null,
    cur ? h("div", { style: "margin-top:16px" },
      cur.needs.map((n) => {
        const inp = h("input", { type: n.secret ? "password" : "text", class: "wide", autocomplete: "off",
          placeholder: S.state.credentials[n.key] ? "설정됨 – 바꾸려면 새로 입력" : (n.required ? "필수" : "선택") });
        keyInputs[n.key] = inp;
        return field(`${n.label}${S.state.credentials[n.key] ? " ✓" : ""}`, inp);
      }),
      cur.needs.length ? h("div", { class: "row" },
        h("label", { class: "check" }, persist, "이 컴퓨터에 저장 (.env.local, git 제외)"),
        h("button", { class: "cyan", onclick: async () => {
            const keys = {};
            for (const [k, el] of Object.entries(keyInputs)) if (el.value.trim()) keys[k] = el.value.trim();
            if (!Object.keys(keys).length) return toast("입력한 값이 없습니다.", "err");
            await guard(() => POST("/api/keys", { keys, persist: persist.checked }), "저장했습니다.");
            await load(); render();
          } }, "키 저장")) : null,
      h("div", { class: "grid2", style: "margin-top:14px" },
        h("div", {},
          field("모델", h("div", { class: "row" }, modelInput, modelList,
            h("button", { class: "sm", onclick: async (e) => {
                e.target.disabled = true;
                const r = await guard(() => GET(`/api/models?provider=${cur.name}`));
                e.target.disabled = false;
                if (r) { modelList.replaceChildren(...r.models.map((m) => h("option", { value: m }))); toast(`모델 ${r.models.length}개 – 입력칸을 눌러 고르세요.`, "ok"); }
              } }, "목록 불러오기")), "목록에서 고르거나 이름을 직접 입력")),
        h("div", {},
          field("룰 자료 (내 룰북에서)", select([["index", "색인 – 상황에 맞는 쪽만 (기본)"], ["summary", "AI 정리본 – ② 에서 만든 경우"], ["none", "사용 안 함 – AI 지식에 맡김"]], s.rules, async (v) => {
            await guard(() => POST("/api/ai", { rules: v })); await load(); }), "로컬 모델(Ollama)은 '핵심' 권장"),
          useSub ? null : field("응답 최대 길이 (토큰)", h("input", { type: "number", value: s.max_tokens, min: 300, max: 8000, step: 100,
            onchange: async (e) => { await guard(() => POST("/api/ai", { max_tokens: +e.target.value })); await load(); } })))),
      h("div", { class: "row" },
        h("button", { class: "primary", onclick: async () => {
            await guard(() => POST("/api/ai", { model: modelInput.value.trim() }), "적용했습니다.");
            await load(); render();
          } }, "적용"),
        h("button", { onclick: async (e) => {
            e.target.disabled = true; e.target.textContent = "테스트 중…";
            await guard(() => POST("/api/ai", { model: modelInput.value.trim() }));
            const r = await guard(() => POST("/api/ai/test"));
            if (r) toast(`AI 응답: ${r.reply}`, "ok");
            await load(); render();
          } }, "연결 테스트"))) : null);

  const nTok = h("input", { type: "password", class: "wide", autocomplete: "off", placeholder: notionTokenSet() ? "설정됨 – 바꾸려면 새로 입력" : "ntn_… / secret_…" });
  const nPersist = h("input", { type: "checkbox", checked: true });
  const notionCard = h("div", { class: "card" },
    h("h3", {}, "2 · Notion 연결 (선택)"),
    h("p", { class: "lead" }, "필수가 아닙니다. 연결하지 않아도 게임은 그대로 진행되고 기록은 이 컴퓨터에 저장됩니다. 연결하면 플레이어들이 볼 기록이 Notion 에 쌓입니다. 장면(이미지+서술), 캐릭터 시트, 세션 요약만 올라가고 룰북·GM 메모는 올라가지 않습니다. 기존 내용은 수정하지 않고 추가만 합니다."),
    h("ol", { class: "dim small" },
      h("li", {}, h("a", { href: "https://app.notion.com/developers/connections", target: "_blank" }, "Notion 개발자 포털"), " → Internal connections → Create a new connection → Configuration 탭에서 API 토큰 복사 (워크스페이스 소유자만 가능)"),
      h("li", {}, "기록할 Notion 페이지의 ··· → Connections(연결) → + Add connection 에서 방금 만든 연결 추가"),
      h("li", {}, "그 페이지 URL 은 ② 캠페인 화면에서 입력")),
    field(`Notion API 토큰 (선택)${notionTokenSet() ? " ✓" : ""}`, nTok),
    h("div", { class: "row" },
      h("label", { class: "check" }, nPersist, "이 컴퓨터에 저장"),
      h("button", { class: "cyan", onclick: async () => {
          if (!nTok.value.trim()) return toast("토큰을 입력하세요.", "err");
          await guard(() => POST("/api/keys", { keys: { NOTION_TOKEN: nTok.value.trim() }, persist: nPersist.checked }), "저장했습니다.");
          await load(); render();
        } }, "토큰 저장")),
    h("div", { class: "row" }, field("장면을 Notion 에 기록하는 방식 (선택)", select([["always", "장면이 바뀌면 자동으로 (추천)"], ["ask", "장면마다 버튼으로"], ["never", "기록하지 않음"]], s.notion_mode, async (v) => {
      await guard(() => POST("/api/ai", { notion_mode: v })); await load(); }))));

  const dangerCard = h("div", { class: "card" },
    h("h3", {}, "저장된 키"),
    h("div", { class: "dim small" }, Object.entries(S.state.credentials).filter(([, v]) => v).map(([k, v]) => `${k} (${{ memory: "이번 실행에만", env: "환경변수", file: ".env.local" }[v]})`).join(" · ") || "없음"),
    h("p", { class: "dim small", style: "margin:6px 0 0" }, "API 키·Notion 토큰처럼 이 앱에 입력한 값만 표시됩니다. 구독 계정(Claude · ChatGPT)은 키 없이 각 도구의 로그인으로 동작하므로 여기 나오지 않습니다. 저장 위치는 이 폴더의 .env.local 이라 다른 폴더에서 실행하면 따로 입력해야 합니다."),
    h("div", { class: "row", style: "margin-top:10px" }, h("button", { class: "danger", onclick: async () => {
      if (!confirm("이 컴퓨터에 저장된 키를 모두 지울까요? (환경변수는 지워지지 않음)")) return;
      await guard(() => POST("/api/keys/forget", {}), "삭제했습니다."); await load(); render();
    } }, "저장된 키 모두 삭제")));

  return h("div", {},
    h("h2", {}, "AI 연결 · Notion (선택)"), h("p", { class: "lead" }, "한 번만 설정하면 됩니다. 필수는 AI 하나뿐이고 Notion 은 선택입니다."),
    h("div", { class: "grid2" }, provCard, h("div", {}, notionCard, dangerCard)),
    h("div", { class: "row" }, h("button", { class: "primary", disabled: !aiReady(), onclick: () => go("campaign") }, "다음: 캠페인 · 인원 →")));
}

// ------------------------------------------------------------------ 룰북 등록
let bookPoll;
async function pollBook() {
  clearTimeout(bookPoll);
  const r = await guard(() => GET("/api/book"));
  if (!r) return;
  S.bookJobs = r.jobs; S.state.book = r.book;
  const running = Object.values(r.jobs).some((j) => j.status === "running");
  if (!running && r.book.chargen && !S.cg?.ready) S.cg = await GET("/api/chargen/data");
  if (S.tab === "book") render();
  if (running) bookPoll = setTimeout(pollBook, 1500);
}
function jobLine(kind) {
  const j = (S.bookJobs || {})[kind];
  if (!j) return null;
  if (j.status === "running") return h("div", { class: "job" }, h("div", { class: "bar" }, h("span", { style: `width:${Math.round(j.progress * 100)}%` })), h("span", { class: "small dim" }, j.msg));
  if (j.status === "error") return h("div", { class: "err small" }, `실패: ${j.error}`);
  return h("div", { class: "ok small" }, "✓ 완료");
}
async function uploadPdf(f) {
  if (!f) return;
  if (!/\.pdf$/i.test(f.name) && f.type !== "application/pdf") return toast("PDF 파일만 등록할 수 있습니다.", "err");
  if ((S.bookJobs || {}).import?.status === "running") return toast("이미 등록 중입니다.", "err");
  if (S.state.book?.imported && !confirm(`'${f.name}' 으로 다시 등록할까요? 기존 색인을 새로 만듭니다.`)) return;
  toast(`'${f.name}' 업로드 중… (${Math.round(f.size / 1048576)}MB)`);
  const fd = new FormData(); fd.append("pdf", f);
  const r = await fetch("/api/book/import", { method: "POST", headers: { "X-App-Token": TOKEN }, body: fd });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) return toast(j.error || "업로드 실패", "err");
  pollBook();
}
// 룰북 화면 밖에 떨어뜨려도 브라우저가 PDF 를 열어 버리지 않게
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  if (S.tab === "book") uploadPdf(e.dataTransfer?.files?.[0]);
});

function viewBook() {
  const b = S.state.book || {};
  const jobs = S.bookJobs || {};
  const busy = (k) => jobs[k]?.status === "running";
  const file = h("input", { type: "file", accept: "application/pdf,.pdf", class: "hidden", onchange: (e) => uploadPdf(e.target.files[0]) });
  const drop = h("div", { class: `dropzone ${busy("import") ? "busy" : ""}`, onclick: () => !busy("import") && file.click(),
      ondragenter: (e) => { e.preventDefault(); e.currentTarget.classList.add("over"); },
      ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add("over"); },
      ondragleave: (e) => e.currentTarget.classList.remove("over"),
      ondrop: (e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.remove("over"); uploadPdf(e.dataTransfer.files[0]); } },
    h("div", { class: "dz-icon" }, "📄"),
    h("b", {}, busy("import") ? "등록 중…" : b.imported ? "다른 PDF 로 다시 등록하려면 여기에 끌어다 놓기" : "룰북 PDF 를 여기에 끌어다 놓기"),
    h("div", { class: "dim small" }, "또는 클릭해서 파일 선택"), file);
  return h("div", {},
    h("h2", {}, "룰북 등록"),
    h("p", { class: "lead" }, "이 앱에는 룰북 내용이 들어 있지 않습니다. 가지고 있는 Cyberpunk 2020 코어 룰북 PDF 를 등록하면, 이 컴퓨터 안에서만 GM 자료와 캐릭터 생성 표를 만듭니다. PDF 와 추출한 내용은 어디에도 업로드되지 않습니다."),
    h("div", { class: "grid2" },
      h("div", { class: "card" },
        h("h3", {}, "1 · PDF 등록"),
        b.imported ? h("div", {},
          h("p", {}, h("span", { class: "badge ok" }, "등록됨"), ` ${b.file} · ${b.pages}쪽`),
          h("p", { class: "dim small" }, `확인된 표지 ${b.markers.length}개 · ${String(b.imported_at).replace("T", " ")}`))
          : h("p", { class: "dim small" }, "텍스트가 들어 있는(검색 가능한) PDF 여야 합니다. 등록에 20~60초 정도 걸립니다."),
        drop,
        jobLine("import")),
      h("div", { class: "card" },
        h("h3", {}, "2 · 캐릭터 생성 표 만들기"),
        h("p", { class: "dim small" }, "연결한 AI 가 내 룰북에서 역할·스킬 목록·월급표·라이프패스 표를 읽어 정리합니다. 몇 분 걸리고 AI 사용량이 조금 듭니다. 실패하면 다시 누르세요."),
        b.chargen ? h("p", {}, h("span", { class: "badge ok" }, "준비됨"), " 캐릭터 생성 가능") : null,
        h("button", { class: b.chargen ? "" : "primary", disabled: !b.imported || busy("chargen") || !aiReady(), onclick: async () => {
          if (await guard(() => POST("/api/book/chargen"))) pollBook();
        } }, b.chargen ? "다시 만들기" : "만들기"),
        !aiReady() ? h("span", { class: "dim small" }, "  ① 에서 AI 를 먼저 연결하세요") : null,
        jobLine("chargen"))),
    h("div", { class: "card" },
      h("h3", {}, "3 · (선택) AI 정리본"),
      h("p", { class: "dim small" }, "기본은 '색인' 방식이라 매 턴 지금 상황과 관련된 쪽만 찾아 GM 에게 줍니다. 판정을 더 안정적으로 하고 싶으면 책 전체를 AI 로 요약한 정리본을 만들 수 있습니다(15~30분, 사용량 많음). 만든 뒤 ① 의 룰 자료를 'AI 정리본' 으로 바꾸세요."),
      b.summary ? h("p", {}, h("span", { class: "badge ok" }, "정리본 있음")) : null,
      h("button", { disabled: !b.imported || busy("summary") || !aiReady(), onclick: async () => {
        if (!confirm("책 전체를 AI 로 정리합니다. 시간이 오래 걸리고 사용량이 많이 듭니다. 진행할까요?")) return;
        if (await guard(() => POST("/api/book/summary"))) pollBook();
      } }, b.summary ? "다시 만들기" : "정리본 만들기"), jobLine("summary")),
    h("div", { class: "row" },
      h("button", { class: "primary", disabled: !bookReady(), onclick: () => go("campaign") }, "다음: 캠페인 · 인원 →"),
      h("button", { class: "ghost", onclick: () => go("campaign") }, "룰북 없이 계속 (캐릭터 생성 불가, 판정 부정확)"),
      h("span", { style: "flex:1" }),
      b.imported ? h("button", { class: "danger sm", onclick: async () => {
        if (!confirm("등록한 룰북 데이터(색인·표·정리본)를 이 컴퓨터에서 지울까요? 캠페인과 캐릭터는 남습니다.")) return;
        const r = await guard(() => POST("/api/book/forget")); if (r) { S.state.book = r.book; S.bookJobs = {}; S.cg = await GET("/api/chargen/data"); render(); }
      } }, "룰북 데이터 삭제") : null),
    h("p", { class: "dim small" }, "※ 판매처 PDF 에는 구매자 정보가 들어 있을 수 있으니 PDF 를 다른 사람에게 공유하지 마세요. 이 앱은 R. Talsorian Games 의 승인이나 보증을 받지 않은 팬 제작 도구입니다."));
}

// ------------------------------------------------------------------ ② 캠페인
function viewCampaign() {
  const name = h("input", { type: "text", class: "wide", placeholder: "예) 나이트시티 첫 캠페인" });
  const page = h("input", { type: "url", class: "wide", placeholder: "https://www.notion.so/… (나중에 넣어도 됨)" });
  const create = h("div", { class: "card" },
    h("h3", {}, "새 캠페인"),
    field("캠페인 이름", name), field("Notion 기록 페이지 URL (선택)", page),
    h("button", { class: "primary", onclick: async () => {
      const r = await guard(() => POST("/api/campaigns", { name: name.value, notion_page: page.value }), "캠페인을 만들었습니다.");
      if (r) { S.camp = r; await load(); render(); }
    } }, "만들기"));
  if (!S.camp) {
    return h("div", {}, h("h2", {}, "캠페인 · 인원"),
      h("p", { class: "lead" }, "플레이 그룹마다 캠페인을 하나 만드세요. 캐릭터·세션 기록은 이 컴퓨터의 campaigns/ 폴더에만 저장됩니다(GitHub 에 올라가지 않음)."),
      h("div", { class: "grid2" }, create,
        S.state.campaigns.length ? h("div", { class: "card" }, h("h3", {}, "기존 캠페인"),
          S.state.campaigns.map((c) => h("div", { class: "row" }, h("button", { onclick: async () => { S.camp = await guard(() => GET(`/api/campaign/${encodeURIComponent(c.id)}`)); render(); } }, c.name),
            h("span", { class: "dim small" }, (c.created || "").slice(0, 10))))) : null));
  }
  const m = S.camp.meta;
  const players = (m.players || []).map((p) => ({ ...p }));
  const list = h("div", {});
  const countH = h("h3", {}, `플레이어 (${players.length}명)`);
  const drawPlayers = () => (countH.textContent = `플레이어 (${players.length}명)`, list.replaceChildren(...players.map((p, i) => h("div", { class: "row", style: "margin-bottom:6px" },
    h("span", { class: "mono dim" }, `P${i + 1}`),
    h("input", { type: "text", value: p.name, placeholder: "플레이어 이름", oninput: (e) => (p.name = e.target.value) }),
    S.camp.characters.find((c) => c.player === p.name) ? h("span", { class: "badge ok" }, S.camp.characters.find((c) => c.player === p.name).handle) : h("span", { class: "badge" }, "캐릭터 없음"),
    h("button", { class: "sm ghost", onclick: () => { players.splice(i, 1); drawPlayers(); } }, "✕")))));
  drawPlayers();
  const method = { v: m.stat_method || "cinematic" };
  const pts = { v: m.stat_points || 75 };
  const exp = { v: m.experience || "전원 처음" };
  const premise = h("textarea", { placeholder: "예) 짧은 원샷 / 아라사카에 맞서는 장기 캠페인 / 잔혹 표현 수위 낮게 …" }, m.premise || "");
  const notionPage = h("input", { type: "url", class: "wide", value: m.notion_page || "", placeholder: "https://www.notion.so/…" });
  const nstat = h("span", { class: "small" }, S.camp.notion_ready ? h("span", { class: "ok" }, "연결 정보 있음") : h("span", { class: "dim" }, "토큰과 페이지가 모두 있어야 기록됩니다"));
  const save = async (msg = "저장했습니다.") => {
    const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/meta`, {
      players, stat_method: method.v, stat_points: +pts.v, experience: exp.v, premise: premise.value, notion_page: notionPage.value.trim() }), msg);
    if (r) { S.camp = r; await load(); render(); }
    return r;
  };
  const methodBox = h("div", {});
  const drawMethod = () => methodBox.replaceChildren(
    h("div", { class: "choice-grid" }, Object.entries(S.cg.methods).map(([k, v]) =>
      h("div", { class: `choice ${method.v === k ? "sel" : ""}`, onclick: () => { method.v = k; drawMethod(); } },
        h("b", {}, { cinematic: "고정 포인트", random: "9D10 랜덤", fast: "빠른 방식" }[k]), h("span", { class: "small" }, v.split("–")[1] || v)))),
    method.v === "cinematic" ? h("div", { style: "margin-top:10px" }, Object.keys(S.cg.cinematic || {}).length
      ? field("포인트", select(Object.entries(S.cg.cinematic).map(([k, v]) => [k, `${k} – ${v}`]).reverse(), pts.v, (v) => (pts.v = v)))
      : field("포인트", h("input", { type: "number", value: pts.v, min: 40, max: 90, onchange: (e) => (pts.v = +e.target.value) }), "룰북을 등록하면 등급별 포인트 표가 나타납니다")) : null);
  drawMethod();
  return h("div", {},
    h("h2", {}, m.name), h("p", { class: "lead" }, "인원과 진행 방식을 정하세요. 바꾼 뒤 저장을 누르세요."),
    h("div", { class: "grid2" },
      h("div", { class: "card" }, countH, list,
        h("button", { class: "sm cyan", onclick: () => { players.push({ name: "" }); drawPlayers(); list.lastChild?.querySelector("input")?.focus(); } }, "＋ 플레이어 추가"),
        h("div", { style: "margin-top:16px" }, field("플레이 경험", select(["전원 처음", "일부 경험 있음", "모두 숙련"], exp.v, (v) => (exp.v = v)), "AI GM 이 규칙 설명 양을 조절합니다")),
        field("캠페인 메모 (AI GM 참고)", premise)),
      h("div", {},
        h("div", { class: "card" }, h("h3", {}, "능력치 결정 방식"), methodBox),
        h("div", { class: "card" }, h("h3", {}, "Notion 기록 페이지 (선택)"),
          field("페이지 URL", notionPage), h("div", { class: "row" },
            h("button", { class: "sm", onclick: async () => {
              if (!notionTokenSet()) return toast("먼저 ① 에서 Notion 토큰을 저장하세요.", "err");
              const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/notion/check`, { notion_page: notionPage.value.trim() }));
              if (r) toast(r.ok ? `접근 확인: ${r.title}` : r.error, r.ok ? "ok" : "err");
            } }, "연결 확인"), nstat)))),
    h("div", { class: "row" },
      h("button", { class: "primary", onclick: () => save() }, "저장"),
      h("button", { onclick: async () => { if (await save()) go("characters"); } }, "저장하고 캐릭터 생성 →"),
      h("span", { style: "flex:1" }),
      h("button", { class: "ghost sm", onclick: () => { S.camp = null; render(); } }, "다른 캠페인 / 새로 만들기")));
}

// ------------------------------------------------------------------ ③ 캐릭터
const roleOf = (ch) => S.cg.roles[ch.role];

function newDraft(player = "") {
  return { id: null, player, handle: "", name: "", age: "", role: "", stats: Object.fromEntries(S.cg.stats.map(([k]) => [k, 5])),
    stat_pool: null, slots: [], pickupRows: [], cyberware: [], gear: "", notes: "", lifepath: null, money: null, status: {} };
}
function slotsForRole(role, career = {}) {
  const r = S.cg.roles[role];
  if (!r) return [];
  const used = new Set();
  return [r.special, ...r.skills].map((slot) => {
    let options = slot === "TECH_CHOICE" ? S.cg.tech_choices : slot.split("|");
    let name = options.find((o) => o in career && !used.has(o)) || (slot === "TECH_CHOICE" ? options.find((o) => !used.has(o) && !(r.skills.includes(o))) : options[0]);
    used.add(name);
    return { options, name, value: career[name] || 0, choice: options.length > 1 };
  });
}
function draftFrom(ch) {
  const d = { ...newDraft(), ...JSON.parse(JSON.stringify(ch)) };
  d.slots = slotsForRole(ch.role, ch.career || {});
  d.pickupRows = Object.entries(ch.pickup || {}).map(([name, value]) => ({ name, value }));
  return d;
}
function draftToChar(d) {
  const ch = { ...d };
  ch.career = Object.fromEntries(d.slots.filter((s) => s.name).map((s) => [s.name, +s.value || 0]));
  ch.pickup = Object.fromEntries(d.pickupRows.filter((r) => r.name).map((r) => [r.name, +r.value || 0]));
  for (const k of ["slots", "pickupRows", "derived", "notion"]) delete ch[k];
  ch.stats = Object.fromEntries(Object.entries(d.stats).map(([k, v]) => [k, parseInt(v, 10) || 0]));
  return ch;
}
let checkTimer;
function recheck(redraw) {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    const r = await guard(() => POST("/api/chargen/check", { character: draftToChar(S.draft), method: S.camp.meta.stat_method, points: S.camp.meta.stat_points }));
    if (r) { S.problems = r.problems; S.derived = r.derived; redraw(); }
    markDirty();
  }, 250);
}

// ---- 작성 중 캐릭터 임시 저장 (플레이어별)
const draftKey = (d) => (d.player ? `p:${d.player}` : `c:${d.id || "new"}`);
let draftTimer;
const draftChanged = () => !!(S.draft && S.camp && JSON.stringify(S.draft) !== S.draftSnap);
async function saveDraftNow() {
  clearTimeout(draftTimer);
  if (!draftChanged()) return;
  const key = draftKey(S.draft), data = JSON.parse(JSON.stringify(S.draft));
  S.draftSnap = JSON.stringify(S.draft);
  S.camp.drafts = { ...(S.camp.drafts || {}), [key]: data };
  await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/draft`, { key, draft: data }));
}
function markDirty() {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(saveDraftNow, 1500);
}
window.addEventListener("beforeunload", () => {
  if (!draftChanged()) return;
  fetch(`/api/campaign/${encodeURIComponent(S.camp.id)}/draft`, { method: "POST", keepalive: true,
    headers: { "Content-Type": "application/json", "X-App-Token": TOKEN },
    body: JSON.stringify({ key: draftKey(S.draft), draft: S.draft }) });
});
async function selectSlot(player, ch) {
  await saveDraftNow();                       // 이전 플레이어 작업 저장 후 전환
  const key = player ? `p:${player}` : `c:${ch?.id || "new"}`;
  const saved = (S.camp.drafts || {})[key];
  if (saved) { S.draft = { ...newDraft(player), ...saved }; delete S.draft._saved; }
  else S.draft = ch ? draftFrom(ch) : newDraft(player);
  S.draft.player = player || S.draft.player || "";
  S.problems = []; S.derived = null; S.rosterOpen = false; S.draftSnap = JSON.stringify(S.draft);
  render(); recheck(render);
  $("#main").scrollTop = 0;
}
function slotStatus(player, ch) {
  const key = player ? `p:${player}` : `c:${ch?.id}`;
  const editing = S.draft && draftKey(S.draft) === key && draftChanged();
  const dr = (S.camp.drafts || {})[key] || editing;
  if (ch && dr) return ["수정 중 · 저장 안 됨", "warn"];
  if (ch) return ["완성", "ok"];
  if (dr) return ["작성 중 · 임시 저장", "warn"];
  return ["미작성", ""];
}

function viewCharacters() {
  const m = S.camp.meta;
  const players = m.players || [];
  const others = S.camp.characters.filter((c) => !players.some((p) => p.name === c.player));
  const slots = [...players.map((p) => ({ player: p.name, ch: S.camp.characters.find((c) => c.player === p.name) })),
    ...others.map((c) => ({ player: "", ch: c }))];
  if (S.rosterOpen === undefined) S.rosterOpen = !S.draft;
  const cur = S.draft;
  const curCh = cur && slots.find((x) => (cur.player ? x.player === cur.player : x.ch && x.ch.id === cur.id));
  const label = (x) => x.player || `${x.ch.handle} (NPC/미배정)`;

  const bar = h("div", { class: "card pbar" },
    h("div", { class: "pbar-head", onclick: async () => { S.rosterOpen = !S.rosterOpen; render(); } },
      h("span", { class: "dim small" }, "플레이어"),
      cur ? h("b", {}, cur.player || "(NPC/미배정)") : h("b", { class: "dim" }, "선택하세요"),
      cur ? h("span", { class: "dim" }, cur.handle ? `· ${cur.handle}${cur.role ? ` · ${S.cg.roles[cur.role]?.ko || cur.role}` : ""}` : "· 새 캐릭터") : null,
      cur && curCh ? (([t, k]) => h("span", { class: `badge ${k}` }, t))(slotStatus(curCh.player, curCh.ch)) : null,
      h("span", { style: "flex:1" }),
      h("span", { class: "dim small" }, `${slots.filter((x) => x.ch).length}/${players.length}명 완성`),
      h("button", { class: "sm", title: "플레이어 목록" }, S.rosterOpen ? "▲ 닫기" : "▼ 플레이어 선택")),
    S.rosterOpen ? h("div", { class: "pbar-list" },
      players.length ? null : h("p", { class: "dim small" }, "② 캠페인 · 인원에서 플레이어를 먼저 추가하세요."),
      slots.map((x) => {
        const [t, k] = slotStatus(x.player, x.ch);
        const sel = cur && (cur.player ? cur.player === x.player : x.ch && cur.id === x.ch.id);
        return h("div", { class: `pbar-item ${sel ? "sel" : ""}`, onclick: () => selectSlot(x.player, x.ch) },
          h("div", { class: "row", style: "justify-content:space-between" }, h("b", {}, label(x)), h("span", { class: `badge ${k}` }, t)),
          h("div", { class: "dim small" }, x.ch ? `${x.ch.handle} · ${S.cg.roles[x.ch.role]?.ko || x.ch.role}${x.ch.notion ? " · Notion ✓" : ""}`
            : ((S.camp.drafts || {})[`p:${x.player}`]?.handle || "＋ 캐릭터 만들기")));
      }),
      h("div", { class: "row", style: "grid-column:1/-1;margin-top:4px" },
        h("span", { class: "dim small" }, `능력치 방식: ${{ cinematic: `고정 ${m.stat_points}점`, random: "9D10 랜덤", fast: "빠른 방식" }[m.stat_method]} · 플레이어를 바꾸면 작업 중인 내용은 자동으로 임시 저장됩니다.`))) : null);

  return h("div", {}, h("h2", {}, "캐릭터 생성"),
    h("p", { class: "lead" }, "플레이어를 골라 순서대로 채우세요: 역할 → 능력치 → 스킬 → 라이프패스 → 자금·장비. AI 도우미로 초안을 만든 뒤 고쳐도 됩니다."),
    bar,
    charsDone() ? h("div", { class: "row", style: "margin:-6px 0 16px" }, h("span", { class: "ok small" }, "✓ 모든 플레이어의 캐릭터가 준비됐습니다."),
      h("button", { class: "primary sm", onclick: async () => { await saveDraftNow(); go("play"); } }, "게임 시작 →")) : null,
    S.draft ? editor() : h("div", { class: "card dim" }, "위의 ‘▼ 플레이어 선택’ 에서 캐릭터를 만들거나 고칠 플레이어를 고르세요."));
}

function editor() {
  const d = S.draft;
  const m = S.camp.meta;
  const wrap = h("div", {});
  const redraw = () => { const n = editor(); wrap.replaceWith(n); };
  const change = (fn, full = false) => (e) => { fn(e); recheck(full ? render : refreshSide); if (full) render(); };
  // live side elements
  const statCounter = h("span", { class: "counter" });
  const careerCounter = h("span", { class: "counter" });
  const pickCounter = h("span", { class: "counter" });
  const derivedBox = h("div", { class: "derived" });
  const problemsBox = h("div", {});
  function refreshSide() {
    const sum = Object.values(d.stats).reduce((a, b) => a + (parseInt(b, 10) || 0), 0);
    let target = m.stat_method === "cinematic" ? +m.stat_points : d.stat_pool?.points;
    if (m.stat_method === "fast") {
      statCounter.textContent = d.stat_pool ? "굴린 숫자를 배치" : "먼저 굴리세요";
      statCounter.className = "counter";
    } else {
      statCounter.textContent = target ? `${sum} / ${target}` : "먼저 굴리세요";
      statCounter.className = `counter ${target && sum === target ? "good" : "bad"}`;
    }
    const ct = d.slots.reduce((a, s) => a + (+s.value || 0), 0);
    careerCounter.textContent = `${ct} / 40`; careerCounter.className = `counter ${ct === 40 ? "good" : "bad"}`;
    const allowed = (+d.stats.INT || 0) + (+d.stats.REF || 0);
    const pt = d.pickupRows.reduce((a, r) => a + (+r.value || 0), 0);
    pickCounter.textContent = `${pt} / ${allowed}`; pickCounter.className = `counter ${pt <= allowed ? (pt === allowed ? "good" : "") : "bad"}`;
    const dv = S.derived;
    derivedBox.replaceChildren(...(dv ? [
      ["RUN", `${dv.run}m`], ["LEAP", `${dv.leap}m`], ["휴머니티", `${dv.humanity}/${dv.humanity_max}`], ["현재 EMP", dv.emp_current],
      ["BTM", `${dv.btm} (${dv.body_label})`], ["Save", dv.save], ["운반", `${dv.carry}kg`], ["픽업 포인트", dv.pickup_points],
    ].map(([k, v]) => h("span", {}, `${k} `, h("b", {}, v))) : []));
    problemsBox.replaceChildren(S.problems.length ? h("ul", { class: "problems" }, S.problems.map((p) => h("li", {}, p))) : h("span", { class: "ok small" }, "✓ 규칙상 문제 없음"));
    if (m.stat_method === "fast" && d.stat_pool) {
      const left = [...d.stat_pool.values];
      Object.values(d.stats).forEach((v) => { const i = left.indexOf(+v); if (i >= 0) left.splice(i, 1); });
      poolBox.replaceChildren(...d.stat_pool.values.map((v, i) => h("span", {}, v)), left.length ? h("span", { class: "dim small", style: "border:0" }, `남은 값: ${left.join(", ")}`) : h("span", { class: "ok small", style: "border:0" }, "모두 배치됨"));
    }
  }
  const poolBox = h("div", { class: "pool" });

  // --- 기본
  const basics = h("div", { class: "card" }, h("h3", {}, "기본 정보"),
    h("div", { class: "row" },
      field("플레이어", h("div", { style: "padding:7px 0;font-weight:700" }, d.player || "(NPC/미배정)")),
      field("핸들(별명) *", h("input", { type: "text", value: d.handle, oninput: change((e) => (d.handle = e.target.value)) })),
      field("본명", h("input", { type: "text", value: d.name, oninput: (e) => (d.name = e.target.value) })),
      field("나이", h("input", { type: "number", value: d.age, min: 16, max: 80, oninput: (e) => (d.age = e.target.value) }))));

  // --- AI 도우미
  const concept = h("textarea", { placeholder: "예) 아라사카에서 쫓겨난 전직 경호원. 과묵하고 의리 있음. 사이버암 하나.",
    oninput: (e) => { d.concept = e.target.value; markDirty(); } }, d.concept || "");
  const aiBox = h("div", { class: "card" }, h("h3", {}, "AI 도우미 (선택)"),
    h("p", { class: "dim small" }, "콘셉트를 적으면 AI 가 역할·능력치·스킬·장비 초안을 채웁니다. 결과는 아래에서 자유롭게 고치세요."),
    concept,
    h("div", { class: "row", style: "margin-top:8px" }, h("button", { class: "cyan", disabled: S.aiBusy || !aiReady(), onclick: async () => {
      if (m.stat_method !== "cinematic" && !d.stat_pool) return toast("먼저 능력치를 굴리세요.", "err");
      S.aiBusy = true; render();
      const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/chargen/ai`, { concept: concept.value, character: draftToChar(d) }));
      S.aiBusy = false;
      if (r) {
        const keep = { id: d.id, player: d.player, concept: d.concept, stat_pool: d.stat_pool, lifepath: d.lifepath, money: d.money, status: d.status };
        S.draft = { ...draftFrom(r.character), ...Object.fromEntries(Object.entries(keep).filter(([, v]) => v)) };
        S.problems = r.problems;
        toast(r.problems.length ? "초안을 채웠습니다. 표시된 문제를 고쳐 주세요." : "초안을 채웠습니다.", "ok");
      }
      render(); recheck(render);
    } }, S.aiBusy ? "AI 가 만드는 중…" : "AI 로 초안 만들기"), aiReady() ? null : h("span", { class: "dim small" }, "① 에서 AI 를 연결하면 쓸 수 있어요")));

  // --- 역할
  const roles = h("div", { class: "card" }, h("h3", {}, "역할 (Role)"),
    h("div", { class: "choice-grid" }, Object.entries(S.cg.roles).map(([k, r]) =>
      h("div", { class: `choice ${d.role === k ? "sel" : ""}`, title: r.desc, onclick: () => {
          if (d.role === k) return;
          d.role = k; d.slots = slotsForRole(k); d.money = null;
          d.pickupRows = d.pickupRows.filter((p) => !d.slots.some((s) => s.name === p.name));
          render(); recheck(render);
        } },
        h("b", {}, `${r.ko} `, h("span", { class: "dim small" }, k)), h("span", { class: "small" }, `특수능력: ${r.special}`)))),
    d.role ? h("p", { class: "small", style: "margin:10px 0 0" }, roleOf(d).desc) : null);

  // --- 능력치
  const statInputs = S.cg.stats.map(([k, ko, desc]) => h("div", { class: "stat", title: desc },
    h("div", { class: "k" }, k), h("div", { class: "n" }, ko),
    h("input", { type: "number", min: 2, max: 10, value: d.stats[k], oninput: change((e) => (d.stats[k] = e.target.value)) })));
  const stats = h("div", { class: "card" },
    h("div", { class: "row", style: "justify-content:space-between" }, h("h3", { style: "margin:0" }, "능력치 (Stats)"), statCounter),
    m.stat_method !== "cinematic" ? h("div", { class: "row", style: "margin:10px 0" },
      h("button", { class: "cyan sm", onclick: async () => {
        if (d.stat_pool && !confirm("다시 굴릴까요? (그룹 규칙에 따라 재굴림이 허용되지 않을 수 있어요)")) return;
        const r = await guard(() => POST("/api/chargen/roll_stats", { method: m.stat_method }));
        if (r) { d.stat_pool = r; toast(m.stat_method === "random" ? `9D10 = ${r.rolls.join("+")} = ${r.points}` : `굴림: ${r.values.join(", ")}`, "ok"); render(); recheck(render); }
      } }, d.stat_pool ? "다시 굴리기" : "🎲 능력치 굴리기"),
      m.stat_method === "random" && d.stat_pool ? h("span", { class: "mono" }, `${d.stat_pool.rolls.join(" + ")} = ${d.stat_pool.points}점 분배`) : null,
      m.stat_method === "fast" ? poolBox : null) : h("p", { class: "dim small", style: "margin:6px 0 10px" }, `${m.stat_points}점을 9개 능력치에 분배 (각 2~10)`),
    h("div", { class: "stats-grid" }, statInputs), derivedBox);

  // --- 커리어
  const career = d.role ? h("div", { class: "card" },
    h("div", { class: "row", style: "justify-content:space-between" }, h("h3", { style: "margin:0" }, "커리어 스킬 – 40점"), careerCounter),
    h("p", { class: "dim small" }, "첫 줄은 역할의 특수능력(최소 1). 각 스킬 최대 10. 판정 = 능력치 + 스킬 + 1D10."),
    h("table", { class: "skill-table" }, d.slots.map((s, i) => h("tr", {},
      h("td", {}, s.choice ? select(s.options.map((o) => [o, o]), s.name, (v) => { s.name = v; recheck(refreshSide); }) : h("b", {}, s.name),
        i === 0 ? h("span", { class: "badge pink", style: "margin-left:8px" }, "특수능력") : null),
      h("td", { class: "stat-tag" }, S.cg.skill_stat[s.name] || ""),
      h("td", {}, h("input", { type: "number", min: 0, max: 10, value: s.value, oninput: change((e) => (s.value = +e.target.value || 0)) })))))) : null;

  // --- 픽업
  const careerNames = new Set(d.slots.map((s) => s.name));
  const allSkills = Object.entries(S.cg.skills).flatMap(([st, l]) => l.map((n) => [n, `${n} (${st})`])).filter(([n]) => !careerNames.has(n)).sort();
  const pickup = d.role ? h("div", { class: "card" },
    h("div", { class: "row", style: "justify-content:space-between" }, h("h3", { style: "margin:0" }, "픽업 스킬 – REF+INT 점"), pickCounter),
    h("p", { class: "dim small" }, "커리어에 없는 아무 스킬에 자유롭게. 언어(Know Language)·전문지식(Expert)도 여기서."),
    h("table", { class: "skill-table" }, d.pickupRows.map((r, i) => h("tr", {},
      h("td", {}, select([["", "— 스킬 선택 —"], ...allSkills], r.name, (v) => { r.name = v; recheck(refreshSide); })),
      h("td", {}, h("input", { type: "number", min: 0, max: 10, value: r.value, oninput: change((e) => (r.value = +e.target.value || 0)) }),
        h("button", { class: "sm ghost", onclick: () => { d.pickupRows.splice(i, 1); render(); recheck(render); } }, "✕"))))),
    h("button", { class: "sm cyan", style: "margin-top:8px", onclick: () => { d.pickupRows.push({ name: "", value: 1 }); render(); } }, "＋ 스킬 추가")) : null;

  // --- 라이프패스
  const lp = d.lifepath;
  const lines = (arr) => (arr || []).join("\n");
  const lifepath = h("div", { class: "card" },
    h("div", { class: "row", style: "justify-content:space-between" }, h("h3", { style: "margin:0" }, "라이프패스 (배경)"),
      h("button", { class: "cyan sm", onclick: async () => {
        if (lp && !confirm("라이프패스를 새로 굴릴까요? 고친 내용은 사라집니다.")) return;
        const r = await guard(() => POST("/api/chargen/lifepath", { age: d.age || null }));
        if (r) { d.lifepath = r; if (!d.age) d.age = r.age; render(); }
      } }, lp ? "다시 굴리기" : "🎲 라이프패스 굴리기")),
    h("p", { class: "dim small" }, "표를 굴려 배경을 만듭니다. 적·빚·옛 연인은 AI GM 이 이야기에 엮습니다. 마음대로 고쳐도 됩니다."),
    lp ? h("div", {},
      field("스타일", h("input", { type: "text", class: "wide", value: lp.style, oninput: (e) => (lp.style = e.target.value) })),
      field("출신 · 모국어", h("input", { type: "text", class: "wide", value: lp.ethnic, oninput: (e) => (lp.ethnic = e.target.value) })),
      h("div", { class: "grid2" },
        field("가족", h("textarea", { rows: 5, oninput: (e) => (lp.family = e.target.value.split("\n").filter(Boolean)) }, lines(lp.family))),
        field("동기 · 성격", h("textarea", { rows: 5, oninput: (e) => (lp.motivations = e.target.value.split("\n").filter(Boolean)) }, lines(lp.motivations)))),
      field("인생 사건 (나이: 내용)", h("textarea", { rows: 6, oninput: (e) => (lp.events = e.target.value.split("\n").filter(Boolean).map((l) => {
        const mm = l.match(/^(\d+)\s*세?\s*[:：]\s*(.*)$/); return mm ? { age: +mm[1], text: mm[2] } : { age: "", text: l }; })) },
        (lp.events || []).map((e) => `${e.age}세: ${e.text}`).join("\n")))) : null);

  // --- 자금·장비
  const lvl = d.slots[0]?.value || 1;
  const gear = h("div", { class: "card" }, h("h3", {}, "자금 · 사이버웨어 · 장비"),
    d.role ? h("div", { class: "row" },
      h("button", { class: "cyan sm", onclick: async () => {
        const r = await guard(() => POST("/api/chargen/money", { role: d.role, level: lvl }));
        if (r) { d.money = r; render(); }
      } }, d.money ? "다시 굴리기" : "🎲 시작 자금 굴리기"),
      d.money ? h("span", {}, h("b", { class: "mono" }, `${d.money.cash.toLocaleString()} eb`),
        h("span", { class: "dim small" }, ` = 월급 ${d.money.salary.toLocaleString()} × ${d.money.months}개월 (1D6=${d.money.months_roll}÷3) · 직업 1D6=${d.money.job_roll} ${d.money.unemployed ? "→ 현재 실직 중" : "→ 재직 중"}`))
        : h("span", { class: "dim small" }, `특수능력 ${lvl} 기준 월급 × 1D6÷3 개월`)) : h("p", { class: "dim small" }, "역할을 먼저 고르세요."),
    h("h3", { style: "margin-top:16px" }, "사이버웨어"),
    h("table", { class: "skill-table" }, d.cyberware.map((c, i) => h("tr", {},
      h("td", {}, h("input", { type: "text", class: "wide", value: c.name, placeholder: "예) Cyberoptics + Low-lite", oninput: (e) => (c.name = e.target.value) })),
      h("td", {}, "HL ", h("input", { type: "number", min: 0, value: c.hl, oninput: change((e) => (c.hl = +e.target.value || 0)) }),
        h("button", { class: "sm ghost", onclick: () => { d.cyberware.splice(i, 1); render(); recheck(render); } }, "✕"))))),
    h("button", { class: "sm cyan", style: "margin:8px 0 14px", onclick: () => { d.cyberware.push({ name: "", hl: 0 }); render(); } }, "＋ 사이버웨어"),
    h("span", { class: "dim small" }, "  HL = 휴머니티 손실(설치 시 굴린 값)"),
    field("장비 (한 줄에 하나)", h("textarea", { rows: 5, placeholder: "Militech Arms Avenger (중형 권총) 250eb\n아머재킷 경량 SP14 150eb\n…", oninput: (e) => (d.gear = e.target.value) }, d.gear || "")),
    field("메모 (외모·성격·말버릇)", h("textarea", { rows: 3, oninput: (e) => (d.notes = e.target.value) }, d.notes || "")));

  const notionChk = h("input", { type: "checkbox", checked: !!S.camp.notion_ready });
  const doSave = async (force) => {
    const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/character`, { character: draftToChar(d), force, notion: notionChk.checked, draft_key: draftKey(d) }));
    if (!r) return;
    if (!r.saved) { S.problems = r.problems; refreshSide(); toast("규칙상 문제가 있습니다. 고치거나 ‘그래도 저장’을 누르세요.", "err"); return; }
    toast(`${r.character.handle} 저장${r.notion === "ok" ? " · Notion 기록" : ""}`, "ok");
    if (r.notion && r.notion !== "ok") toast(r.notion, "err");
    clearTimeout(draftTimer);
    await refreshCamp();
    S.draft = draftFrom(r.character);
    S.draftSnap = JSON.stringify(S.draft);
    render();
  };
  const actions = h("div", { class: "sticky-actions" }, problemsBox, h("span", { style: "flex:1" }),
    S.camp.notion_ready ? h("label", { class: "check" }, notionChk, "Notion 에 시트 기록 (선택)") : null,
    h("button", { class: "primary", onclick: () => doSave(false) }, "저장"),
    h("button", { class: "ghost", onclick: () => doSave(true) }, "그래도 저장"),
    (S.camp.drafts || {})[draftKey(d)] && S.camp.characters.some((c) => c.id === d.id) ? h("button", { class: "sm ghost", onclick: async () => {
      if (!confirm("저장하지 않은 수정 내용을 버리고 마지막 저장본으로 되돌릴까요?")) return;
      clearTimeout(draftTimer);
      await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/draft`, { key: draftKey(d), draft: null }));
      await refreshCamp();
      S.draft = draftFrom(S.camp.characters.find((c) => c.id === d.id)); S.draftSnap = JSON.stringify(S.draft); render(); recheck(render);
    } }, "저장본으로 되돌리기") : null,
    d.id ? h("button", { class: "danger sm", onclick: async () => {
      if (!confirm(`${d.handle} 를 삭제할까요? (Notion 기록은 남습니다)`)) return;
      S.camp = await guard(() => api("DELETE", `/api/campaign/${encodeURIComponent(S.camp.id)}/character/${d.id}`)); S.draft = null; render();
    } }, "삭제") : null);

  wrap.addEventListener("input", markDirty);
  wrap.addEventListener("change", markDirty);
  wrap.addEventListener("click", (e) => { if (e.target.closest(".choice, button:not(.primary):not(.ghost):not(.danger)")) markDirty(); });
  wrap.append(basics, aiBox, roles, stats, career || "", pickup || "", lifepath, gear, actions);
  refreshSide();
  return wrap;
}

// ------------------------------------------------------------------ ④ 플레이
const WOUNDS = ["무사", "경상 Light", "중상 Serious", "치명 Critical", "빈사0 Mortal", "빈사1", "빈사2", "빈사3", "빈사4", "빈사5", "빈사6"];
const woundOf = (dmg) => WOUNDS[Math.min(10, Math.ceil((+dmg || 0) / 4))];

async function loadPlay(session) {
  if (!S.camp) return;
  const r = await guard(() => GET(`/api/campaign/${encodeURIComponent(S.camp.id)}/play${session || S.play.session ? `?session=${encodeURIComponent(session || S.play.session)}` : ""}`));
  if (!r) return;
  Object.assign(S.play, { session: r.session, sessions: r.sessions, log: r.log, sent: new Set(r.sent_scenes), scenes: r.scenes, sessionText: r.session_text, unlogged: r.unlogged });
  if (S.tab === "play") render();
}
function scrollLog() { const l = $(".log"); if (l) l.scrollTop = l.scrollHeight; }
function lastScene() {
  for (let i = S.play.log.length - 1; i >= 0; i--) {
    const segs = S.play.log[i].segments || [];
    for (let j = segs.length - 1; j >= 0; j--) if (segs[j].kind === "scene") return segs[j];
  }
  return null;
}

async function sendTurn(text, actor, kind = "player") {
  if (S.play.busy) return;
  S.play.busy = true;
  S.play.log.push({ role: "user", text, actor, kind, pendingView: true });
  render();
  const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/play/turn`, { session: S.play.session, text, actor, kind }));
  S.play.busy = false;
  S.play.log = S.play.log.filter((x) => !x.pendingView);
  if (r) {
    S.play.log.push(...r.new);
    (r.auto_sent || []).forEach((id) => S.play.sent.add(id));
    if (r.unlogged !== undefined) S.play.unlogged = r.unlogged;
    if (r.notion_error) toast(`Notion: ${r.notion_error}`, "err");
    await refreshCamp();
  } else {
    await loadPlay();
  }
  render();
}

async function sendScene(id) {
  const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/scene/send`, { session: S.play.session, scene_id: id }), `장면 ${id} → Notion 기록`);
  if (r) { S.play.sent.add(id); await loadPlay(); }
}

function sceneCard(seg) {
  const sent = S.play.sent.has(seg.id);
  return h("div", { class: "scene" },
    seg.image ? h("img", { src: `/img/${encodeURIComponent(seg.image)}`, alt: "", onerror: (e) => e.target.remove() }) : null,
    h("div", { class: "body" },
      h("div", { class: "title" }, `🎬 ${seg.id} · ${seg.title}`),
      h("div", { class: "meta" }, [seg.location, seg.time].filter(Boolean).join(" · ")),
      h("div", { class: "narr" }, seg.narration),
      h("div", { class: "acts" },
        sent ? h("span", { class: "badge ok" }, "Notion 기록됨") :
          (S.camp.notion_ready ? h("button", { class: "sm cyan", onclick: () => sendScene(seg.id) }, "Notion 에 기록") : null),
        seg.image ? h("span", { class: "dim small" }, `🖼 ${seg.image}`) : null)));
}

function renderItem(it) {
  if (it.role === "user") {
    const auto = it.kind === "auto_roll";
    return h("div", { class: `msg user ${auto ? "auto" : ""}` },
      h("div", { class: "actor" }, auto ? "🎲 프로그램 주사위" : (it.actor || "운영자")),
      h("div", { class: "bubble", html: md(it.text) }));
  }
  return h("div", { class: "msg gm" }, h("div", { class: "who" }, "GM"),
    (it.segments || []).map((s) => {
      if (s.kind === "scene") return sceneCard(s);
      if (s.kind === "check") {
        const done = Object.values(S.play.rolled).find((x) => x.seg === s);
        return h("div", {}, h("span", { class: "rollreq", style: "color:var(--cyan);border-color:#1d5a66" },
          `🎲 판정 요청 · ${s.who || "?"}: ${s.stat}${s.skill ? ` + ${s.skill}` : ""} + 1D10${s.diff ? ` · 난이도 ${s.diff}` : ""}${s.why ? ` — ${s.why}` : ""}`));
      }
      if (s.kind === "rollreq") return h("div", {}, h("span", { class: "rollreq" }, `🎲 GM 굴림 요청 · ${s.expr}  ${s.why}`));
      if (s.kind === "gm") return h("div", { class: "gmnote" }, "🔒 GM 메모: ", s.text);
      return h("div", { class: "text", html: md(s.text) });
    }));
}

// ---- GM 판정 요청 → 주사위 창 자동 채우기
const STAT_KEYS = ["INT", "REF", "TECH", "COOL", "ATTR", "LUCK", "MA", "BODY", "EMP"];
const normSk = (x) => String(x || "").toLowerCase().replace(/[^a-z0-9가-힣]/g, "");
function findChar(who, chars) {
  if (!chars.length) return null;
  const w = normSk(who);
  return (w && (chars.find((c) => normSk(c.handle) === w) || chars.find((c) => normSk(c.player) === w)
    || chars.find((c) => w.includes(normSk(c.handle)) || normSk(c.handle).includes(w))))
    || chars.find((c) => c.handle === S.play.actor) || (chars.length === 1 ? chars[0] : null);
}
function findSkill(name, ch) {
  if (!name) return "";
  const all = ch ? Object.keys({ ...ch.career, ...ch.pickup }) : [];
  const n = normSk(name);
  return all.find((k) => normSk(k) === n) || all.find((k) => normSk(k).includes(n) || n.includes(normSk(k))) || name;
}
// AI 가 태그 없이 "REF + Handgun + 1D10, 난이도 20" 처럼 쓴 경우를 읽어 냄
function parseChecksFromText(text, chars) {
  const out = [];
  const re = new RegExp(`\\b(${STAT_KEYS.join("|")})\\b\\s*\\+\\s*(?:([A-Za-z][A-Za-z/&.:\\- ]*?)\\s*\\+\\s*)?1\\s*D\\s*10`, "gi");
  for (const line of String(text).split("\n")) {
    let m;
    while ((m = re.exec(line))) {
      const after = line.slice(m.index);
      const d = after.match(/(?:난이도|명중값|목표값|DC)\s*[:：]?\s*(\d{1,2})/) || line.match(/(?:난이도|명중값|목표값|DC)\s*[:：]?\s*(\d{1,2})/);
      const who = chars.find((c) => line.includes(c.handle))?.handle || "";
      out.push({ kind: "check", who, stat: m[1].toUpperCase(), skill: (m[2] || "").trim(), diff: d ? d[1] : "", mod: "0", why: "", guessed: true });
    }
  }
  return out;
}
function currentChecks() {
  const log = S.play.log;
  for (let i = log.length - 1; i >= 0; i--) {
    const it = log[i];
    if (it.role === "user" && it.kind !== "auto_roll") return [];       // 이미 답한 뒤
    if (it.role !== "assistant") continue;
    const segs = it.segments || [];
    let checks = segs.filter((x) => x.kind === "check");
    if (!checks.length) checks = segs.filter((x) => x.kind === "text").flatMap((x) => parseChecksFromText(x.text, S.camp.characters));
    return checks.map((c, n) => ({ ...c, key: `${i}:${n}`, seg: c }));
  }
  return [];
}
// 솔로의 Combat Sense 는 인지(Awareness) 판정에 더해진다
const combatSense = (ch, skill) => (ch && ch.role === "Solo" && normSk(skill).startsWith("awareness") ? +(ch.career?.["Combat Sense"] || 0) : 0);
function checkState(chk, chars) {
  if (!S.play.checkState[chk.key]) {
    const ch = findChar(chk.who, chars);
    const skill = findSkill(chk.skill, ch);
    let stat = STAT_KEYS.includes(chk.stat) ? chk.stat : (S.cg.skill_stat[skill] && S.cg.skill_stat[skill] !== "-" ? S.cg.skill_stat[skill] : "REF");
    let mod = parseInt(chk.mod, 10) || 0;
    const cs = combatSense(ch, skill);
    if (cs && (mod === cs || /combat\s*sense/i.test(chk.why || ""))) mod = Math.max(0, mod - cs);   // AI 가 넣었으면 중복 제거
    S.play.checkState[chk.key] = { ch: ch?.id || "", stat, skill, mod, luck: 0, diff: parseInt(chk.diff, 10) || 0 };
  }
  return S.play.checkState[chk.key];
}
async function rollCheck(chk, chars, all) {
  const st = checkState(chk, chars);
  const ch = chars.find((c) => c.id === st.ch);
  if (!ch) return toast("굴릴 캐릭터를 고르세요.", "err");
  const skills = { ...ch.career, ...ch.pickup };
  const sv = +ch.stats[st.stat] || 0, kv = st.skill ? +(skills[st.skill] || 0) : 0;
  const cs = combatSense(ch, st.skill);
  const base = sv + kv + cs + st.mod + st.luck;
  const r = await guard(() => POST("/api/roll", { expr: `1D10${base >= 0 ? "+" : "-"}${Math.abs(base)}` }));
  if (!r) return;
  const ok = st.diff ? r.total >= st.diff : null;
  const label = `${ch.handle}${chk.why ? ` – ${chk.why}` : ""}: ${st.stat} ${sv}${st.skill ? ` + ${st.skill} ${kv}` : ""}${cs ? ` + Combat Sense ${cs}` : ""}${st.mod ? ` + 수정 ${st.mod}` : ""}${st.luck ? ` + LUCK ${st.luck}` : ""} + 1D10`;
  const line = `[주사위] ${label}: ${r.text}${st.diff ? ` vs 난이도 ${st.diff} → ${ok ? "성공" : "실패"}` : ""}`;
  S.play.rolled[chk.key] = { line, total: r.total, ok, note: r.note, seg: chk.seg, actor: ch.handle };
  S.play.pending.push(line);
  if (st.luck) {
    await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/character/${ch.id}/status`, { luck_used: (+(ch.status?.luck_used) || 0) + st.luck }));
    await refreshCamp();
  }
  const left = all.filter((c) => !S.play.rolled[c.key]);
  if (!left.length && S.play.autoSend) {
    const actors = [...new Set(all.map((c) => S.play.rolled[c.key].actor))];
    const body = S.play.pending.join("\n");
    S.play.pending = [];
    toast(`${r.total}${ok === null ? "" : ok ? " · 성공" : " · 실패"} – GM 에게 전달합니다.`, ok === false ? "err" : "ok");
    return sendTurn(body, actors.length === 1 ? actors[0] : "운영자");
  }
  render();
}
function checkPanel(checks, chars) {
  const skillOpts = (ch, cur) => {
    const sk = ch ? Object.entries({ ...ch.career, ...ch.pickup }).filter(([, v]) => +v > 0).map(([k, v]) => [k, `${k} +${v}`]) : [];
    if (cur && !sk.some(([k]) => k === cur)) sk.unshift([cur, `${cur} (없음 → 0)`]);
    return [["", "스킬 없음"], ...sk];
  };
  return h("div", { class: "dicebox checkbox" },
    h("div", { class: "row", style: "margin-bottom:6px" },
      h("b", { style: "color:var(--cyan)" }, `🎲 GM 판정 요청 (${checks.length})`),
      checks.some((c) => c.guessed) ? h("span", { class: "dim small" }, "GM 설명에서 읽어 냄 – 맞는지 확인하세요") : null,
      h("span", { style: "flex:1" }),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: S.play.autoSend, onchange: (e) => (S.play.autoSend = e.target.checked) }), "다 굴리면 GM 에게 자동 전달")),
    checks.map((chk) => {
      const st = checkState(chk, chars);
      const ch = chars.find((c) => c.id === st.ch);
      const done = S.play.rolled[chk.key];
      const sv = ch ? +ch.stats[st.stat] || 0 : 0, kv = ch && st.skill ? +({ ...ch.career, ...ch.pickup }[st.skill] || 0) : 0;
      return h("div", { class: `checkrow ${done ? "done" : ""}` },
        chk.why ? h("div", { class: "small", style: "margin-bottom:4px" }, chk.why) : null,
        h("div", { class: "row" },
          select([["", "캐릭터"], ...chars.map((c) => [c.id, c.handle])], st.ch, (v) => { st.ch = v; render(); }, { disabled: !!done }),
          ch ? select(STAT_KEYS.map((k) => [k, `${k} ${ch.stats[k]}`]), st.stat, (v) => { st.stat = v; render(); }, { disabled: !!done }) : null,
          ch ? select(skillOpts(ch, st.skill), st.skill, (v) => { st.skill = v; render(); }, { disabled: !!done }) : null,
          h("span", { class: "small dim" }, "수정", h("input", { type: "number", value: st.mod, disabled: !!done, onchange: (e) => { st.mod = +e.target.value || 0; render(); } })),
          ch ? h("span", { class: "small dim" }, "LUCK", h("input", { type: "number", min: 0, max: Math.max(0, (ch.stats.LUCK || 0) - (ch.status?.luck_used || 0)), value: st.luck, disabled: !!done, onchange: (e) => { st.luck = +e.target.value || 0; render(); } })) : null,
          select([[0, "난이도 –"], [10, "쉬움 10"], [15, "보통 15"], [20, "어려움 20"], [25, "매우 어려움 25"], [30, "거의 불가 30"],
            ...(st.diff && ![10, 15, 20, 25, 30].includes(st.diff) ? [[st.diff, `목표 ${st.diff}`]] : [])], st.diff, (v) => { st.diff = +v; render(); }, { disabled: !!done }),
          done ? h("span", { class: `rollres ${done.ok === false ? "fail" : done.ok ? "ok" : ""}` },
              `${done.total}${done.ok === null ? "" : done.ok ? " 성공" : " 실패"}${done.note ? " ⚡" : ""}`)
            : h("button", { class: "primary sm", disabled: S.play.busy || !ch, onclick: () => rollCheck(chk, chars, checks) },
              `🎲 굴리기${ch ? ` (1D10+${sv + kv + combatSense(ch, st.skill) + st.mod + st.luck})` : ""}`)),
        done ? h("div", { class: "mono small dim", style: "margin-top:4px" }, done.line.replace(/\*\*/g, "")) : null);
    }));
}

function diceBox(chars) {
  const st = { ch: chars[0]?.id || "", stat: "REF", skill: "", mod: 0, diff: 0, luck: 0, free: "" };
  const box = h("div", { class: "dicebox" });
  const draw = () => {
    const ch = chars.find((c) => c.id === st.ch);
    const skills = ch ? Object.entries({ ...ch.career, ...ch.pickup }).filter(([, v]) => +v > 0) : [];
    box.replaceChildren(
      h("div", { class: "row" },
        select([["", "(자유 굴림)"], ...chars.map((c) => [c.id, c.handle])], st.ch, (v) => { st.ch = v; draw(); }),
        ch ? select(S.cg.stats.map(([k]) => [k, `${k} ${ch.stats[k]}`]), st.stat, (v) => (st.stat = v)) : null,
        ch ? select([["", "스킬 없음"], ...skills.map(([k, v]) => [k, `${k} +${v}`])], st.skill, (v) => {
          st.skill = v; const stat = S.cg.skill_stat[v]; if (stat && stat !== "-") { st.stat = stat; } draw(); }) : null,
        ch ? h("span", { class: "small dim" }, "수정", h("input", { type: "number", value: st.mod, oninput: (e) => (st.mod = +e.target.value || 0) })) : null,
        ch ? h("span", { class: "small dim" }, "LUCK", h("input", { type: "number", min: 0, value: st.luck, oninput: (e) => (st.luck = +e.target.value || 0) })) : null,
        ch ? select([[0, "난이도 –"], [10, "쉬움 10"], [15, "보통 15"], [20, "어려움 20"], [25, "매우 어려움 25"], [30, "거의 불가 30"]], st.diff, (v) => (st.diff = +v)) : null,
        !ch ? h("input", { type: "text", placeholder: "예) 3D6, 1D10+12", value: st.free, oninput: (e) => (st.free = e.target.value) }) : null,
        h("button", { class: "cyan sm", onclick: async () => {
          let expr, label;
          if (ch) {
            const sv = +ch.stats[st.stat] || 0, kv = st.skill ? +({ ...ch.career, ...ch.pickup }[st.skill] || 0) : 0;
            const base = sv + kv + st.mod + st.luck;
            expr = `1D10${base >= 0 ? "+" : "-"}${Math.abs(base)}`;
            label = `${ch.handle}: ${st.stat} ${sv}${st.skill ? ` + ${st.skill} ${kv}` : ""}${st.mod ? ` + 수정 ${st.mod}` : ""}${st.luck ? ` + LUCK ${st.luck}` : ""} + 1D10`;
          } else { expr = st.free; label = "자유 굴림"; }
          const r = await guard(() => POST("/api/roll", { expr }));
          if (!r) return;
          let res = r.text;
          if (ch && st.diff) res += ` vs 난이도 ${st.diff} → ${r.total >= st.diff ? "성공" : "실패"}`;
          S.play.pending.push(`[주사위] ${label}: ${res}`);
          if (ch && st.luck) {
            await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/character/${ch.id}/status`, { luck_used: (+(ch.status?.luck_used) || 0) + st.luck }));
            await refreshCamp();
          }
          render();
        } }, "🎲 굴리기")));
  };
  draw();
  return box;
}

function viewPlay() {
  const chars = S.camp.characters;
  const party = h("section", { class: "party" }, h("h3", {}, "파티"),
    chars.length ? null : h("p", { class: "dim small" }, "캐릭터가 없습니다. ③ 에서 만드세요."),
    chars.map((ch) => {
      const s = ch.status || {};
      const setS = async (k, v) => { await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/character/${ch.id}/status`, { [k]: v })); await refreshCamp(); render(); };
      return h("div", { class: "pc" },
        h("div", { class: "name" }, ch.handle), h("div", { class: "role" }, `${S.cg.roles[ch.role]?.ko || ch.role} · ${ch.player || "NPC"}`),
        h("div", { class: "st" }, S.cg.stats.map(([k]) => h("span", {}, `${k} `, h("b", {}, ch.stats[k]), "  "))),
        h("div", { class: "track" }, "피해", h("button", { class: "sm", onclick: () => setS("damage", Math.max(0, (s.damage || 0) - 1)) }, "−"),
          h("b", { class: "mono" }, s.damage || 0), h("button", { class: "sm", onclick: () => setS("damage", Math.min(40, (s.damage || 0) + 1)) }, "＋"),
          h("span", { class: "wound", style: `background:${(s.damage || 0) > 12 ? "#5a1020" : (s.damage || 0) > 4 ? "#4a3a10" : "#123a24"}` }, woundOf(s.damage))),
        h("div", { class: "track" }, `LUCK ${Math.max(0, (ch.stats.LUCK || 0) - (s.luck_used || 0))}/${ch.stats.LUCK}`,
          h("button", { class: "sm ghost", title: "세션 시작 시 회복", onclick: () => setS("luck_used", 0) }, "회복"),
          h("span", { class: "dim" }, ` BTM ${ch.derived.btm} · 휴머니티 ${ch.derived.humanity}`)));
    }));

  const log = h("div", { class: "log" },
    S.play.log.length ? S.play.log.map(renderItem) :
      h("div", { class: "card", style: "max-width:640px" }, h("h3", {}, "시작하기"),
        h("p", {}, "아래 입력창에 GM 에게 하고 싶은 말을 적어 보내세요."),
        h("div", { class: "row" },
          h("button", { class: "cyan", disabled: !aiReady(), onclick: () => sendTurn("0회차를 시작해줘. 처음 하는 플레이어들을 위해 세계관 소개(도입 장면 S00)부터 해주고, 캐릭터들을 한 명씩 소개할 기회를 줘.", "운영자", "system") }, "0회차 시작 (세계관 소개)"),
          h("button", { disabled: !aiReady(), onclick: () => sendTurn("새 의뢰로 이번 회차를 시작해줘. 캐릭터들이 함께 있는 장면부터.", "운영자", "system") }, "새 의뢰로 시작"))),
    S.play.busy ? h("div", { class: "thinking" }, "GM 이 생각하는 중") : null);

  const actorOpts = [["운영자", "운영자 / 전체"], ...chars.map((c) => [c.handle, `${c.handle} (${c.player || "NPC"})`])];
  if (!S.play.actor) S.play.actor = "운영자";
  const ta = h("textarea", { placeholder: "행동이나 대사를 입력 (Ctrl+Enter 로 보내기). 여러 명이면 '이름: 행동' 을 줄마다.", disabled: S.play.busy });
  const submit = () => {
    const t = ta.value.trim();
    if (!t && !S.play.pending.length) return;
    const actor = S.play.actor;
    const body = [...S.play.pending, t && (actor && actor !== "운영자" ? `${actor}: ${t}` : t)].filter(Boolean).join("\n");
    S.play.pending = [];
    sendTurn(body, actor);
  };
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });
  const showDice = { v: !!S.play.showDice };
  const checks = S.play.busy ? [] : currentChecks();
  const composer = h("div", { class: "composer" },
    checks.length ? checkPanel(checks, chars) : null,
    S.play.showDice ? diceBox(chars) : null,
    S.play.pending.length ? h("div", { class: "chips" }, S.play.pending.map((p, i) => h("span", { class: "chip" }, p,
      h("button", { onclick: () => { S.play.pending.splice(i, 1); render(); } }, "✕")))) : null,
    h("div", { class: "row", style: "margin-bottom:6px" },
      select(actorOpts, S.play.actor, (v) => (S.play.actor = v)),
      h("button", { class: `sm ${S.play.showDice ? "cyan" : ""}`, onclick: () => { S.play.showDice = !showDice.v; render(); } }, "🎲 주사위"),
      h("span", { style: "flex:1" }),
      h("button", { class: "sm ghost", disabled: S.play.busy, onclick: async () => {
        const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/play/retry`, { session: S.play.session }));
        if (r) { S.play.log.pop(); S.play.log.push(...r.new); render(); }
      } }, "↻ 다시 생성"),
      h("button", { class: "sm ghost", disabled: S.play.busy, onclick: async () => {
        if (!confirm("마지막 주고받기를 취소할까요? (이미 Notion 에 기록된 내용은 남습니다)")) return;
        await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/play/undo`, { session: S.play.session })); await loadPlay();
      } }, "↶ 취소")),
    h("div", { class: "row", style: "align-items:stretch" }, h("div", { style: "flex:1" }, ta),
      h("button", { class: "primary", disabled: S.play.busy || !aiReady(), onclick: submit }, S.play.busy ? "…" : "보내기")));

  const bar = h("div", { class: "playbar" },
    h("span", { class: "dim small" }, "세션"),
    select(S.play.sessions, S.play.session, (v) => loadPlay(v)),
    h("button", { class: "sm", onclick: async () => {
      const title = prompt("새 회차 제목", "새 의뢰"); if (!title) return;
      const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/session/new`, { title }), "새 회차를 만들었습니다.");
      if (r) loadPlay(r.session);
    } }, "＋ 새 회차"),
    h("span", { style: "flex:1" }),
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: S.showGM, onchange: (e) => { S.showGM = e.target.checked; document.body.classList.toggle("hide-gm", !S.showGM); } }), "GM 메모 보기"),
    h("button", { class: "sm", disabled: S.play.busy || !S.play.log.length, onclick: async (e) => {
      if (!confirm("AI 가 이번 세션 요약과 IP(경험치) 제안을 써서 세션 기록에 덧붙입니다. 진행할까요?")) return;
      e.target.disabled = true; e.target.textContent = "요약 중…";
      const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/session/summarize`, { session: S.play.session }), "세션 기록에 요약을 추가했습니다.");
      if (r && S.camp.notion_ready && confirm("요약을 Notion 세션 페이지에도 추가할까요?")) {
        await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/session/sync`, { session: S.play.session }), "Notion 에 추가했습니다.");
      }
      loadPlay();
    } }, "📝 세션 요약"));

  // right side – 지금 장면만 + Notion 진행 기록
  const cur = lastScene();
  const gmNotes = S.play.log.flatMap((i) => (i.segments || []).filter((s) => s.kind === "gm").map((s) => s.text)).slice(-8).reverse();
  const auto = S.state.settings.notion_mode === "always";
  const unlogged = S.play.unlogged;
  const side = h("section", { class: "side" },
    h("h3", {}, "현재 장면"),
    cur ? h("div", { class: "current" },
      cur.image ? h("img", { src: `/img/${encodeURIComponent(cur.image)}`, alt: cur.title, onerror: (e) => e.target.remove() })
        : h("div", { class: "noimg" }, "이 장면에 맞는 이미지 없음"),
      h("div", { class: "cur-title" }, `${cur.id} · ${cur.title}`),
      h("div", { class: "dim small" }, [cur.location, cur.time].filter(Boolean).join(" · ")),
      h("div", { class: "cur-narr" }, cur.narration),
      h("div", { style: "margin-top:8px" }, S.play.sent.has(cur.id) ? h("span", { class: "badge ok" }, "Notion 기록됨") :
        (S.camp.notion_ready ? h("button", { class: "sm cyan", onclick: () => sendScene(cur.id) }, "이 장면 Notion 에 기록") : null)))
      : h("div", { class: "noimg" }, "아직 장면이 없습니다. GM 이 장면을 열면 여기에 그 장면의 이미지가 표시됩니다."),
    h("h3", { style: "margin-top:22px" }, "📝 Notion 진행 기록 (선택)"),
    S.camp.notion_ready ? h("div", { class: "card", style: "padding:12px" },
      h("p", { class: "small", style: "margin:0 0 8px" }, auto
        ? "장면이 바뀔 때마다 그 전까지의 행동·대화·판정·결과를 AI 가 요약해 Notion 에 자동 기록합니다."
        : "장면을 Notion 에 기록할 때 그 전까지의 진행이 요약되어 함께 기록됩니다. (① 에서 ‘자동’ 으로 바꿀 수 있음)"),
      h("div", { class: "row" },
        h("span", { class: "small dim" }, unlogged ? `아직 기록 안 된 주고받기 ${unlogged}개` : "모두 기록됨"),
        h("button", { class: "sm cyan", disabled: S.play.busy || !unlogged || unlogged < 2, onclick: async (e) => {
          e.target.disabled = true; e.target.textContent = "요약 중…";
          const r = await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/play/log`, { session: S.play.session }));
          if (r) { toast(r.logged ? "진행 기록을 Notion 에 추가했습니다." : "기록할 내용이 없습니다.", r.logged ? "ok" : ""); S.play.unlogged = r.unlogged; }
          render();
        } }, "지금 요약해서 기록")))
      : h("p", { class: "dim small" }, "선택 기능입니다. 연결하지 않아도 게임은 그대로 진행되고 기록은 이 컴퓨터(campaigns 폴더)에 저장됩니다."),
    h("h3", { style: "margin-top:22px" }, "🔒 GM 메모"),
    gmNotes.length ? gmNotes.map((n) => h("div", { class: "gmnote" }, n)) : h("p", { class: "dim small" }, "없음"),
    h("h3", { style: "margin-top:22px" }, "세션 메모"),
    (() => { const inp = h("input", { type: "text", class: "wide", placeholder: "세션 기록에 한 줄 추가 (플레이어 공개)" });
      return h("div", { class: "row" }, inp, h("button", { class: "sm", onclick: async () => {
        if (!inp.value.trim()) return;
        await guard(() => POST(`/api/campaign/${encodeURIComponent(S.camp.id)}/session/note`, { session: S.play.session, text: inp.value.trim() }), "추가했습니다.");
        inp.value = "";
      } }, "추가")); })());

  return h("div", { class: "play" }, party, h("section", { class: "center" }, bar, log, composer), side);
}

// ------------------------------------------------------------------ start
(async () => {
  try {
    await load();
    S.tab = !aiReady() ? "connect" : !bookReady() ? "book" : !S.camp ? "campaign" : !charsDone() ? "characters" : "play";
    render();
    if (S.tab === "play") loadPlay();
  } catch (e) {
    document.body.innerHTML = `<p style="padding:30px">불러오기 실패: ${esc(e.message)}</p>`;
  }
})();
