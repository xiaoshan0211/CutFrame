$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$state = Join-Path (Split-Path $project -Parent) 'local\cutframe'
if ($env:CUTFRAME_STATE) { $state = $env:CUTFRAME_STATE }
$mutex = New-Object System.Threading.Mutex($false, 'Local\CutFrameStudioWatchdog4380')
if (!$mutex.WaitOne(0)) { exit 0 }
try {
    $logs = Join-Path $state 'server-logs'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    while ($true) {
        try {
            if (!(Test-Path -LiteralPath (Join-Path $state 'service-paused'))) {
                $config = Get-Content -LiteralPath (Join-Path $state 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
                $listener = Get-NetTCPConnection -LocalPort $config.port -State Listen -ErrorAction SilentlyContinue
                # 有监听或已有本应用进程时不重复启动，也不因繁忙请求超时杀进程。
                $appPath = Join-Path $project 'app.py'
                $existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($appPath) }
                if (!$listener -and !$existing) {
                    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
                    $child = Start-Process -FilePath $config.python -ArgumentList @('-X','utf8',('"' + $appPath + '"')) -WorkingDirectory $project -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs ($stamp+'-stdout.log')) -RedirectStandardError (Join-Path $logs ($stamp+'-stderr.log'))
                    $child.Id | Set-Content -LiteralPath (Join-Path $state 'server.pid')
                    Add-Content -LiteralPath (Join-Path $logs 'watchdog.log') -Value ("$(Get-Date -Format o) 启动服务 PID=$($child.Id)")
                    Start-Sleep -Seconds 10
                }
            }
        } catch {
            Add-Content -LiteralPath (Join-Path $logs 'watchdog.log') -Value ("$(Get-Date -Format o) 守护检查失败：$($_.Exception.Message)")
            Start-Sleep -Seconds 20
        }
        Start-Sleep -Seconds 5
    }
} finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
