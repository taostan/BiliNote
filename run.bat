@echo off
cd /d "%~dp0"

start "Backend" powershell -NoExit -Command "cd backend; python main.py"
start "Frontend" powershell -NoExit -Command "cd BillNote_frontend; pnpm dev"

start http://localhost:3015/