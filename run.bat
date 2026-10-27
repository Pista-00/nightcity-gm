@echo off
rem Windows: 더블클릭 → 필요한 패키지 설치 후 브라우저로 열림
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.10 이상을 먼저 설치하세요: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
python app.py %*
pause
