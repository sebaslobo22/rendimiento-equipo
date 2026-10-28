<#
.SYNOPSIS
Enlaza la skill rendimiento-equipo en las carpetas que leen los agentes (version Windows de install.sh).

.DESCRIPTION
Crea enlaces de carpeta (junctions) hacia skills\rendimiento-equipo en:
  Claude Code  %CLAUDE_CONFIG_DIR% (o %USERPROFILE%\.claude), subcarpeta skills\rendimiento-equipo
  Codex        %USERPROFILE%\.agents\skills\rendimiento-equipo

No copia archivos, no instala dependencias y no usa la red. Los junctions no piden
permisos de administrador ni Modo de desarrollador.

Si ya existe algo con ese nombre y no es un enlace a este repositorio, se mueve a
<repositorio>\.respaldos\<destino>-<fecha> antes de enlazar. Nada se borra.
Si el enlace ya apunta a este repositorio, no hace nada (se puede correr varias veces).
Con -Desinstalar solo se quita el enlace, nunca el contenido de la carpeta a la que apunta.

Funciona en Windows PowerShell 5.1 y en PowerShell 7. Codigos de salida:
  0  todo bien
  1  falta skills\rendimiento-equipo\SKILL.md (correlo desde el repositorio) o fallo inesperado
  2  argumentos invalidos

Si Windows bloquea el script por la politica de ejecucion ("la ejecucion de scripts esta
deshabilitada en este sistema"), corre en su lugar, desde la carpeta del repositorio:
  powershell -ExecutionPolicy Bypass -File .\install.ps1
(el permiso vale solo para ese comando y no cambia la configuracion del equipo).

.PARAMETER Destino
ambos (por defecto), claude o agentes: donde enlazar.

.PARAMETER Prueba
Muestra lo que haria, sin cambiar nada.

.PARAMETER Desinstalar
Quita los enlaces que apuntan a este repositorio.

.PARAMETER Ayuda
Muestra la ayuda corta y termina.

.EXAMPLE
PS> .\install.ps1
Enlaza en Claude Code y en Codex.

.EXAMPLE
PS> .\install.ps1 -Prueba
Muestra lo que haria, sin cambiar nada.

.EXAMPLE
PS> .\install.ps1 -Destino claude
Enlaza solo en Claude Code.

.EXAMPLE
PS> .\install.ps1 -Desinstalar
Quita los enlaces que apuntan a este repositorio.

.EXAMPLE
PS> powershell -ExecutionPolicy Bypass -File .\install.ps1
Igual que el primero, para equipos donde la politica de ejecucion bloquea scripts.
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Destino = 'ambos',
    [switch]$Prueba,
    [switch]$Desinstalar,
    [switch]$Ayuda,
    # Recoge todo lo que no es un parametro conocido, para poder salir con codigo 2
    # (PowerShell por si solo sale con 1 cuando un parametro no existe).
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Resto
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$NOMBRE = 'rendimiento-equipo'
$EsWindows = ([System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT)
# En Windows se usan junctions (no piden administrador). El respaldo en otros sistemas
# (solo para probar el script con pwsh fuera de Windows) usa enlaces simbolicos.
$TipoEnlace = 'Junction'
if (-not $EsWindows) { $TipoEnlace = 'SymbolicLink' }

$CasaUsuario = $env:USERPROFILE
if ([string]::IsNullOrEmpty($CasaUsuario)) { $CasaUsuario = $HOME }

$RAIZ = $PSScriptRoot
if ([string]::IsNullOrEmpty($RAIZ)) { $RAIZ = (Get-Location).ProviderPath }
$RAIZ = [System.IO.Path]::GetFullPath($RAIZ)
$ORIGEN = [System.IO.Path]::Combine($RAIZ, 'skills', $NOMBRE)
$RESPALDOS = [System.IO.Path]::Combine($RAIZ, '.respaldos')

$ConfigClaude = $env:CLAUDE_CONFIG_DIR
if ([string]::IsNullOrEmpty($ConfigClaude)) { $ConfigClaude = [System.IO.Path]::Combine($CasaUsuario, '.claude') }
$DESTINO_CLAUDE = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($ConfigClaude, 'skills', $NOMBRE))
$DESTINO_AGENTES = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($CasaUsuario, '.agents', 'skills', $NOMBRE))

