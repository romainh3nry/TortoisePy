#
# Installe tortoisePy et sa commande `topy` — Windows.
#
# `uv` plutôt que `pip` : il crée un environnement isolé ET télécharge
# l'interpréteur au besoin. L'utilisateur n'a donc pas à installer
# Python 3.13 lui-même, ce qui est le vrai obstacle.
#
#   irm https://raw.githubusercontent.com/romainh3nry/TortoisePy/v0.7.0/scripts/install.ps1 | iex
#
# `irm | iex` et non `curl | sh` : il n'existe pas de `sh` sous Windows,
# et `curl` y est un alias d'`Invoke-WebRequest`, qui n'accepte pas
# `-LsSf`. C'est la forme employée par uv, rustup et Chocolatey.

$ErrorActionPreference = "Stop"

$Version = "v0.7.0"
$Depot = "git+https://github.com/romainh3nry/TortoisePy@$Version"

Write-Host "tortoisePy $Version"
Write-Host ""

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "-> Installation de uv..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    # `uv` vient d'être posé : il n'est pas encore visible dans CETTE session.
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "-> Installation de tortoisePy..."
Write-Host "   (environ 1,2 Go a telecharger : c'est Qt, pas une erreur)"
# `--force` pour que relancer le script mette à jour plutôt que d'échouer.
uv tool install --force $Depot

Write-Host ""

# Vérifier son propre résultat : l'installation peut parfaitement réussir
# alors que la commande reste introuvable, faute de PATH. C'est
# précisément là qu'un utilisateur abandonne, en croyant que
# l'installation a échoué.
$ok = $false
if (Get-Command topy -ErrorAction SilentlyContinue) {
    try {
        $sortie = topy --version 2>$null
        if ($LASTEXITCODE -eq 0) { $ok = $true }
    } catch {
        $ok = $false
    }
}

if ($ok) {
    Write-Host "OK - $sortie installe."
    Write-Host ""
    Write-Host "   Placez-vous dans un projet Git et lancez :"
    Write-Host "       topy ."
    Write-Host ""
    Write-Host "   Ou visez un depot ailleurs :"
    Write-Host "       topy C:\code\mon-projet"
} else {
    Write-Host "ATTENTION - tortoisePy est installe, mais « topy » n'est pas dans votre PATH."
    Write-Host ""
    Write-Host "   Le plus simple :"
    Write-Host "       uv tool update-shell"
    Write-Host ""
    Write-Host "   Puis rouvrez PowerShell."
    exit 1
}
