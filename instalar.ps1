# Instala claudemon en Windows: copia el programa a %USERPROFILE%\claudemon y crea el comando «claudemon».
# Uso (PowerShell):  powershell -ExecutionPolicy Bypass -File instalar.ps1
# Importante: NO usar "Stop" acá. Los comandos nativos (python, pip) escriben avisos o errores esperados en stderr
# (por ejemplo «No module named psutil») y con "Stop" PowerShell los toma como fallos fatales. Los códigos de salida se revisan a mano.
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$destino = Join-Path $env:USERPROFILE "claudemon"

# 1) Python 3.8 o más nuevo
$py = $null
foreach ($c in @("py", "python", "python3")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try {
        & $c -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $py = $c; break }
    } catch { }
}
if (-not $py) {
    Write-Host "No encontré Python 3.8 o más nuevo." -ForegroundColor Red
    Write-Host "Instalalo desde https://www.python.org/downloads/ (tildá «Add python.exe to PATH») o con:  winget install Python.Python.3.12"
    exit 1
}
Write-Host "OK Python: $(& $py --version)"

# 2) copiar el programa y crear el comando (claudemon.cmd)
New-Item -ItemType Directory -Force -Path $destino -ErrorAction Stop | Out-Null
Copy-Item (Join-Path $aqui "claudemon.py") (Join-Path $destino "claudemon.py") -Force -ErrorAction Stop
$lanzador = "@echo off`r`n$py `"%~dp0claudemon.py`" %*`r`n"
[IO.File]::WriteAllText((Join-Path $destino "claudemon.cmd"), $lanzador, [Text.Encoding]::ASCII)
Write-Host "OK Instalado en $destino"

# 3) agregar la carpeta al PATH del usuario
$pathUsuario = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $pathUsuario) { $pathUsuario = "" }
if (($pathUsuario -split ";") -notcontains $destino) {
    [Environment]::SetEnvironmentVariable("Path", ($pathUsuario.TrimEnd(";") + ";" + $destino), "User")
    Write-Host "OK Agregué $destino al PATH (abrí una terminal NUEVA para que lo tome)"
}

# 4) psutil (solo para la pantalla en vivo)
& $py -c "import psutil" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "OK psutil ya está instalado"
} else {
    Write-Host ""
    Write-Host "La pantalla en vivo necesita la librería psutil (los informes andan sin ella)."
    if ($env:CLAUDEMON_SIN_PREGUNTAS) { $r = "n" } else { $r = Read-Host "¿La instalo ahora? [S/n]" }
    if ($r -notmatch "^[nN]") {
        & $py -m pip install --user psutil
        if ($LASTEXITCODE -eq 0) { Write-Host "OK psutil instalado" } else { Write-Host "No pude instalar psutil. Probá:  $py -m pip install --user psutil" -ForegroundColor Yellow }
    }
}

Write-Host ""
Write-Host "Listo. Abrí una terminal nueva y probá:   claudemon demo"
Write-Host "Ayuda:                                    claudemon ayuda"
Write-Host "Recomendado: usar Windows Terminal (la consola vieja muestra mal algunos símbolos; si pasa, agregá --ascii)."
