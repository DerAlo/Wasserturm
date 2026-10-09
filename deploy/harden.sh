#!/bin/bash
# Einmalige Systemeinstellungen auf dem Coral für den Dauerbetrieb (mit sudo ausführen, wiederholbar).
set -u
# Hardware-Watchdog: hängt das System, startet das Board nach 30 s neu. Kernel-Panik -> Neustart.
mkdir -p /etc/systemd/system.conf.d /etc/systemd/journald.conf.d /etc/NetworkManager/conf.d
printf '[Manager]\nRuntimeWatchdogSec=30\nShutdownWatchdogSec=2min\n' > /etc/systemd/system.conf.d/watchdog.conf
printf 'kernel.panic = 10\nkernel.panic_on_oops = 1\n' > /etc/sysctl.d/90-turret.conf
sysctl -q -p /etc/sysctl.d/90-turret.conf
# Protokolle über Neustarts hinweg behalten (begrenzt)
mkdir -p /var/log/journal
printf '[Journal]\nStorage=persistent\nSystemMaxUse=80M\n' > /etc/systemd/journald.conf.d/turret.conf
systemctl restart systemd-journald
# WLAN-Stromsparen aus
printf '[connection]\nwifi.powersave = 2\n' > /etc/NetworkManager/conf.d/wifi-powersave-off.conf
# Dienste, die der Turm nicht braucht (Bildschirm, Bluetooth, USB-Gadget, automatische Updates)
for u in weston bluetooth btfw_loader usb-gadget usb-gadget-getty-ttyGS0 unattended-upgrades rsync \
         apt-daily.timer apt-daily-upgrade.timer man-db.timer; do
  systemctl disable --now "$u" >/dev/null 2>&1
done
systemctl reset-failed
# Dienste des Turms
cp /home/mendel/turret/deploy/turret.service /home/mendel/turret/deploy/netwatch.service /etc/systemd/system/
systemctl daemon-reload
systemctl daemon-reexec
systemctl enable turret netwatch >/dev/null 2>&1
systemctl restart netwatch
echo fertig
