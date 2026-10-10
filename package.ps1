# package.ps1 —— 把项目打包成可分享的 zip
# 用法：在项目根目录 powershell 里跑  .\package.ps1
# 产物：项目上级目录\DeepSeek-AnswerMark-pack\DeepSeek-AnswerMark.zip

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$staging = Join-Path (Split-Path $root -Parent) "DeepSeek-AnswerMark-pack"
$zipPath = Join-Path $staging "DeepSeek-AnswerMark.zip"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  毕设项目打包（去除敏感数据后分享给同学）" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# 1. 准备暂存目录
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null
$stage = Join-Path $staging "DeepSeek-AnswerMark"
New-Item -ItemType Directory -Path $stage | Out-Null

# 2. 用 robocopy 复制（排除大文件/敏感文件）
Write-Host ""
Write-Host "[1/5] 复制项目文件..." -ForegroundColor Yellow
$xdList = @('data\uploads','data\cache','data\logs','data\results','__pycache__','packaging')
$xdQuoted = ($xdList | ForEach-Object { '"' + $_ + '"' }) -join ' '
cmd /c ("robocopy `"$root`" `"$stage`" /MIR /NJH /NJS /NDL /NFL /NP /XD " + $xdQuoted + ' /XF "*.pyc" "*.log" "*.tmp"') | Out-Null

# 3. 清理 data 目录残留（如果原本无子目录，仅有占位文件）
foreach ($sub in @('uploads','cache','logs','results')) {
    $p = Join-Path $stage "backend\data\$sub"
    if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
}
# 删 DB（学情数据由用户自己跑出来，不打包）
$dbFile = Join-Path $stage "backend\data\answer_mark.db"
if (Test-Path $dbFile) { Remove-Item $dbFile -Force }

# 4. 替换 API Key 为占位符
Write-Host "[2/5] 脱敏 API Key..." -ForegroundColor Yellow
$cfg = Join-Path $stage "backend\config.py"
if (Test-Path $cfg) {
    $c = Get-Content $cfg -Raw -Encoding UTF8
    $c = [regex]::Replace($c, '(DEEPSEEK_API_KEY\s*=\s*os\.getenv\([^,]+,\s*")[^"]+(")',
                           '$1sk-请填入你的真实Key$2')
    [System.IO.File]::WriteAllText($cfg, $c, [System.Text.UTF8Encoding]::new($false))
}

# 5. 写一份给接收方的 README
Write-Host "[3/5] 生成说明文档..." -ForegroundColor Yellow
$readme = @"
# DeepSeek-Vision 答卷智能判题系统（分享版）

## 包含什么
- backend/      Python 后端（FastAPI + DeepSeek-Vision）
- frontend/     前端页面（HTML + JS + ECharts）
- requirements.txt
- start_backend.ps1 / start_frontend.ps1 / setup_env.ps1

## 不包含什么（已清理）
- backend/data/uploads/   上传的答卷原图（含个人信息）
- backend/data/cache/      API 响应缓存
- backend/data/results/   历史判题 JSON
- backend/data/logs/      运行日志
- backend/data/answer_mark.db  学情分析数据库（首次运行自动重建）
- 真实 API Key  ← 已替换为占位符 **请填入**

## 接收方使用步骤
1. 安装 Python 3.10+（python.org 下载）
2. 解压本 zip
3. 编辑 backend/config.py，把 DEEPSEEK_API_KEY 改为你的真实 Key
4. 双击 setup_env.ps1 安装依赖
5. 双击 start_backend.ps1 启动后端
6. 浏览器打开 http://localhost:8000/web/

## 常见问题
- python 命令找不到 → 见 fix_python.ps1
- /web/ 404 → 后端启动时会自动挂载前端目录
- 端口被占用 → 编辑 backend/config.py 改 PORT = 8000
"@
[System.IO.File]::WriteAllText((Join-Path $stage "📖使用说明.txt"), $readme, [System.Text.UTF8Encoding]::new($false))

# 6. 打包成 zip
Write-Host "[4/5] 压缩为 zip..." -ForegroundColor Yellow
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Add-Type -AssemblyName "System.IO.Compression.FileSystem"
[System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $zipPath)

$sizeMB = (Get-Item $zipPath).Length / 1024 / 1024
Write-Host ""
Write-Host "[5/5] 完成 ✓" -ForegroundColor Green
Write-Host ("  zip 路径：{0}" -f $zipPath)
Write-Host ("  大小：{0:N2} MB" -f $sizeMB)
Write-Host ""
if ($sizeMB -gt 100) {
    Write-Host "⚠ 超过 100 MB，手机微信发送会被拒。考虑：取消注释排除某些目录，或用 PC 微信发。" -ForegroundColor Yellow
} else {
    Write-Host "✓ 小于 100 MB，手机微信/文件传输助手都能发" -ForegroundColor Green
}
Write-Host ""
Write-Host "下一步：" -ForegroundColor Cyan
Write-Host "  1. 打开微信 → 文件传输助手（或发给好友）"
Write-Host "  2. 发送这个 zip：$zipPath"
Write-Host "  3. 接收方解压后，按 📖使用说明.txt 操作"