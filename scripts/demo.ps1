[CmdletBinding()]
param(
    [switch]$ExitAfterReady,
    [switch]$SkipPrepare,
    [ValidateRange(0, 3600)]
    [int]$ServeForSeconds = 0
)

$ErrorActionPreference = 'Stop'
$backendRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$mobileRoot = (Resolve-Path -LiteralPath (Join-Path $backendRoot '..\wajz-mobile')).Path
$python = Join-Path $backendRoot '.venv\Scripts\python.exe'
$database = Join-Path $backendRoot 'wajz.db'
$backupRoot = Join-Path $backendRoot '.demo-backups'
$webRoot = Join-Path $mobileRoot 'build\web'
$apiLog = Join-Path $backendRoot '.demo-api.log'
$apiErrorLog = Join-Path $backendRoot '.demo-api-error.log'
$webLog = Join-Path $backendRoot '.demo-web.log'
$webErrorLog = Join-Path $backendRoot '.demo-web-error.log'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Backend environment not found at $python. Create .venv and install the project first."
}

foreach ($port in 8000, 3000) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($listener) {
        throw "Port $port is already in use. The demo command will not stop another process."
    }
}

$env:ENVIRONMENT = 'development'
$env:DATABASE_URL = 'sqlite:///./wajz.db'
$env:AUTH_MODE = 'dev'
$env:AI_PROVIDER = 'heuristic'
$env:CORS_ORIGINS = 'http://127.0.0.1:3000,http://localhost:3000'

if (-not $SkipPrepare) {
    $expectedDatabase = [System.IO.Path]::GetFullPath((Join-Path $backendRoot 'wajz.db'))
    if ([System.IO.Path]::GetFullPath($database) -ne $expectedDatabase) {
        throw 'Refusing to reset an unexpected database path.'
    }

    if (Test-Path -LiteralPath $database) {
        $databaseItem = Get-Item -LiteralPath $database -Force
        if ($databaseItem.PSIsContainer -or
            ($databaseItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Refusing to reset a directory or reparse point.'
        }
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backup = Join-Path $backupRoot "wajz-$stamp.db"
        Copy-Item -LiteralPath $database -Destination $backup -ErrorAction Stop
        Remove-Item -LiteralPath $database -ErrorAction Stop
        Write-Host "Database backup: $backup"
    }

    Push-Location $backendRoot
    try {
        & $python -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
        & $python -m app.seeds all
        if ($LASTEXITCODE -ne 0) { throw 'Demo seeding failed.' }
    } finally {
        Pop-Location
    }

    Push-Location $mobileRoot
    try {
        & flutter build web --release `
            --dart-define=WAJZ_API_BASE=http://127.0.0.1:8000 `
            --dart-define=WAJZ_ENABLE_DEV_LOGIN=true
        if ($LASTEXITCODE -ne 0) { throw 'Consumer web build failed.' }
    } finally {
        Pop-Location
    }
} elseif (-not (Test-Path -LiteralPath $database -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $webRoot 'index.html') -PathType Leaf)) {
    throw 'Prepared demo database and consumer build are required with -SkipPrepare.'
}

$api = $null
$web = $null
try {
    $api = Start-Process -FilePath $python -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' `
        -RedirectStandardOutput $apiLog -RedirectStandardError $apiErrorLog
    $web = Start-Process -FilePath $python -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
        -ArgumentList 'scripts\serve_spa.py', '--root', $webRoot, '--host', '127.0.0.1', '--port', '3000' `
        -RedirectStandardOutput $webLog -RedirectStandardError $webErrorLog

    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/ready' -TimeoutSec 1
            if ($response.status -eq 'ready') { $ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "API readiness failed. See $apiErrorLog" }

    Write-Host 'Wajz demo is ready:'
    Write-Host '  Consumer: http://127.0.0.1:3000'
    Write-Host '  API:      http://127.0.0.1:8000/docs'
    if ($ExitAfterReady) { return }
    if ($ServeForSeconds -gt 0) {
        $deadline = (Get-Date).AddSeconds($ServeForSeconds)
        while ((Get-Date) -lt $deadline -and -not $api.HasExited -and -not $web.HasExited) {
            Start-Sleep -Seconds 1
        }
        if ($api.HasExited -or $web.HasExited) {
            throw 'A demo process exited unexpectedly.'
        }
        return
    }
    Write-Host 'Press Ctrl+C to stop this demo.'
    while (-not $api.HasExited -and -not $web.HasExited) {
        Start-Sleep -Seconds 1
    }
    throw 'A demo process exited unexpectedly.'
} finally {
    foreach ($process in @($web, $api)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -ErrorAction Stop
            $process.WaitForExit()
        }
    }
    Write-Host 'Wajz demo stopped.'
}
