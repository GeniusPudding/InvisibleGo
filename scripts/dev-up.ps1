# Starts the dev stack (web server, no TLS) and prints the LAN URLs
# other devices on the network can connect to.
#
# Run from repo root:
#   .\scripts\dev-up.ps1
# Extra flags pass through to docker compose:
#   .\scripts\dev-up.ps1 --force-recreate

$ErrorActionPreference = 'Stop'

Write-Host ''
Write-Host '=== Local + LAN URLs to share ===' -ForegroundColor Green
Write-Host '  http://localhost:8000                 (this machine only)'

try {
    $addresses = Get-NetIPAddress -AddressFamily IPv4 `
        -SuffixOrigin Dhcp, Manual `
        -ErrorAction Stop |
        Where-Object { $_.IPAddress -notmatch '^169\.254\.' } |
        Sort-Object InterfaceAlias
} catch {
    $addresses = @()
}

if ($addresses.Count -eq 0) {
    Write-Host '  (no LAN adapter detected)' -ForegroundColor Yellow
} else {
    foreach ($a in $addresses) {
        Write-Host ("  http://{0}:8000  ({1})" -f $a.IPAddress, $a.InterfaceAlias) -ForegroundColor Cyan
    }
}

Write-Host ''
Write-Host 'First time on this machine? Open the firewall once:' -ForegroundColor DarkGray
Write-Host "  New-NetFirewallRule -DisplayName 'InvisibleGo 8000' -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow" -ForegroundColor DarkGray
Write-Host '  (must run PowerShell as Administrator)' -ForegroundColor DarkGray
Write-Host ''

# Pass any extra args through to compose
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build @args
