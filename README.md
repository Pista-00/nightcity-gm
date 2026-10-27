# NightCity GM
**Cyberpunk 2020 용 비공식 AI GM 도구** · 무료 팬 제작물

내가 고른 AI(Claude 구독 계정 · Claude API · GPT · Gemini · 로컬 모델)가 GM 을 맡고,
한 화면에서 **연결 → 룰북 등록 → 인원 설정 → 캐릭터 생성 → 게임 진행**까지 할 수 있는 로컬 웹 앱입니다.
플레이어들은 Notion 페이지로 장면(이미지 + 서술), 진행 기록, 캐릭터 시트를 함께 봅니다.

> **이 저장소에는 룰북 내용이 들어 있지 않습니다.** 룰북을 가진 사람이 자기 PDF 를 등록해야
> 캐릭터 생성 표와 GM 룰 자료가 내 컴퓨터 안에서 만들어집니다. 등록한 PDF·추출 데이터는 어디에도 업로드되지 않습니다.

## 실행
**필요한 것:** Python 3.10+, Cyberpunk 2020 코어 룰북 PDF(텍스트 검색 가능한 것), 그리고 다음 중 하나
- 유료 Claude 구독(Pro·Max 등) + [Claude Code](https://code.claude.com/docs/en/setup) – 기본
- 또는 Anthropic / OpenAI / Gemini API 키, Ollama, OpenAI 호환 API

```bash
git clone https://github.com/Pista-00/nightcity-gm.git
cd nightcity-gm
```
- **Windows:** `run.bat` 더블클릭 · **macOS:** `run.command` 더블클릭(처음엔 우클릭 → 열기) · 직접: `pip install -r requirements.txt` → `python app.py`

브라우저에서 `http://127.0.0.1:8020` 이 열립니다. 이 주소는 내 컴퓨터에서만 접속됩니다.

## 화면 구성
| 단계 | 하는 일 |
|---|---|
| ① AI · Notion 연결 | 기본은 Claude 구독 계정(Claude Code 로그인 상태 확인). `API 키로 연결` 에서 다른 AI 선택. Notion API 토큰 |
| ② 룰북 등록 | 내 룰북 PDF 선택 → 내 컴퓨터에서 텍스트 추출·책 확인·색인 → AI 로 캐릭터 생성 표 만들기 → (선택) AI 정리본 |
| ③ 캠페인 · 인원 | 캠페인 생성, 플레이어, 능력치 방식, 경험 수준, Notion 기록 페이지 |
| ④ 캐릭터 생성 | 플레이어별 역할 → 능력치 → 커리어/픽업 스킬 → 라이프패스 → 자금·장비. 규칙 검사, AI 초안, 자동 임시 저장 |
| ⑤ 게임 진행 | AI GM 과 대화, 장면 이미지, GM 판정 요청 시 주사위 창 자동 채우기, 피해·LUCK 추적, Notion 진행 기록, 세션 요약 |

## 룰북 등록 – 어떻게 동작하나
1. **PDF 등록:** 앱이 PDF 텍스트를 뽑고, 핵심 용어로 Cyberpunk 2020 코어 룰북이 맞는지 확인한 뒤 검색 색인을 만듭니다. 원본 PDF 사본은 남기지 않습니다.
2. **캐릭터 생성 표:** 연결한 AI 가 내 룰북에서 역할·스킬 목록·월급표·라이프패스 표를 읽어 `book/chargen.json` 으로 정리합니다(몇 분).
3. **GM 룰 자료** (① 에서 선택)
   - **색인 (기본):** 매 턴 지금 상황과 관련된 쪽만 찾아 GM 에게 줍니다. 추가 준비 비용 없음.
   - **AI 정리본 (선택):** 책 전체를 AI 로 GM 레퍼런스로 요약해 둡니다(15~30분, 사용량 많음).
   - **사용 안 함:** AI 의 일반 지식으로 진행(판정 부정확).
4. 모든 결과는 `book/` 폴더(git 제외)에만 저장됩니다. ② 에서 언제든 삭제할 수 있습니다.

## 게임 진행 중
- **행동 입력:** 누가 하는지 고르고 입력 → `Ctrl+Enter`
- **GM 판정 요청:** GM 이 판정을 요청하면 입력창 위에 주사위 창이 자동으로 열리고 캐릭터·능력치·스킬·난이도가 채워집니다. `굴리기` 만 누르면 성공/실패가 나오고 GM 에게 자동 전달됩니다.
- **GM 이 굴리는 주사위**(NPC 공격 등)는 프로그램이 굴려 자동으로 돌려줍니다.
- **장면 · 진행 기록:** 장면이 바뀌면 오른쪽에 그 장면 이미지가 표시되고, Notion 에는 그 전까지의 행동·대화·판정·결과 요약과 새 장면이 자동으로 추가됩니다.
- **🔒 GM 메모:** 화면을 플레이어와 공유할 땐 `GM 메모 보기` 를 끄세요. Notion 에는 올라가지 않습니다.

## Notion 연결
1. [Notion 개발자 포털](https://app.notion.com/developers/connections) → Internal connections → Create a new connection
2. Configuration 탭에서 API 토큰 복사 → ① 에 입력
3. 기록할 Notion 페이지 `•••` → Connections → 만든 연결 추가 → 그 페이지 URL 을 ③ 에 입력

Notion 에는 기존 내용을 바꾸지 않고 **추가만** 합니다. 룰북 내용, AI 대화 원문, GM 메모는 올라가지 않습니다.

## 데이터 위치 (모두 git 제외)
| 위치 | 내용 |
|---|---|
| `.env.local` | API 키·Notion 토큰 ('이 컴퓨터에 저장' 을 고른 경우) |
| `settings.json` | 선택한 AI·모델 등 |
| `book/` | 내 룰북에서 만든 색인·캐릭터 생성 표·정리본 – **공유 금지** |
| `campaigns/` | 캠페인별 캐릭터·세션 기록·장면·AI 대화 기록 |

## 저장소 구성
| 경로 | 내용 |
|---|---|
| `app.py`, `web/` | 로컬 웹 서버(Flask)와 화면 |
| `cp2020/` | 엔진: AI 제공자, 룰북 등록(`book.py`), GM 프롬프트·태그 처리, 캐릭터 생성, 주사위, Notion, 저장 |
| `content/scenes/` | 0회차 도입 장면(창작) |
| `library/` | 장면 이미지 36장(AI 생성)과 카탈로그·생성 프롬프트 |

## 고지
- NightCity GM 은 **무료 비공식 팬 제작 도구**이며 **R. Talsorian Games 의 승인이나 보증을 받지 않았습니다.** Cyberpunk 및 Cyberpunk 2020 은 해당 권리자의 상표입니다.
- 이 저장소는 룰북의 문장·표를 포함하지 않습니다. 룰 데이터는 사용자가 소유한 룰북에서 사용자의 컴퓨터 안에서만 만들어집니다.
- [R. Talsorian Games Homebrew Content Policy](https://rtalsoriangames.com/homebrew-content-policy/) 를 따릅니다(무료 배포, 제목에 게임명 미사용, 고지문 표기).
- 코드 라이선스: MIT (`LICENSE`).
