# Kopiert die Coral-App auf das Board und startet den Dienst neu.
#   .\deploy\deploy.ps1          nur Coral-App
#   .\deploy\deploy.ps1 -Core    zusätzlich turret_main.py auf den Core (per mpremote, kein Flashen)
param([switch]$Core)
$h = 'mendel@192.168.178.110'
$root = Split-Path $PSScriptRoot -Parent
ssh -o BatchMode=yes $h "mkdir -p ~/turret/app ~/turret/web ~/turret/models ~/turret/tools ~/turret/deploy"
# PowerShell löst Platzhalter für scp nicht auf, deshalb die Dateien einzeln übergeben
function Send($pattern, $dest) {
    scp -q -o BatchMode=yes (Get-ChildItem -File $pattern).FullName "${h}:$dest"
    if ($LASTEXITCODE) { throw "Kopieren fehlgeschlagen: $pattern" }
}
Send "$root\tools\*" 'turret/tools/'
Send "$root\deploy\*" 'turret/deploy/'
Send "$root\coral\*.py" 'turret/app/'
Send "$root\web\*" 'turret/web/'
scp -q -o BatchMode=yes "$root\turret_main.py" "$root\boot.py" "${h}:turret/"
if ($Core) {
    ssh -o BatchMode=yes $h "sudo -n systemctl stop turret; cd ~/turret; timeout 60 tools/mp cp turret_main.py :app/turret_main.py; timeout 8 tools/mp exec 'import machine; machine.reset()' >/dev/null 2>&1; sleep 3"
}
ssh -o BatchMode=yes $h "sudo -n systemctl restart turret; sleep 6; systemctl is-active turret; journalctl -u turret -n 15 --no-pager"
