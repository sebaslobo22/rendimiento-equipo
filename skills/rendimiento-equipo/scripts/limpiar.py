#!/usr/bin/env python3
"""Apaga los procesos pesados PROPIOS que quedaron vivos (servidores Whisper de agentes,
Remotion o Chrome sin ventana huerfanos). Por defecto solo MUESTRA lo que haria (--dry-run).

Clasificacion (la hace diagnosticar.py y se repite aqui al actuar):
  propio      whisper-server lanzado por un agente (-m ... --port 88xx); remotion o chrome sin
              ventana huerfanos (su padre es launchd) o hijos de uno de esos huerfanos.
  protegido   whisper-server de la app OpenWhispr (usa --model y --host) o cualquier proceso que
              cuelgue de OpenWhispr.app. Nunca se toca, ni siquiera con --pid.
  en_uso      todo lo demas (un render con su padre vivo, ffmpeg, un whisper-server raro).
              Tampoco se toca.

Con --aplicar envia SIGTERM por PID, uno por uno, y comprueba que el PID siga siendo el mismo
proceso antes de cada envio. No usa SIGKILL: si algo no cierra, lo informa y lo deja.
Con --pid N (repetible) se limita a esos PID; sirve a un subagente para apagar solo lo que lanzo.

Uso:
    python3 limpiar.py                 # muestra, no termina nada
    python3 limpiar.py --aplicar
    python3 limpiar.py --aplicar --pid 4242

Codigos de salida: 0 = ok (o nada que hacer); 1 = algun proceso no cerro; 2 = argumentos invalidos
o PID protegido/no apagable.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

sys.dont_write_bytecode = True  # no ensuciar la carpeta compartida de la skill
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import diagnosticar as dg  # noqa: E402


def viva(pid):
    """Vivo de verdad: un zombi (ya termino, su padre no lo ha recogido) cuenta como terminado."""
    rc, out, _ = dg.ejecutar(["ps", "-o", "stat=", "-p", str(pid)], 5)
    estado = out.strip()
    return rc == 0 and bool(estado) and not estado.startswith("Z")


def mismo_proceso(pid, comando):
    """El PID sigue siendo el proceso que clasificamos (evita matar uno nuevo que reuso el numero)."""
    ahora = dg.listar_procesos().get(pid)
    return bool(ahora) and ahora["cmd"][:240] == comando


def terminar(p, espera):
    pid = p["pid"]
    if not mismo_proceso(pid, p["comando"]):
        return {"pid": pid, "resultado": "ya no existe o cambio de proceso: no se toco"}
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"pid": pid, "resultado": "ya habia terminado"}
    except PermissionError:
        return {"pid": pid, "resultado": "sin permiso para terminarlo"}
    limite = time.time() + espera
    while time.time() < limite:
        if not viva(pid):
            return {"pid": pid, "resultado": "terminado (SIGTERM)"}
        time.sleep(0.2)
    return {"pid": pid, "resultado": "sigue vivo tras %ss: no se fuerza, revisalo a mano" % espera}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Apaga procesos pesados propios (whisper-server de agentes, remotion/chrome huerfanos). "
                    "Muestra por defecto; actua solo con --aplicar. Nunca toca OpenWhispr.",
        epilog="Los procesos protegidos y los que estan en uso no se terminan nunca.")
    ap.add_argument("--aplicar", action="store_true", help="termina los procesos propios con SIGTERM (por PID)")
    ap.add_argument("--dry-run", action="store_true", help="solo mostrar (es el comportamiento por defecto)")
    ap.add_argument("--pid", type=int, action="append", default=[], help="limitarse a este PID propio (repetible)")
    ap.add_argument("--esperar", type=float, default=5.0, help="segundos que se espera a que cada proceso cierre (por defecto %(default)s)")
    args = ap.parse_args(argv)
    if args.aplicar and args.dry_run:
        print("error: --aplicar y --dry-run se contradicen; usa solo uno.", file=sys.stderr)
        return 2

    procs = dg.procesos_pesados()
    propios = [p for p in procs if p["clase"] == "propio"]
    protegidos = [p for p in procs if p["clase"] == "protegido"]
    en_uso = [p for p in procs if p["clase"] == "en_uso"]

    objetivo = propios
    if args.pid:
        por_pid = {p["pid"]: p for p in procs}
        for n in args.pid:
            p = por_pid.get(n)
            if p is None:
                print("error: el PID %d no es un proceso pesado conocido (whisper-server, remotion, chrome sin ventana, ffmpeg)." % n, file=sys.stderr)
                return 2
            if p["clase"] != "propio":
                print("error: el PID %d es %s (%s): no se apaga desde aqui." % (n, p["clase"], p["motivo"]), file=sys.stderr)
                return 2
        objetivo = [p for p in propios if p["pid"] in args.pid]

    # Primero las raices (cuyo padre no es otro objetivo), despues los hijos.
    ids = {p["pid"] for p in objetivo}
    objetivo.sort(key=lambda p: (p["padre"] in ids, p["pid"]))

    salida = {
        "modo": "aplicar" if args.aplicar else "dry-run",
        "propios": propios,
        "protegidos": protegidos,
        "en_uso": en_uso,
        "se_terminarian" if not args.aplicar else "objetivo": [p["pid"] for p in objetivo],
        "resultado": [],
    }
    if args.aplicar:
        salida["resultado"] = [terminar(p, args.esperar) for p in objetivo]
    print(json.dumps(salida, ensure_ascii=False, indent=2))

    def linea(p):
        puerto = " puerto %s" % p["puerto"] if p["puerto"] else ""
        return "  pid %-6s %-16s edad %-9s%s  %s" % (p["pid"], p["tipo"], p["edad"], puerto, p["motivo"])

    print("%s: %d propio(s), %d protegido(s), %d en uso." % (
        "APLICADO" if args.aplicar else "DRY-RUN (no se termino nada)", len(propios), len(protegidos), len(en_uso)), file=sys.stderr)
    for titulo, grupo in (("propios", propios), ("protegidos (no se tocan)", protegidos), ("en uso (no se tocan)", en_uso)):
        if grupo:
            print(titulo + ":", file=sys.stderr)
            for p in grupo:
                print(linea(p), file=sys.stderr)
    if not args.aplicar and objetivo:
        print("Para apagar los propios: python3 %s --aplicar" % os.path.join(AQUI, "limpiar.py"), file=sys.stderr)
    fallos = [r for r in salida["resultado"] if r["resultado"].startswith("sigue vivo") or r["resultado"].startswith("sin permiso")]
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
