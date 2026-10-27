#!/usr/bin/env bash
# macOS / Linux: 더블클릭 또는 ./run.sh  → 필요한 패키지 설치 후 브라우저로 열림
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
[ -z "$PY" ] && { echo "Python 3.10 이상을 먼저 설치하세요: https://www.python.org/downloads/"; read -r; exit 1; }
[ -d .venv ] || "$PY" -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python app.py "$@"
