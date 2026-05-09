# architect.ps1 - Launcher Claude Code en mode architecte (Artiste Coloriage)

$ErrorActionPreference = "Stop"
$ProjectRoot = "D:\projets\artiste-coloriage"
$MemoryFile = Join-Path $ProjectRoot "docs\architect\MEMORY.md"

Set-Location $ProjectRoot

Write-Host ""
Write-Host "=== Artiste Coloriage - Mode Architecte ===" -ForegroundColor Cyan
Write-Host "Projet : $ProjectRoot" -ForegroundColor Gray
Write-Host ""

if (-not (Test-Path $MemoryFile)) {
    Write-Host "[!] MEMORY.md absent - bootstrap requis." -ForegroundColor Yellow
    Write-Host "    Tape : " -NoNewline -ForegroundColor Yellow
    Write-Host "/architect-bootstrap" -ForegroundColor White
} else {
    $lineCount = (Get-Content $MemoryFile).Count
    $lastUpdate = (Get-Item $MemoryFile).LastWriteTime.ToString("yyyy-MM-dd HH:mm")
    Write-Host "[+] MEMORY.md : $lineCount lignes, maj $lastUpdate" -ForegroundColor Green
    Write-Host "    Tape : " -NoNewline -ForegroundColor Green
    Write-Host "/architect-load" -ForegroundColor White
    Write-Host "    Fin de session : " -NoNewline -ForegroundColor Gray
    Write-Host "/architect-save" -ForegroundColor White
}

Write-Host ""
Write-Host "Lancement de Claude Code..." -ForegroundColor Gray
Write-Host ""

claude