# ---------------------------------------------------------------- utilidades

function Write-Err([string]$mensaje) {
    $Host.UI.WriteErrorLine($mensaje)
}

function Show-Ayuda {
    Write-Host @"
Uso: .\install.ps1 [opciones]

Enlaza skills\$NOMBRE en:
  Claude Code  $DESTINO_CLAUDE
  Codex        $DESTINO_AGENTES

Opciones:
  -Destino ambos|claude|agentes   donde enlazar (por defecto: ambos)
  -Prueba                         muestra lo que haria, sin cambiar nada
  -Desinstalar                    quita los enlaces que apuntan a este repositorio
  -Ayuda                          muestra esta ayuda

Si ya existe algo con ese nombre y no es este repositorio, se mueve a
$RESPALDOS antes de enlazar. Nada se borra.

Si Windows bloquea el script (politica de ejecucion), corre:
  powershell -ExecutionPolicy Bypass -File .\install.ps1
"@
}

# Ejecuta el bloque, o solo lo muestra si se pidio -Prueba.
function Invoke-Accion([string]$texto, [scriptblock]$bloque) {
    if ($Prueba) {
        Write-Host "         (prueba) $texto"
    } else {
        & $bloque
    }
}

# Devuelve el elemento (carpeta, archivo o enlace, aunque este roto) o $null si no existe.
function Get-Elemento([string]$ruta) {
    try {
        return (Get-Item -LiteralPath $ruta -Force -ErrorAction Stop)
    } catch {
        return $null
    }
}

# Tipo de enlace ('Junction', 'SymbolicLink'...) o cadena vacia si no es un enlace.
function Get-TipoEnlace($elem) {
    if ($null -eq $elem) { return '' }
    $p = $elem.PSObject.Properties['LinkType']
    if ($null -eq $p) { return '' }
    $v = $p.Value
    if ($null -eq $v) { return '' }
    return [string]$v
}

function Test-EsEnlace($elem) {
    return ((Get-TipoEnlace $elem) -ne '')
}

