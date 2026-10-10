# start_frontend.ps1 —— 启动前端静态服务（仅当你想让前端独立运行时使用）
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root\frontend
Write-Host "前端服务运行中: http://localhost:5500"
Write-Host "（确保后端也已运行: http://localhost:8000）"
Write-Host ""
$py = $null
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
)
foreach ($c in $candidates) { if (Test-Path $c) { $py = $c; break } }
if (-not $py) {
    Write-Host "❌ 未找到真实 Python。请运行 .\fix_python.ps1 修复。"
    pause; exit 1
}
& $py -m http.server 5500