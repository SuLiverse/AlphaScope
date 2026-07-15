# 研策中枢 AlphaScope 依赖安装脚本
# 用法: powershell -ExecutionPolicy Bypass -File scripts/install_deps.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "研策中枢 AlphaScope 依赖安装" -ForegroundColor Cyan
Write-Host "====================`n"

# 1. 检查 Python
Write-Host "检查 Python..." -ForegroundColor Yellow
$pythonVer = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Python 未安装" -ForegroundColor Red
    Write-Host "请访问 https://www.python.org/downloads/ 安装 Python 3.11 或 3.12" -ForegroundColor Yellow
    exit 1
}
python -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] 当前 Python 版本不受支持: $pythonVer" -ForegroundColor Red
    Write-Host "请安装 Python 3.11 或 3.12" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] $pythonVer" -ForegroundColor Green

# 2. 检查 Node.js
Write-Host "`n检查 Node.js..." -ForegroundColor Yellow
$nodeVer = node --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Node.js 未安装" -ForegroundColor Red
    Write-Host "请访问 https://nodejs.org/ 安装 Node.js 18+" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Node.js $nodeVer" -ForegroundColor Green

# 3. 安装 Python 依赖
Write-Host "`n安装 Python 依赖..." -ForegroundColor Yellow
Set-Location $ProjectRoot
python -m pip install -e ".[api]"
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Python 依赖已安装" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Python 依赖安装失败" -ForegroundColor Red
    exit 1
}

# 4. 安装前端依赖
Write-Host "`n安装前端依赖..." -ForegroundColor Yellow
$webDir = Join-Path $ProjectRoot "apps\web"
Set-Location $webDir
npm install
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] 前端依赖已安装" -ForegroundColor Green
} else {
    Write-Host "[FAIL] 前端依赖安装失败" -ForegroundColor Red
    exit 1
}

# 5. 初始化 .env
Write-Host "`n检查配置文件..." -ForegroundColor Yellow
$envFile = Join-Path $ProjectRoot ".env"
$envExample = Join-Path $ProjectRoot ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Host "[OK] 已创建 .env 配置文件" -ForegroundColor Green
        Write-Host "请编辑 .env 文件填入你的 API Key" -ForegroundColor Yellow
    } else {
        Write-Host "[WARN] 未找到 .env.example 模板" -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] .env 已存在" -ForegroundColor Green
}

# 6. 创建数据目录
Write-Host "`n创建数据目录..." -ForegroundColor Yellow
$dirs = @("data", "data/db", "data/cache", "data/reports", "data/uploads", "data/logs")
foreach ($d in $dirs) {
    $path = Join-Path $ProjectRoot $d
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        Write-Host "  创建: $d" -ForegroundColor Gray
    }
}
Write-Host "[OK] 数据目录已就绪" -ForegroundColor Green

Write-Host "`n安装完成！" -ForegroundColor Green
Write-Host "运行 start_local.bat 启动服务" -ForegroundColor Cyan
