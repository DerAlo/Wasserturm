#!/bin/bash
# Bewegt jede Achse kurz über die laufende App (ungesichert wird nie geschaltet -> kein Schuss).
#   servotest.sh tilt|pan|trig
P=~/turret/tools/probe.py
rep() { for i in $(seq "$2"); do printf '%s\n' "$1"; done; }
case "$1" in
tilt)
  mapfile -t A < <(rep '{"t":"manual","pan":0,"tilt":1}' 12)
  python3 $P 3 /tmp/tilt_up.jpg "${A[@]}" | grep -E 'core-Verlauf|log'
  mapfile -t A < <(rep '{"t":"manual","pan":0,"tilt":-1}' 24)
  python3 $P 4.5 /tmp/tilt_down.jpg "${A[@]}" | grep -E 'core-Verlauf|log'
  python3 $P 2.5 /tmp/tilt_home.jpg '{"t":"cmd","c":"tilt_home"}' | grep -E 'core-Verlauf|log'
  ;;
pan)
  mapfile -t A < <(rep '{"t":"manual","pan":1,"tilt":0}' 6)
  python3 $P 2.5 /tmp/pan_a.jpg "${A[@]}" | grep -E 'core-Verlauf|log'
  mapfile -t A < <(rep '{"t":"manual","pan":-1,"tilt":0}' 6)
  python3 $P 2.5 /tmp/pan_b.jpg "${A[@]}" | grep -E 'core-Verlauf|log'
  ;;
trig)
  python3 $P 2.5 - '{"t":"cmd","c":"trig","v":60}' | grep -E 'core-Verlauf|log'
  python3 $P 2.5 - '{"t":"cmd","c":"trig","v":40}' | grep -E 'core-Verlauf|log'
  python3 $P 2.5 - '{"t":"cmd","c":"trig","v":90}' | grep -E 'core-Verlauf|log'
  ;;
esac
