$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$BackendLog = Join-Path $Root "backend-watch.log"
$FrontendLog = Join-Path $Root "frontend-watch.log"

function Test-Port {
    param([int]$Port)
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(500)
        if ($ok) { $client.EndConnect($async) }
        $client.Close()
        return $ok
    } catch {
        return $false
    }
}

function Start-Backend {
    Add-Content $BackendLog "$(Get-Date -Format s) starting backend"
    $cmd = "cd /d `"$BackendDir`" && set PYTHONPATH=. && set PYTHONIOENCODING=utf-8 && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> `"$BackendLog`" 2>&1"
    return Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd -WindowStyle Hidden -PassThru
}

function Start-Frontend {
    Add-Content $FrontendLog "$(Get-Date -Format s) starting frontend"
    $cmd = "cd /d `"$FrontendDir`" && npm run dev -- --host 0.0.0.0 --port 5205 >> `"$FrontendLog`" 2>&1"
    return Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd -WindowStyle Hidden -PassThru
}

$backend = $null
$frontend = $null

while ($true) {
    if (-not (Test-Port 8000)) {
        if ($backend -and -not $backend.HasExited) {
            Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
        }
        $backend = Start-Backend
        Start-Sleep -Seconds 3
    }

    if (-not (Test-Port 5205)) {
        if ($frontend -and -not $frontend.HasExited) {
            Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
        }
        $frontend = Start-Frontend
        Start-Sleep -Seconds 3
    }

    Start-Sleep -Seconds 5
}
