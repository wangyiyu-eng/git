# start_gradio.ps1 —— 一键启动 Gradio 版（不开窗口浏览器）
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py = $null
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
)
foreach ($c in $candidates) { if (Test-Path $c) { $py = $c; break } }
if (-not $py) { try { $py = (Get-Command python.exe -ErrorAction Stop).Source } catch {} }
if (-not $py) { Write-Host "❌ 未找到 Python"; exit 1 }

& $py -m pip install -r requirements.txt --quiet --disable-pip-version-check

if (-not (Test-Path "backend\config.py")) {
    Copy-Item "backend\config.example.py" "backend\config.py"
    notepad "backend\config.py"
}

Set-Location backend
& $py app_gradio.py