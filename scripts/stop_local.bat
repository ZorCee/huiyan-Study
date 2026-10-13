@echo off
chcp 65001 >nul
title 慧眼医学教学实训平台 - 本地一键停止管理器

echo =================================================================
echo        慧眼医学教学实训平台 (Huiyan Medical System)
echo                  正在停止本地服务...
echo =================================================================
echo.

powershell -NoProfile -Command ^
    "$ports = @(8000, 5174); " ^
    "foreach ($p in $ports) { " ^
    "    $conns = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue; " ^
    "    if ($conns) { " ^
    "        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique; " ^
    "        foreach ($id in $pids) { " ^
    "            if ($id -gt 4) { " ^
    "                Stop-Process -Id $id -Force -ErrorAction SilentlyContinue; " ^
    "                Write-Host \"[OK] 已停止占用端口 $p 的进程 PID: $id\"; " ^
    "            } " ^
    "        } " ^
    "    } else { " ^
    "        Write-Host \"[--] 端口 $p 未被占用\"; " ^
    "    } " ^
    "}"

echo.
echo =================================================================
echo                  所有本地服务已成功停止！
echo =================================================================
echo.
pause