# Quita prefijos de Windows (\??\ y \\?\), completa la ruta y quita la barra final.
function ConvertTo-RutaNormal([string]$ruta) {
    $r = $ruta
    foreach ($pre in @('\??\', '\\?\')) {
        if ($r.StartsWith($pre, [System.StringComparison]::Ordinal)) {
            $r = $r.Substring($pre.Length)
            break
        }
    }
    $r = [System.IO.Path]::GetFullPath($r)
    $raiz = [System.IO.Path]::GetPathRoot($r)
    if ($r.Length -gt $raiz.Length) { $r = $r.TrimEnd('\', '/') }
    return $r
}

# Compara dos rutas completas: sin distinguir mayusculas en Windows, distinguiendo en otros sistemas.
function Test-MismaRuta([string]$a, [string]$b) {
    $modo = [System.StringComparison]::Ordinal
    if ($EsWindows) { $modo = [System.StringComparison]::OrdinalIgnoreCase }
    return [string]::Equals((ConvertTo-RutaNormal $a), (ConvertTo-RutaNormal $b), $modo)
}

# A donde apunta el enlace (ruta completa), o $null si no es un enlace o no se puede leer.
function Get-DestinoEnlace([string]$ruta) {
    $elem = Get-Elemento $ruta
    if (-not (Test-EsEnlace $elem)) { return $null }
    $p = $elem.PSObject.Properties['Target']
    if ($null -eq $p -or $null -eq $p.Value) { return $null }
    $t = [string](@($p.Value)[0])
    if ([string]::IsNullOrEmpty($t)) { return $null }
    if (-not [System.IO.Path]::IsPathRooted($t)) {
        $base = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($ruta))
        $t = [System.IO.Path]::Combine($base, $t)
    }
    return (ConvertTo-RutaNormal $t)
}

# Verdadero si la ruta es un enlace cuyo destino es la carpeta de este repositorio
# (o es esa misma carpeta).
function Test-ApuntaAlOrigen([string]$ruta) {
    $elem = Get-Elemento $ruta
    if ($null -eq $elem) { return $false }
    $objetivo = Get-DestinoEnlace $ruta
    if ($null -ne $objetivo) { return (Test-MismaRuta $objetivo $ORIGEN) }
    return (Test-MismaRuta $ruta $ORIGEN)
}

# Quita SOLO el enlace, nunca el contenido de la carpeta a la que apunta.
# (Remove-Item sobre un junction puede entrar a la carpeta destino en PowerShell 5.1.)
function Remove-Enlace([string]$ruta) {
    if ($EsWindows) {
        [System.IO.Directory]::Delete($ruta, $false)
    } else {
        Remove-Item -LiteralPath $ruta -Force
    }
}

# Mueve lo que haya en $ruta a $resp sin borrar nada. Si es un enlace hacia otro lado,
# se recrea en el respaldo y recien despues se quita el original (Move-Item sobre un
# enlace puede copiar el contenido del destino).
function Move-ARespaldo([string]$ruta, [string]$resp) {
    $objetivo = Get-DestinoEnlace $ruta
    if ($null -ne $objetivo) {
        $creado = $false
        try {
            New-Item -ItemType $TipoEnlace -Path $resp -Value $objetivo | Out-Null
            $creado = $true
        } catch {
            $creado = $false
        }
        if ($creado) {
            Remove-Enlace $ruta
            return
        }
    }
    $elem = Get-Elemento $ruta
    if ((Test-EsEnlace $elem) -and $elem.PSIsContainer) {
        [System.IO.Directory]::Move($ruta, $resp)
    } else {
        Move-Item -LiteralPath $ruta -Destination $resp
    }
}

# Devuelve como llamar a Python 3 ('py -3', 'python3' o 'python') o $null si ninguno sirve.
# El atajo 'python' de Microsoft Store no cuenta: no imprime una version de Python 3.
function Get-ComandoPython {
    $candidatos = @(
        @{ Cmd = 'py';      Arg = @('-3', '--version'); Texto = 'py -3' },
        @{ Cmd = 'python3'; Arg = @('--version');       Texto = 'python3' },
        @{ Cmd = 'python';  Arg = @('--version');       Texto = 'python' }
    )
    foreach ($c in $candidatos) {
        if ($null -eq (Get-Command $c.Cmd -ErrorAction SilentlyContinue)) { continue }
        $cmd = $c.Cmd
        $argumentos = $c.Arg
        $ok = $false
        try {
            # Local a la funcion: en Windows PowerShell 5.1 el texto que un programa escribe
            # en stderr se vuelve error si la preferencia es 'Stop'.
            $ErrorActionPreference = 'Continue'
            $texto = (& $cmd @argumentos 2>&1 | Out-String)
            if (($LASTEXITCODE -eq 0) -and ($texto -match 'Python 3\.')) { $ok = $true }
        } catch {
            $ok = $false
        }
        if ($ok) { return $c.Texto }
    }
    return $null
}

function Install-Enlace([string]$etiqueta, [string]$dest) {
    if (Test-ApuntaAlOrigen $dest) {
        Write-Host "ok       $dest (ya apunta a este repositorio)"
        return
    }
    if ($null -ne (Get-Elemento $dest)) {
        $resp = [System.IO.Path]::Combine($RESPALDOS, ($etiqueta + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
        Write-Host "respalda $dest -> $resp"
        Invoke-Accion "mkdir $RESPALDOS" { New-Item -ItemType Directory -Force -Path $RESPALDOS | Out-Null }
        Invoke-Accion "mover $dest $resp" { Move-ARespaldo $dest $resp }
    }
    Write-Host "enlaza   $dest -> $ORIGEN"
    $padre = [System.IO.Path]::GetDirectoryName($dest)
    Invoke-Accion "mkdir $padre" { New-Item -ItemType Directory -Force -Path $padre | Out-Null }
    Invoke-Accion "enlace $dest -> $ORIGEN" { New-Item -ItemType $TipoEnlace -Path $dest -Value $ORIGEN | Out-Null }
}

function Uninstall-Enlace([string]$etiqueta, [string]$dest) {
    $elem = Get-Elemento $dest
    if ((Test-EsEnlace $elem) -and (Test-ApuntaAlOrigen $dest)) {
        Write-Host "quita    $dest"
        Invoke-Accion "quitar enlace $dest" { Remove-Enlace $dest }
    } elseif ($null -ne $elem) {
        Write-Host "deja     $dest (no es un enlace a este repositorio)"
    } else {
        Write-Host "nada     $dest (no existe)"
    }
}

# ---------------------------------------------------------------- programa

try {
    # Argumentos que PowerShell no reconocio como parametros.
    $extra = @()
    if ($null -ne $Resto) { $extra = @($Resto) }
    $palabrasAyuda = @('-h', '-help', '--help', '--ayuda', '-?', '/?', '/h')
    $pideAyuda = $Ayuda.IsPresent
    $desconocido = $null
    foreach ($e in $extra) {
        if ($palabrasAyuda -contains $e.ToLowerInvariant()) {
            $pideAyuda = $true
        } elseif ($null -eq $desconocido) {
            $desconocido = $e
        }
    }
    if ($pideAyuda) { Show-Ayuda; exit 0 }
    if ($null -ne $desconocido) {
        Write-Err "Opcion desconocida: $desconocido (usa -Ayuda)"
        exit 2
    }

    # Claude primero: su enlace puede pasar por el de .agents, y al desinstalar
    # hay que quitarlo antes de que ese otro deje de existir.
    $destinos = @()
    switch ($Destino.Trim().ToLowerInvariant()) {
        'ambos'   { $destinos = @(@{ Etiqueta = 'claude'; Ruta = $DESTINO_CLAUDE }, @{ Etiqueta = 'agentes'; Ruta = $DESTINO_AGENTES }) }
        'claude'  { $destinos = @(@{ Etiqueta = 'claude'; Ruta = $DESTINO_CLAUDE }) }
        'agentes' { $destinos = @(@{ Etiqueta = 'agentes'; Ruta = $DESTINO_AGENTES }) }
        default {
            Write-Err '-Destino debe ser ambos, claude o agentes'
            exit 2
        }
    }

    $skillMd = [System.IO.Path]::Combine($ORIGEN, 'SKILL.md')
    if (-not (Test-Path -LiteralPath $skillMd -PathType Leaf)) {
        Write-Err "No encuentro ${skillMd}: corre el instalador desde el repositorio."
        exit 1
    }

    if ($Desinstalar) {
        foreach ($d in $destinos) { Uninstall-Enlace $d.Etiqueta $d.Ruta }
        Write-Host ''
        $medidas = [System.IO.Path]::Combine($CasaUsuario, '.local', 'share', $NOMBRE)
        Write-Host "Las mediciones de cada equipo siguen en $medidas y no se tocan."
        exit 0
    }

    foreach ($d in $destinos) { Install-Enlace $d.Etiqueta $d.Ruta }

    Write-Host ''
    $python = Get-ComandoPython
    if ($null -eq $python) {
        Write-Host 'Aviso: falta Python 3 (se probo py -3, python3 y python). Los scripts de la skill lo necesitan.'
    }
    if ($EsWindows) {
        Write-Host 'Aviso: en Windows la skill describe y mide el equipo, pero todavia no recomienda nada: faltan mediciones de equipos reales.'
    }
    if ($Prueba) {
        Write-Host 'Prueba terminada: no se cambio nada.'
        exit 0
    }
    Write-Host 'Listo. Abre una sesion nueva de Claude Code o Codex para que la detecten.'
    Write-Host 'Para ver lo que detecta en este equipo:'
    $comandoPython = 'python'
    if ($null -ne $python) { $comandoPython = $python }
    $perfil = [System.IO.Path]::Combine($ORIGEN, 'scripts', 'perfil.py')
    Write-Host ('  ' + $comandoPython + ' "' + $perfil + '" --formato texto')
    exit 0
} catch {
    Write-Err ('Error: ' + $_.Exception.Message)
    exit 1
}
