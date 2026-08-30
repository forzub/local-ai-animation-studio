$ErrorActionPreference = "Stop"

Write-Host "Local AI Animation Studio bootstrap"
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is not available in PATH"
}

if (-not (Test-Path ".git")) {
    git init
}

git status

Write-Host ""
Write-Host "Next:"
Write-Host "  git add ."
Write-Host '  git commit -m "chore: bootstrap local AI animation studio"'
