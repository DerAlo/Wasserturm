#!/bin/bash
# Schreibt während eines Testlaufs Kernelmeldungen, Temperatur und Last auf die Platte (mit sync),
# damit nach einem unerwarteten Neustart des Boards noch etwas zu sehen ist.
#   watch.sh <sekunden>     -> ~/turret/test/watch.log
L=~/turret/test/watch.log
echo "=== $(date +%T) start" > $L
sudo -n dmesg -w >> $L 2>&1 &
D=$!
for i in $(seq "$1"); do
  echo "t=$i up=$(cut -d' ' -f1 /proc/uptime) temp=$(cat /sys/class/thermal/thermal_zone0/temp) load=$(cut -d' ' -f1 /proc/loadavg) mem=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo) turret=$(systemctl is-active turret)" >> $L
  sync
  sleep 1
done
kill $D
echo "=== ende" >> $L
sync
