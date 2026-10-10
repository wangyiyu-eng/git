# fix_python.ps1 —— 修复 Windows 把 python 命令劫持到 Microsoft Store 的问题
# 用法：以管理员身份运行（右键 PowerShell → 以管理员身份运行），再执行此脚本

$ErrorActionPreference = "Stop"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  修复 Python 调用（Windows 应用执行别名冲突）" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# ---- 1. 找到真实 Python ----
$candidates = @(
    'C:\Users\kz\AppData\Local\Programs\Python\Python312\python.exe',
    'C:\Users\kz\AppData\Local\Programs\Python\Python311\python.exe',
    'C:\Python312\python.exe',
    'C:\Python311\python.exe'
)
$py = $null
foreach ($c in $candidates) {
    if (Test-Path $c) { $py = $c; break }
}
if (-not $py) {
    Write-Host "[X] 没找到 Python 3.12/3.11 安装位置，请确认是否已安装" -ForegroundColor Red
    Write-Host "    下载地址: https://www.python.org/downloads/" -ForegroundColor Yellow
    pause; exit 1
}
Write-Host "[OK] 真实 Python 路径: $py" -ForegroundColor Green
$pyDir = Split-Path $py -Parent
$scriptsDir = Join-Path $pyDir "Scripts"

# ---- 2. 禁用 Microsoft Store 的 python.exe / python3.exe 应用执行别名（当前用户级别，无需管理员）----
Write-Host ""
Write-Host "[1/3] 禁用应用执行别名（HKCU，无需管理员）..." -ForegroundColor Yellow
$aliasPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Execution Aliases'

foreach ($name in @('python.exe', 'python3.exe')) {
    $full = "$aliasPath\$name"
    if (Test-Path $full) {
        try {
            Set-ItemProperty -Path $full -Name "(default)" -Value "" -ErrorAction Stop
            # 同时写入空字符串覆盖
            $key = Get-Item -Path $full
            New-ItemProperty -Path $full -Name "Disabled" -Value 1 -PropertyType DWord -Force -ErrorAction SilentlyContinue | Out-Null
            # 最稳妥：直接删除这个别名键
            Remove-Item -Path $full -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "  - 已禁用 $name" -ForegroundColor Green
        } catch {
            Write-Host "  - 跳过 $name（可能需要管理员）: $_" -ForegroundColor DarkYellow
        }
    } else {
        Write-Host "  - $name 不在 HKCU 别名中（已是干净的）" -ForegroundColor DarkGray
    }
}

# HKLM 级别（需要管理员）
Write-Host ""
Write-Host "[2/3] 尝试禁用 HKLM 级别别名（若失败，请右键以管理员身份重跑）..." -ForegroundColor Yellow
$aliasPathLM = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Execution Aliases'
if (Test-Path $aliasPathLM) {
    foreach ($name in @('python.exe', 'python3.exe')) {
        $full = "$aliasPathLM\$name"
        if (Test-Path $full) {
            try {
                Remove-Item -Path $full -Recurse -Force -ErrorAction Stop
                Write-Host "  - 已禁用 HKLM \$name" -ForegroundColor Green
            } catch {
                Write-Host "  - HKLM \$name 需要管理员权限跳过（HKCU 通常够用）" -ForegroundColor DarkYellow
            }
        }
    }
}

# ---- 3. 把真实 Python 加入当前用户的 PATH ----
Write-Host ""
Write-Host "[3/3] 把真实 Python 加入 PATH（当前用户）..." -ForegroundColor Yellow
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
$parts = $currentPath -split ";" | Where-Object { $_ -ne "" }
$add = @($pyDir, $scriptsDir) | Where-Object { $parts -notcontains $_ }
if ($add.Count -gt 0) {
    $newPath = ($parts + $add) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $newPath
    Write-Host "  - 已追加: $($add -join ', ')" -ForegroundColor Green
} else {
    Write-Host "  - PATH 已包含，无需重复添加" -ForegroundColor DarkGray
}

# ---- 4. 验证 ----
Write-Host ""
Write-Host "==== 验证（请关闭并重开 PowerShell 窗口后再跑命令） ====" -ForegroundColor Cyan
Write-Host ""
& $py --version
Write-Host "完整路径: $py" -ForegroundColor Gray
Write-Host ""
Write-Host "修复完成！请：" -ForegroundColor Green
Write-Host "  1) 关闭当前 PowerShell 窗口"
Write-Host "  2) 重新打开 PowerShell"
Write-Host "  3) 运行: python --version     （应当显示真实 Python 版本）"
Write-Host "  4) 再运行: .\start_backend.ps1 （启动后端）"
Write-Host ""
Write-Host "若仍被劫持，请右键 PowerShell → 以管理员身份运行，再跑一次此脚本。" -ForegroundColor Yellow
pause