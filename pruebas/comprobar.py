#!/usr/bin/env python3
"""Comprobaciones de humo para GitHub Actions (Windows y macOS). No forman parte de la skill.

Uso:
    python pruebas/comprobar.py diagnostico diag.json windows|macos
    python pruebas/comprobar.py medir medir.json <codigo de salida de medir.py> diag.json
    python pruebas/comprobar.py cpu diag.json      # el tiempo de CPU de medir.py no sale vacio
"""
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "skills", "rendimiento-equipo", "scripts"))
sys.dont_write_bytecode = True


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def falla(msg):
    print("FALLA: " + msg)
    sys.exit(1)


def diagnostico(ruta, so):
    d = leer(ruta)
    for k in ("huella", "cpu", "memoria", "gpu", "herramientas", "procesos_pesados", "avisos"):
        if k not in d:
            falla("falta la clave %s" % k)
    niveles = d["cpu"].get("niveles") or []
    if not niveles and so == "macos":
        print("aviso: macOS sin niveles de CPU (las maquinas virtuales de GitHub pueden no publicarlos)")
    elif not niveles or any((n.get("nucleos_fisicos") or 0) < 1 for n in niveles):
        falla("niveles de CPU vacios o sin nucleos: %r" % niveles)
    if sum(n.get("nucleos_logicos") or 0 for n in niveles) > (d["cpu"].get("logicalcpu") or 0):
        falla("mas nucleos logicos por nivel que procesadores logicos")
    if (d["memoria"].get("memsize") or 0) < 2 ** 30:
        falla("memoria total imposible: %r" % d["memoria"].get("memsize"))
    if so == "windows":
        if not d.get("soporte"):
            falla("Windows debe marcar soporte sin recomendaciones medidas")
        if not d["gpu"].get("adaptadores"):
            falla("no se listo ningun adaptador de video")
        if not d["herramientas"]["ffmpeg"].get("elegido"):
            falla("no se encontro ffmpeg")
        if not isinstance(d.get("video"), dict) or "codificadores" not in d["video"]:
            falla("faltan las pruebas de video por hardware")
        if d["memoria"].get("swap") is None:
            print("aviso: sin datos del archivo de paginacion")
    elif "soporte" in d:
        falla("macOS no debe marcar falta de soporte")
    print("OK diagnostico %s: %s | %s | %s GB | GPU %s | video %s" % (
        so, d["cpu"].get("marca"), " + ".join("%s %s" % (n["nombre"], n["nucleos_fisicos"]) for n in niveles),
        d["memoria"].get("memsize_gb"), d["gpu"].get("nombre"), json.dumps(d.get("video"), ensure_ascii=False)[:400]))


def medir(ruta, codigo, ruta_diag):
    codigo = int(codigo)
    d = leer(ruta_diag)
    video = d.get("video") or {}
    abre = [k for k, v in (video.get("codificadores") or {}).items() if v.get("abre")] if d.get("soporte") else []
    if codigo == 2 and d.get("soporte") and not abre:
        print("OK medir: sin codificadores por hardware que abran en esta maquina, medir.py se nego con codigo 2 como debe")
        return
    if codigo not in (0, 1):
        falla("medir.py salio con %s" % codigo)
    out = leer(ruta)
    base = out["variantes"].get("x264_cpu") or {}
    if base.get("fallo"):
        falla("la base libx264 fallo: %r" % base)
    if base.get("cpu_s") is None:
        falla("la base no tiene tiempo de CPU")
    print("OK medir (codigo %s): %s" % (codigo, {k: (v.get("real_s"), v.get("cpu_s"), v.get("fallo")) for k, v in out["variantes"].items()}))


def cpu(ruta_diag):
    import medir as m
    ffmpeg = leer(ruta_diag)["herramientas"]["ffmpeg"]["elegido"]
    r = m.correr([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                  "testsrc2=size=1280x720:rate=30:duration=3", "-c:v", "libx264", "-f", "null", "-"])
    if r["rc"] != 0 or not r["cpu_s"] or r["cpu_s"] <= 0:
        falla("correr() no midio CPU: %r" % r)
    print("OK cpu: %r" % r)


if __name__ == "__main__":
    modo, resto = sys.argv[1], sys.argv[2:]
    {"diagnostico": diagnostico, "medir": medir, "cpu": cpu}[modo](*resto)
