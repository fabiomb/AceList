<#
.SYNOPSIS
    Prepara AceList y lo abre en el navegador.

.DESCRIPTION
    La primera vez crea el entorno virtual (.venv) e instala la aplicación; después
    solo reinstala si cambió pyproject.toml. Aplica las migraciones de la base de datos,
    arranca el servidor en 127.0.0.1 y abre el navegador cuando responde.
    Ctrl+C detiene el servidor.

.PARAMETER Port
    Puerto local del servidor (por defecto 8000).

.PARAMETER NoBrowser
    No abrir el navegador.

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Port 8080 -NoBrowser
#>
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$installMarker = Join-Path $PSScriptRoot '.venv\acelist-installed.txt'
$url = "http://127.0.0.1:$Port/"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-AceList {
    try {
        $response = Invoke-WebRequest -Uri "${url}health" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Find-Python {
    # The "py" launcher first (it picks the newest Python), then python on PATH.
    $candidates = @(@('py', '-3'), @('python'))
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $prefix = @($candidate | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        & $exe @prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { return , $candidate }
    }
    return $null
}

if (Test-AceList) {
    Write-Step "AceList ya está funcionando en $url"
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $python = Find-Python
    if ($null -eq $python) {
        Write-Error 'Hace falta Python 3.11 o superior: https://www.python.org/downloads/'
    }
    Write-Step 'Creando el entorno virtual (.venv)'
    $exe = $python[0]
    $prefix = @($python | Select-Object -Skip 1)
    & $exe @prefix -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Error 'No se pudo crear el entorno virtual.' }
}

# Reinstall only when the dependencies changed.
$wanted = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'pyproject.toml')).Hash
$installed = ''
if (Test-Path -LiteralPath $installMarker) { $installed = (Get-Content -LiteralPath $installMarker -Raw).Trim() }
if ($installed -ne $wanted) {
    Write-Step 'Instalando AceList y sus dependencias'
    & $venvPython -m pip install --disable-pip-version-check --quiet --editable .
    if ($LASTEXITCODE -ne 0) { Write-Error 'Falló la instalación de dependencias.' }
    Set-Content -LiteralPath $installMarker -Value $wanted -Encoding ascii
}

Write-Step 'Actualizando la base de datos'
& $venvPython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Error 'Fallaron las migraciones de la base de datos.' }

if (-not $NoBrowser) {
    # Opens the browser once the server answers, while it runs in the foreground.
    Start-Job -ArgumentList $url -ScriptBlock {
        param($url)
        for ($i = 0; $i -lt 60; $i++) {
            try {
                Invoke-WebRequest -Uri "${url}health" -UseBasicParsing -TimeoutSec 2 | Out-Null
                Start-Process $url
                return
            } catch {
                Start-Sleep -Milliseconds 500
            }
        }
    } | Out-Null
}

Write-Step "Abriendo AceList en $url (Ctrl+C para detener)"
$env:ACELIST_PORT = "$Port"
& $venvPython -m app.main
