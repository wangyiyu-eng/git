$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 使用系统已安装的 Python
$py = 'C:\Users\kz\AppData\Local\Programs\Python\Python312\python.exe'

Write-Host "============================================"
Write-Host " 安装依赖 (pip install -r requirements.txt)"
Write-Host "============================================"
Write-Host ""
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt --quiet

if ($LASTEXITCODE -ne 0) {
    Write-Host "安装失败，尝试详细模式..."
    & $py -m pip install -r requirements.txt
}

# 从示例复制 config.py
if (-not (Test-Path "backend\config.py")) {
    Copy-Item "backend\config.example.py" "backend\config.py"
    Write-Host "已生成 backend/config.py，请填入真实 DEEPSEEK_API_KEY。"
}

Write-Host ""
Write-Host "DONE: 依赖安装完成"