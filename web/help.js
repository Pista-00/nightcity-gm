/* 캐릭터 생성 화면용 짧은 설명 – 직접 작성한 한 줄 풀이(룰북 문장 아님) */
"use strict";

const STAT_HELP = {
  INT: "관찰·지식·추리. 인지·교육·해킹처럼 머리 쓰는 판정에 더함",
  REF: "사격·격투·운전·회피 등 몸을 빠르게 쓰는 판정. 전투의 핵심",
  TECH: "수리·제작·전자기기·의료 장비를 다루는 판정",
  COOL: "압박·공포·고문을 버티는 정신력. 위협·심문·거리 감각",
  ATTR: "외모와 첫인상. 꾸미기·패션 판정",
  LUCK: "세션마다 이 점수만큼 원하는 굴림에 보탤 수 있음(굴리기 전에 선언)",
  MA: "이동 속도. 한 라운드에 MA×3m 달림",
  BODY: "체력·근력. 피해 감소(BTM)·기절/사망 저항·운반량을 정함",
  EMP: "사람을 읽고 설득·매혹하는 힘. 사이버웨어를 달수록 줄어듦",
};

const DERIVED_HELP = {
  RUN: "한 전투 라운드(약 3초)에 달릴 수 있는 거리",
  LEAP: "도움닫기 멀리뛰기 거리",
  "휴머니티": "인간성. 사이버웨어마다 깎이고 10 줄 때마다 EMP 1 감소. 바닥나면 사이버사이코",
  "현재 EMP": "휴머니티 손실을 반영한 실제 EMP",
  BTM: "받는 피해에서 빼는 값. 몸이 단단할수록 큼",
  Save: "기절·사망 판정 기준. 1D10 이 이 값 이하면 버팀(부상이 깊을수록 불리)",
  "운반": "들고 다닐 수 있는 무게",
  "픽업 포인트": "커리어 외 스킬에 쓸 수 있는 점수(REF+INT)",
};

const SPECIAL_HELP = {
  combatsense: "위험을 먼저 감지. 인지 판정과 선제권(Initiative)에 더함 – 솔로",
  interface: "넷에 접속해 프로그램과 기능을 다루는 능력 – 넷러너",
  juryrig: "무엇이든 임시로 고쳐 잠시 작동하게 함 – 테키",
  medicaltech: "수술·치료·사이버웨어 이식 – 메드테크",
  credibility: "사람들이 내 보도와 말을 믿게 하는 신뢰도 – 미디어",
  authority: "법의 권위로 위협·체포·수색 – 경찰",
  resources: "회사의 차량·인력·자금을 끌어오는 능력 – 코퍼릿",
  streetdeal: "암시장에서 정보·물건·사람을 구함 – 픽서",
  family: "노매드 일족의 사람·장비·정보를 부름 – 노매드",
  charismaticleadership: "군중을 선동하고 이끔 – 로커보이",
};

