# 研策中枢 AlphaScope 停止本地服务
$ErrorActionPreference = "SilentlyContinue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PidsFile = Join-Path $ProjectRoot ".local_pids.json"

Write-Host "研策中枢 AlphaScope 停止服务" -ForegroundColor Cyan
Write-Host "==================`n"

function Stop-ProcessTree($RootProcessId) {
    $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $RootProcessId }
    foreach ($child in $children) {
        Stop-ProcessTree $child.ProcessId
    }

    $proc = Get-Process -Id $RootProcessId -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $RootProcessId -Force -ErrorAction SilentlyContinue
        return $true
    }
    return $false
}

function Stop-PortProcess($Port) {
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -and $_.OwningProcess -ne 0 }
    $processIds = @($connections | Select-Object -ExpandProperty OwningProcess -Unique)

    foreach ($processId in $processIds) {
        $procName = (Get-Process -Id $processId -ErrorAction SilentlyContinue).ProcessName
        if (Stop-ProcessTree $processId) {
            Write-Host "  停止端口 $Port 进程 ($procName, PID: $processId)" -ForegroundColor Gray
        }
    }
}

$stopped = 0

if (Test-Path $PidsFile) {
    $pids = Get-Content $PidsFile | ConvertFrom-Json
    foreach ($prop in $pids.PSObject.Properties) {
        $name = $prop.Name
        $processId = $prop.Value
        if (Stop-ProcessTree $processId) {
            Write-Host "  停止 $name 进程树 (PID: $processId)" -ForegroundColor Gray
            $stopped++
        } else {
            Write-Host "  $name (PID: $processId) 已不在运行" -ForegroundColor DarkGray
        }
    }
    Remove-Item $PidsFile -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "未找到 .local_pids.json，服务可能未通过 start_local 启动。" -ForegroundColor Yellow
}

Write-Host "尝试清理端口进程..." -ForegroundColor Gray
foreach ($port in @(3000, 8000, 8501)) {
    Stop-PortProcess $port
}

Write-Host "尝试清理残留 Vite 前端进程..." -ForegroundColor Gray
$webPath = Join-Path $ProjectRoot "apps\web"
$viteProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($webPath) -and (
        $_.CommandLine.Contains("vite") -or $_.CommandLine.Contains("npm")
    )
}
foreach ($viteProcess in $viteProcesses) {
    if (Stop-ProcessTree $viteProcess.ProcessId) {
        Write-Host "  停止 Vite 残留进程 (PID: $($viteProcess.ProcessId))" -ForegroundColor Gray
    }
}

Write-Host "`n已停止 $stopped 个服务入口。" -ForegroundColor Green
