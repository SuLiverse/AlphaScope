# 研策中枢 AlphaScope 创建桌面快捷方式
# 用法: powershell -ExecutionPolicy Bypass -File scripts/create_shortcut.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "研策中枢 AlphaScope 创建桌面快捷方式" -ForegroundColor Cyan
Write-Host "=============================`n"

# 获取桌面路径
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "研策中枢 AlphaScope.lnk"

# 创建 WScript.Shell 对象
$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($shortcutPath)

# 设置快捷方式属性
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\start_local.ps1`""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.Description = "研策中枢 AlphaScope 本地金融分析工作台"

# 使用项目 logo（如果存在）
$iconPath = Join-Path $ProjectRoot "assets\logo.ico"
if (Test-Path $iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
} else {
    $shortcut.IconLocation = "powershell.exe,0"
}

# 保存
$shortcut.Save()

Write-Host "[OK] 桌面快捷方式已创建" -ForegroundColor Green
Write-Host "位置: $shortcutPath" -ForegroundColor Gray
Write-Host "`n双击桌面 '研策中枢 AlphaScope' 图标即可启动" -ForegroundColor Cyan
