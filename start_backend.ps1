# start_backend.ps1 —— 一键启动后端服务（Windows PowerShell）
# 自动检测已安装的 Python 3.x，无需手动配置

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# ---- 自动找 Python（仅信任真实路径，绝不 fallback 到 Microsoft Store 占位）----
$py = $null
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe"
)
foreach ($c in $candidates) {
    if (Test-Path $c) { $py = $c; break }
}
if (-not $py) {
    Write-Host "❌ 未找到 Python（已跳过 Microsoft Store 占位），请先运行 .\setup_env.ps1 安装"
    Write-Host "   或先运行 .\fix_python.ps1 修复 PATH 别名劫持问题"
    exit 1
}
Write-Host "使用 Python: $py"

# ---- 安装依赖（首次）----
Write-Host ""
Write-Host "[1/3] 安装/更新依赖 ..."
& $py -m pip install --upgrade pip --quiet --disable-pip-version-check
& $py -m pip install -r requirements.txt --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 依赖安装失败，请检查网络"
    exit 1
}

# ---- 检查 config.py ----
if (-not (Test-Path "backend\config.py")) {
    Write-Host ""
    Write-Host "⚠ 首次使用：自动创建 backend\config.py"
    Copy-Item "backend\config.example.py" "backend\config.py"
    Write-Host "  请用记事本/编辑器打开它，把 DEEPSEEK_API_KEY 改为你的真实 Key 后重新运行。"
    Write-Host ""
    notepad "backend\config.py"
}

# ---- 启动服务 ----
Write-Host ""
Write-Host "[2/3] 启动 FastAPI 服务 ..."
Write-Host "  后端API:    http://localhost:8000"
Write-Host "  接口文档:   http://localhost:8000/docs"
Write-Host "  静态前端:   http://localhost:8000/web/"
Write-Host ""
Write-Host "[3/3] 启动完成！按 Ctrl+C 停止"
Write-Host ""

Set-Location backend
& $py main.py