# -*-coding:utf-8-*-
# boot.py – CyberBrick Core, Wasserturm-Variante
# Original liegt als core_backup/boot.py im Projektordner und als /boot_orig.py auf dem Core.
# Zurück zur Original-RC-Firmware: Datei /turret_off auf dem Core anlegen
#   mpremote resume exec "open('/turret_off','w').close()"
# Stürzt turret_main ab, läuft ebenfalls die Original-RC-Firmware weiter.

import bbl_product
import sys
import os

bbl_product.set_app_name("RC")
bbl_product.set_app_version("01.00.01.01")
del bbl_product

sys.path.append('/app')

if 'turret_off' in os.listdir('/'):
    import rc_main
    rc_main.main()
else:
    try:
        import turret_main
        turret_main.main()
    except KeyboardInterrupt:
        pass                     # Strg+C -> REPL
    except Exception as e:
        sys.print_exception(e)
        import rc_main
        rc_main.main()
