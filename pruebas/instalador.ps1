# Pruebas de install.ps1 en una carpeta de usuario temporal. Corre en Windows PowerShell 5.1 y en PowerShell 7.
# Nunca toca la carpeta real del usuario: USERPROFILE apunta a una carpeta nueva durante la prueba.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$raiz = Split-Path -Parent $PSScriptRoot
$instalador = Join-Path $raiz 'install.ps1'
$origen = Join-Path $raiz 'skills\rendimiento-equipo'
$exe = 'powershell'
if ($PSVersionTable.PSEdition -eq 'Core') { $exe = 'pwsh' }
Write-Host "Probando con $exe $($PSVersionTable.PSVersion)"

$casa = Join-Path ([System.IO.Path]::GetTempPath()) ('casa-prueba-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $casa | Out-Null
$env:USERPROFILE = $casa
$env:HOME = $casa
Remove-Item Env:\CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue
$claude = Join-Path $casa '.claude\skills\rendimiento-equipo'
$agentes = Join-Path $casa '.agents\skills\rendimiento-equipo'

function Correr([string[]]$argumentos) {
    # Local: en Windows PowerShell 5.1 lo que el instalador escribe en stderr se volveria error con 'Stop'.
    $ErrorActionPreference = 'Continue'
    $todos = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $instalador) + $argumentos
    $salida = & $exe @todos 2>&1 | Out-String
    Write-Host $salida
    return $LASTEXITCODE
}

function Exigir([bool]$condicion, [string]$mensaje) {
    if (-not $condicion) { throw "FALLA: $mensaje" }
    Write-Host "OK  $mensaje"
}

function Apunta([string]$ruta) {
    $e = Get-Item -LiteralPath $ruta -Force -ErrorAction SilentlyContinue
    if ($null -eq $e -or -not $e.LinkType) { return $null }
    $t = [string](@($e.Target)[0])
    return $t.Replace('\??\', '').TrimEnd('\')
}

$rc = Correr @('-Prueba')
Exigir ($rc -eq 0) "-Prueba sale con 0 (salio $rc)"
Exigir (-not (Test-Path -LiteralPath $claude)) '-Prueba no crea nada'

$rc = Correr @('-Destino', 'otro')
Exigir ($rc -eq 2) "-Destino otro sale con 2 (salio $rc)"

$rc = Correr @('-Opcion')
Exigir ($rc -eq 2) "una opcion desconocida sale con 2 (salio $rc)"

# Algo que ya existia en el destino de Codex: debe ir a .respaldos, no borrarse
New-Item -ItemType Directory -Force -Path $agentes | Out-Null
Set-Content -LiteralPath (Join-Path $agentes 'mio.txt') -Value 'no me borres'

$rc = Correr @()
Exigir ($rc -eq 0) "instalar sale con 0 (salio $rc)"
Exigir ((Apunta $claude) -ieq $origen) "Claude Code queda enlazado al repositorio"
Exigir ((Apunta $agentes) -ieq $origen) "Codex queda enlazado al repositorio"
Exigir (Test-Path -LiteralPath (Join-Path $claude 'SKILL.md')) 'SKILL.md se ve a traves del enlace'
$respaldo = @(Get-ChildItem -LiteralPath (Join-Path $raiz '.respaldos') -Directory -Filter 'agentes-*' -ErrorAction SilentlyContinue)
Exigir ($respaldo.Count -ge 1 -and (Test-Path -LiteralPath (Join-Path $respaldo[-1].FullName 'mio.txt'))) 'lo que ya existia quedo en .respaldos'

$rc = Correr @()
Exigir ($rc -eq 0) "reinstalar sale con 0 (salio $rc)"

$rc = Correr @('-Desinstalar')
Exigir ($rc -eq 0) "desinstalar sale con 0 (salio $rc)"
Exigir (-not (Test-Path -LiteralPath $claude)) 'el enlace de Claude Code se quito'
Exigir (-not (Test-Path -LiteralPath $agentes)) 'el enlace de Codex se quito'
Exigir (Test-Path -LiteralPath (Join-Path $origen 'SKILL.md')) 'el repositorio sigue intacto'

Remove-Item -LiteralPath (Join-Path $raiz '.respaldos') -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $casa -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'Todas las pruebas del instalador pasaron.'
exit 0
