@echo off
cd /d "%~dp0"
if not exist data mkdir data
call .venv\Scripts\activate
python pull.py >> data\pull_log.txt 2>&1
