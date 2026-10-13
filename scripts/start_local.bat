@echo off
chcp 65001 >nul
title 慧眼医学教学实训平台 - 本地一键启动管理器

echo =================================================================
echo        慧眼医学教学实训平台 (Huiyan Medical System)
echo                  本地一键启动中，请稍候...
echo =================================================================
echo.

set ROOT_DIR=D:\huiyan-v0
set BACKEND_DIR=%ROOT_DIR%\backend
set FRONTEND_DIR=%ROOT_DIR%\frontend

:: 1. 检查后端端口 8000
netstat -ano | findstr ":8000 " >nul
if %errorlevel% equ 0 (
    echo [OK] 后端服务已在运行 (端口 8000)
) else (
    echo [..] 正在启动后端 FastAPI 服务 (端口 8000)...
    start "慧眼系统-后端服务[8000]" /min cmd /k "cd /d %BACKEND_DIR% && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
    timeout /t 3 /nobreak >nul
)

:: 2. 检查前端端口 5174
netstat -ano | findstr ":5174 " >nul
if %errorlevel% equ 0 (
    echo [OK] 前端服务已在运行 (端口 5174)
) else (
    echo [..] 正在启动前端 Vite 服务 (端口 5174)...
    start "慧眼系统-前端服务[5174]" /min cmd /k "cd /d %FRONTEND_DIR% && npm run dev -- --host 127.0.0.1 --port 5174"
    timeout /t 3 /nobreak >nul
)

echo.
echo =================================================================
echo                      服务启动完成！
echo =================================================================
echo.
echo  【系统访问地址】 http://localhost:5174
echo  【后端接口文档】 http://localhost:8000/docs
echo.
echo  【演示登录账号】
echo    • 系统管理员：admin    /  密码：Admin@123
echo    • 带教老师端：teacher  /  密码：Huiyan@123
echo    • 规培学员端：student  /  密码：Huiyan@123
echo.
echo =================================================================
echo 正在为您自动打开浏览器...
start http://localhost:5174

exit
