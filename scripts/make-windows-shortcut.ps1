<#
.SYNOPSIS
    Crée un raccourci Windows « tortoisePy » portant l'icône de l'application.

.DESCRIPTION
    Sur Windows, `setWindowIcon` suffit déjà pour la fenêtre et la barre des
    tâches — contrairement à macOS, où il faut un bundle. Ce script ne sert
    donc qu'au confort : un raccourci lançable depuis le menu Démarrer ou le
    bureau, avec la bonne icône, plutôt que de taper `tgraph`.

    Il lance `pythonw.exe` et non `python.exe` : sans cela une console noire
    s'ouvrirait derrière la fenêtre.

.PARAMETER Destination
    Où déposer le raccourci. Par défaut, le bureau de l'utilisateur.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\make-windows-shortcut.ps1
#>
param(
    [string]$Destination = [Environment]::GetFolderPath('Desktop')
)

$ErrorActionPreference = 'Stop'

$racine = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$icone  = Join-Path $racine 'src\tortoisepy\resources\tortoisepy.ico'

if (-not (Test-Path $icone)) {
    Write-Error "Icône absente : $icone`nLancez d'abord : python scripts/make-icon.py"
}

# L'interpréteur du venv s'il existe, sinon celui du PATH : le raccourci
# doit retrouver le paquet `tortoisepy`, pas n'importe quel Python.
$venvw = Join-Path $racine '.venv\Scripts\pythonw.exe'
if (Test-Path $venvw) {
    $python = $venvw
} else {
    $python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    if (-not $python) {
        Write-Error "pythonw.exe introuvable. Installez Python, ou créez le venv du projet."
    }
}

$lien = Join-Path $Destination 'tortoisePy.lnk'

$shell    = New-Object -ComObject WScript.Shell
$raccourci = $shell.CreateShortcut($lien)
$raccourci.TargetPath       = $python
$raccourci.Arguments        = '-c "from tortoisepy.cli import main; raise SystemExit(main())"'
$raccourci.WorkingDirectory = $racine
$raccourci.IconLocation     = $icone
$raccourci.Description      = 'Revision Graph de TortoiseGit, pour Git'
$raccourci.Save()

Write-Host "Raccourci créé : $lien"
Write-Host "Interpréteur   : $python"