const SKILL_HELP = {
  // ATTR
  personalgrooming: "외모 관리·첫인상 꾸미기",
  wardrobestyle: "옷과 스타일로 분위기를 연출",
  // BODY
  endurance: "고통·피로·악조건을 오래 버팀",
  strengthfeat: "문 부수기·들어 올리기 같은 힘 쓰기",
  swimming: "수영",
  // COOL
  interrogation: "심문해서 원하는 정보를 캐냄",
  intimidate: "겁을 줘서 상대를 굴복시킴",
  oratory: "연설로 청중을 움직임",
  resisttorturedrugs: "고문·약물에 버팀",
  streetwise: "뒷골목 감각. 불법 물건·사람 구하기, 위험 피하기",
  // EMP
  humanperception: "거짓말·감정·속셈을 알아챔",
  interview: "대화로 상대의 이야기·사연을 끌어냄",
  leadership: "사람들을 이끌고 지휘",
  seduction: "매혹해서 마음을 얻음",
  social: "상류층 사교·예절",
  persuasionfasttalk: "말로 설득하거나 둘러대기",
  persuasion: "말로 설득하거나 둘러대기",
  perform: "노래·연기 등 공연",
  // INT
  accounting: "회계·장부 분석",
  anthropology: "문화·사회 집단에 대한 지식",
  awarenessnotice: "주변 관찰·단서 발견·위험 감지 (가장 자주 쓰는 스킬)",
  biology: "생물학",
  botany: "식물학",
  chemistry: "화학 – 약물·폭약 재료 등",
  composition: "글·노래·프로그램 문서 작성",
  diagnoseillness: "증상을 보고 병·부상 진단",
  diagnose: "증상을 보고 병·부상 진단",
  educationgenknowledge: "일반 상식·교육 수준",
  education: "일반 상식·교육 수준",
  expert: "특정 분야 전문 지식(분야를 정해서 씀)",
  gamble: "도박과 확률 감각",
  geology: "지질학",
  hideevade: "추적을 따돌리고 숨기",
  history: "역사 지식",
  knowlanguage: "외국어(언어마다 따로)",
  librarysearch: "자료·데이터베이스 검색",
  mathematics: "수학",
  physics: "물리학",
  programming: "프로그램 작성",
  shadowtrack: "미행·추적",
  stockmarket: "주식·금융 시장",
  systemknowledge: "넷의 구조와 주요 시스템에 대한 지식",
  teaching: "남에게 가르치기",
  wildernesssurvival: "야외에서 살아남기",
  zoology: "동물학",
  // REF
  archery: "활·석궁",
  athletics: "달리기·등반·던지기·균형",
  brawling: "주먹다짐 같은 맨손 싸움",
  dance: "춤",
  dodgeescape: "근접 공격 피하기·붙잡힌 상태에서 빠져나오기",
  driving: "자동차 운전",
  drive: "자동차 운전",
  fencing: "검술",
  handgun: "권총 사격",
  heavyweapons: "로켓·유탄발사기 등 중화기",
  martialarts: "무술(유파마다 따로). 근접 피해 보너스",
  martialart: "무술(유파마다 따로). 근접 피해 보너스",
  melee: "칼·곤봉 등 근접 무기와 사이버 무기",
  motorcycle: "오토바이 운전",
  operatehvymachinery: "중장비 조종",
  pilotgyro: "자이로콥터 조종",
  pilotfixedwing: "비행기 조종",
  pilotdirigible: "비행선 조종",
  pilotvectthrust: "수직이착륙기(AV) 조종",
  rifle: "소총·산탄총 사격",
  stealth: "들키지 않게 움직이기",
  submachinegun: "기관단총 사격",
  // TECH
  aerotech: "항공기 정비",
  avtech: "수직이착륙기(AV) 정비",
  basictech: "기본 기계·전기 수리",
  cryotankoperation: "냉동 보존 장치 조작",
  cyberdeckdesign: "사이버덱 설계·개조",
  cybertech: "사이버웨어 정비·개조",
  demolitions: "폭발물 설치·해체",
  disguise: "변장",
  electronics: "전자기기 수리·조작",
  electsecurity: "전자 보안(잠금·경보) 설치·해제",
  firstaid: "응급 처치",
  forgery: "문서 위조",
  gyrotech: "자이로콥터 정비",
  paintordraw: "그림",
  photofilm: "사진·영상 촬영",
  pharmaceuticals: "약 조제",
  picklock: "자물쇠 따기",
  pickpocket: "소매치기·손재주",
  playinstrument: "악기 연주",
  weaponsmith: "무기 수리·제작",
  weaponstech: "무기 수리·정비",
  ...SPECIAL_HELP,
};

const normHelp = (x) => String(x || "").toLowerCase().replace(/[^a-z0-9]/g, "");
function skillHelp(name) {
  if (!name) return "";
  const parts = String(name).split("|");
  if (parts.length > 1) return parts.map((p) => `${p}: ${skillHelp(p) || "-"}`).join(" / ");
  const n = normHelp(name);
  if (SKILL_HELP[n]) return SKILL_HELP[n];
  const k = Object.keys(SKILL_HELP).find((key) => n.startsWith(key) || key.startsWith(n));
  return k ? SKILL_HELP[k] : "";
}
