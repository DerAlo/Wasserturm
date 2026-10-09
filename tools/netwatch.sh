#!/bin/bash
# WLAN-Wächter (Dienst netwatch): prüft alle 20 s, ob der Router antwortet.
#   1 min weg  -> WLAN neu verbinden
#   3 min weg  -> NetworkManager neu starten
#   10 min weg -> Board neu starten (nur einmal je Ausfall, damit ein abgeschalteter Router
#                 keine Neustart-Schleife auslöst)
FLAG=/var/tmp/netwatch_rebooted
fail=0
while sleep 20; do
  gw=$(ip route | awk '/^default/{print $3; exit}')
  if [ -n "$gw" ] && ping -c 2 -W 3 -q "$gw" >/dev/null 2>&1; then
    [ $fail -ge 3 ] && logger -t netwatch "Router wieder erreichbar nach $((fail * 20)) s"
    fail=0
    rm -f $FLAG
    continue
  fi
  fail=$((fail + 1))
  logger -t netwatch "Router nicht erreichbar ($fail)"
  case $fail in
    3) nmcli device disconnect wlan0; sleep 2; nmcli device connect wlan0 ;;
    9) systemctl restart NetworkManager ;;
    30) if [ ! -e $FLAG ]; then touch $FLAG; sync; logger -t netwatch "Neustart"; systemctl reboot; fi ;;
  esac
done
