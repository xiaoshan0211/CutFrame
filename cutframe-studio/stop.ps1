$ErrorActionPreference = 'Stop'
$state = Join-Path (Split-Path $PSScriptRoot -Parent) 'local\cutframe'
if ($env:CUTFRAME_STATE) { $state = $env:CUTFRAME_STATE }
$pidFile = Join-Path $state 'server.pid'
if (!(Test-Path -LiteralPath $pidFile)) { Write-Host '没有本工具的启动记录。'; exit }
$serverPid = [int](Get-Content -LiteralPath $pidFile)
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid"
if (!$process) { Write-Host '服务已停止。'; exit }
$expected = Join-Path $PSScriptRoot 'app.py'
if (!$process.CommandLine.Contains($expected)) { throw '进程标识已被其他程序使用，未停止任何进程。' }
$config = Get-Content -LiteralPath (Join-Path $state 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
try {
    $stateInfo = Invoke-RestMethod ('http://127.0.0.1:' + $config.port + '/api/state')
    if (@($stateInfo.jobs | Where-Object { $_.status -in @('queued','running') }).Count -gt 0) {
        throw '还有处理任务，请先在网页取消任务或等待完成，再停止服务。'
    }
} catch { if ($_.Exception.Message -like '*还有处理任务*') { throw } }
Set-Content -LiteralPath (Join-Path $state 'service-paused') -Value '用户主动关闭；再次运行启动工作台即可恢复'
Stop-Process -Id $serverPid
Write-Host '本地工作台已关闭。'
