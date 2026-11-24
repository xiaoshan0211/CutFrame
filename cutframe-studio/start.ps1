$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$state = Join-Path (Split-Path $project -Parent) 'local\cutframe'
if ($env:CUTFRAME_STATE) { $state = $env:CUTFRAME_STATE }
Remove-Item -LiteralPath (Join-Path $state 'service-paused') -ErrorAction SilentlyContinue
$config = Get-Content -LiteralPath (Join-Path $state 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$url = 'http://127.0.0.1:' + $config.port
try {
    $ready = Invoke-RestMethod -Uri ($url + '/api/state') -TimeoutSec 2
    if ($ready.application -eq 'cutframe-studio') { Start-Process $url; exit 0 }
} catch {}
if (!(Test-Path -LiteralPath $config.python)) { throw '找不到已配置的 Python，请检查 local\cutframe\config.json。' }
$logs = Join-Path $state 'server-logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$process = Start-Process -FilePath $config.python -ArgumentList @('-X', 'utf8', ('"' + (Join-Path $project 'app.py') + '"')) -WorkingDirectory $project -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log')
$process.Id | Set-Content -LiteralPath (Join-Path $state 'server.pid')
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $ready = Invoke-RestMethod -Uri ($url + '/api/state') -TimeoutSec 2
        if ($ready.application -eq 'cutframe-studio') { Start-Process $url; exit 0 }
    } catch {}
    if ($process.HasExited) { throw ('启动失败，请查看 ' + $logs) }
}
throw ('启动超时，请查看 ' + $logs)
