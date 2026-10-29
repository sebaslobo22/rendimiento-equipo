#!/usr/bin/env python3
"""Pruebas cortas A/B para decidir un metodo con datos de ESTE equipo.

Subcomandos:
  codificar   ffmpeg: libx264 (CPU) frente a h264_videotoolbox, con decodificacion en CPU o por hardware.
              En Windows, libx264 frente a cada codificador por hardware que abre en el equipo
              (h264_nvenc, h264_qsv, h264_amf, h264_mf).
  decodificar ffmpeg: decodificar en CPU frente a -hwaccel videotoolbox.
              En Windows, CPU frente a cada acelerador que abre (cuda, qsv, d3d11va).
  remotion    render corto de una composicion: base, angle, hardware y ambos (solo macOS por ahora)
  voz         modelos de dictado de OpenWhispr instalados (whisper.cpp): tiempo, memoria y error con un audio
              tuyo; con --texto (lo que dice el audio) calcula el porcentaje de palabras erradas
  paralelo    cuantas codificaciones por hardware rinden a la vez (1, 2, 4...): los chips Max y Ultra traen
              2 y 4 motores de codificacion y ninguna API dice cuantos hay

En Windows el tiempo de CPU sale de un Job Object, que suma el proceso y sus hijos: el ffmpeg de Chocolatey o
Scoop es un atajo que lanza el ffmpeg real como hijo.

Mide tiempo real y CPU (resource.getrusage de los hijos), y compara la calidad con la diferencia
media de un fotograma (sobre 255). Intercala las repeticiones (A,B,C,A,B,C...) para repartir el ruido.
Salida: JSON por stdout. Los archivos temporales se borran al terminar.

Con --registrar:
  - agrega el resultado a ~/.local/share/rendimiento-equipo/<huella>/mediciones.md
  - actualiza perfil-medido.json SOLO si hay un ganador claro: al menos 15 % mejor en la metrica
    elegida (--criterio tiempo|cpu, por defecto tiempo) y diferencia visual media menor de 2/255.
  - no actualiza el perfil si habia otros procesos pesados en marcha (ruido), salvo --aceptar-ruido.

Ejemplos:
  python3 medir.py codificar --archivo clip.mov --segundos 5
  python3 medir.py decodificar --archivo clip.mov --segundos 30 --repeticiones 3 --registrar
  python3 medir.py remotion --proyecto ~/proyecto --composicion Reel --fotogramas 0-149 --repeticiones 3

Codigos de salida: 0 = medicion hecha; 1 = fallo de una variante; 2 = argumentos o archivos invalidos.
"""
from __future__ import annotations

import argparse
import json
import operator
import os
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime

try:
    import resource  # solo existe en macOS y Linux
except ImportError:  # Windows: main() avisa antes de usarlo
    resource = None

sys.dont_write_bytecode = True  # no ensuciar la carpeta compartida de la skill
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import diagnosticar as dg  # noqa: E402
import perfil as pf  # noqa: E402

UMBRAL_MEJORA = 0.15
UMBRAL_VISUAL = 2.0
BITRATE = pf.BITRATE_FINAL

VAR_CODIFICAR = {
    "x264_cpu": {"entrada": [], "salida": ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]},
    "vt_dec_cpu": {"entrada": [], "salida": ["-c:v", "h264_videotoolbox", "-b:v", "{b}", "-allow_sw", "0"]},
    "vt_dec_hw": {"entrada": ["-hwaccel", "videotoolbox"], "salida": ["-c:v", "h264_videotoolbox", "-b:v", "{b}", "-allow_sw", "0"]},
}
VAR_REMOTION = {
    "base": [],
    "angle": ["--gl=angle"],
    "hardware": ["--hardware-acceleration=required", "--video-bitrate={b}"],
    "ambos": ["--gl=angle", "--hardware-acceleration=required", "--video-bitrate={b}"],
}


class ErrorUso(Exception):
    """Argumento o archivo invalido: se imprime en stderr y sale con codigo 2."""


# ---------------------------------------------------------------- medicion

def _lanzar(cmd, cwd=None):
    kw = dict(cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
              text=True, encoding="utf-8", errors="replace")
    if resource:
        return subprocess.Popen(cmd, **kw)
    import plataforma_windows as pw
    return pw.lanzar_contado(cmd, **kw)  # Job Object: cuenta tambien los hijos (atajos de Chocolatey o Scoop)


def correr_varios(cmds, cwd=None, timeout=1800):
    """Lanza todos los comandos a la vez y mide desde el arranque hasta que termina el ultimo.

    CPU (usuario+sistema) sumada de todos: de los hijos en macOS, de cada arbol de procesos en Windows.
    """
    antes = resource.getrusage(resource.RUSAGE_CHILDREN) if resource else None
    t0 = time.perf_counter()
    procs = [_lanzar(c, cwd) for c in cmds]
    rc, errores = 0, []
    for p in procs:
        try:
            _, err = p.communicate(timeout=max(1.0, t0 + timeout - time.perf_counter()))
            prc = p.returncode
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            prc, err = 124, "tiempo limite de %ss agotado" % timeout
        if prc != 0:
            rc = rc or prc
            errores.append((err or "").strip())
    real = time.perf_counter() - t0
    if resource:
        despues = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = round((despues.ru_utime - antes.ru_utime) + (despues.ru_stime - antes.ru_stime), 2)
    else:
        import plataforma_windows as pw
        partes = [pw.tiempo_cpu(p) for p in procs]
        cpu = None if None in partes else round(sum(partes), 2)
    return {"real_s": round(real, 2), "cpu_s": cpu, "rc": rc, "error": " | ".join(errores)[-400:]}


def correr(cmd, cwd=None, timeout=1800):
    """Ejecuta un comando y mide tiempo real y CPU (usuario+sistema)."""
    return correr_varios([cmd], cwd, timeout)


def duracion(ffmpeg, archivo):
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", archivo], capture_output=True, text=True, timeout=60)
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def fotograma(ffmpeg, archivo, t, hw=False):
    """hw: True para VideoToolbox, o el nombre de un acelerador (cuda, qsv, d3d11va)."""
    acel = "videotoolbox" if hw is True else hw
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"] + (["-hwaccel", acel] if acel else []) + \
          ["-ss", "%.3f" % t, "-i", archivo, "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    return r.stdout if r.returncode == 0 else b""


def diferencia(a, b):
    """Diferencia absoluta media por canal, sobre 255. None si no se pueden comparar."""
    if not a or len(a) != len(b):
        return None
    return round(sum(map(abs, map(operator.sub, a, b))) / len(a), 3)


def resumir(corridas):
    ok = [c for c in corridas if c["rc"] == 0]
    if not ok:
        return {"fallo": True, "corridas": corridas}
    cpus = [c["cpu_s"] for c in ok if c["cpu_s"] is not None]
    return {
        "real_s": round(statistics.median(c["real_s"] for c in ok), 2),
        "cpu_s": round(statistics.median(cpus), 2) if cpus else None,
        "reales": [c["real_s"] for c in ok],
        "cpus": cpus,
        "fallidas": len(corridas) - len(ok),
    }


def decidir(base, cand, dif, criterio):
    """Ganador claro: >=15 % mejor en la metrica y diferencia visual media < 2/255."""
    m = "real_s" if criterio == "tiempo" else "cpu_s"
    if base.get("fallo") or cand.get("fallo") or not base[m] or not cand[m]:
        return None, None, "una de las variantes fallo"
    mejora = 1 - cand[m] / base[m]
    visual_ok = dif is not None and dif < UMBRAL_VISUAL
    if not visual_ok:
        return None, mejora, "diferencia visual %s (limite %s)" % ("no medida" if dif is None else dif, UMBRAL_VISUAL)
    if mejora >= UMBRAL_MEJORA:
        return "candidato", mejora, "el candidato es %.0f %% mejor en %s" % (mejora * 100, m)
    peor = 1 - base[m] / cand[m]
    if peor >= UMBRAL_MEJORA:
        return "base", mejora, "la base es %.0f %% mejor en %s" % (peor * 100, m)
    return None, mejora, "diferencia menor al %.0f %%: sin ganador claro" % (UMBRAL_MEJORA * 100)


def comparar(res, base, cand, dif, criterio):
    g, mejora, motivo = decidir(res[base], res[cand], dif, criterio)
    otra = lambda m: None if res[base].get("fallo") or res[cand].get("fallo") else round(1 - res[cand][m] / res[base][m], 3)  # noqa: E731
    return {"base": base, "candidato": cand, "mejora_real": otra("real_s"), "mejora_cpu": otra("cpu_s"),
            "dif_visual": dif, "ganador": g, "motivo": motivo}


def ruido():
    """Procesos pesados ajenos que falsean una medicion (render, chrome sin ventana, ffmpeg)."""
    vivos = [p for p in dg.procesos_pesados() if p["tipo"] in ("remotion", "chrome-headless", "ffmpeg")]
    try:
        carga = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):  # Windows no tiene getloadavg
        carga = None
    return {"hay_ruido": bool(vivos), "procesos": [{"pid": p["pid"], "tipo": p["tipo"]} for p in vivos], "carga_1min": carga}


# ---------------------------------------------------------------- perfil y registro

def hoy():
    return datetime.now().strftime("%Y-%m-%d")


def actualizar_perfil(huella, cambios):
    """cambios: {("ffmpeg","codificacion"): {...}}. Escribe de forma atomica."""
    ruta = os.path.join(dg.directorio_datos(huella), "perfil-medido.json")
    datos = dg.leer_json(ruta) or {"esquema": 1, "huella": huella}
    for (a, b), valor in cambios.items():
        datos.setdefault(a, {})
        previo = datos[a].get(b) if isinstance(datos[a].get(b), dict) else {}
        nuevo = dict(previo)
        nuevo.update(valor)
        datos[a][b] = nuevo
    datos["actualizado"] = hoy()
    dg.escribir_json_atomico(ruta, datos)
    return ruta


def escribir_md(huella, titulo, ctx, filas, comparaciones, decision_txt):
    ruta = os.path.join(dg.directorio_datos(huella), "mediciones.md")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nuevo = not os.path.exists(ruta)
    L = []
    if nuevo:
        L += ["# Mediciones de este equipo", "", "Huella: `%s`. Cada bloque lo agrega `medir.py --registrar`." % huella, ""]
    L += ["## %s · %s" % (datetime.now().strftime("%Y-%m-%d %H:%M"), titulo), "", ctx, "",
          "| Variante | Real (s) | CPU (s) | Tamaño (MB) | Dif. visual |", "|---|---|---|---|---|"]
    L += filas
    L += [""] + ["- %s → %s: %s" % (c["base"], c["candidato"], c["motivo"]) for c in comparaciones]
    L += ["", "Decisión: %s" % decision_txt, ""]
    with open(ruta, "a", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return ruta


def filas_md(res, difs, tamanos):
    out = []
    for n, r in res.items():
        if r.get("fallo"):
            out.append("| %s | falló | | | |" % n)
        else:
            out.append("| %s | %s | %s | %s | %s |" % (n, r["real_s"], r["cpu_s"], tamanos.get(n, ""), difs.get(n, "")))
    return out


# ---------------------------------------------------------------- subcomandos

def resolver_ffmpeg(args):
    if args.ffmpeg:
        ruta = os.path.expanduser(args.ffmpeg)
    else:
        ruta = (dg.buscar_ffmpeg([]) or {}).get("elegido")
    if not ruta or not os.path.isfile(ruta):
        raise ErrorUso("No encuentro ffmpeg. Pasa --ffmpeg <ruta> o define RENDIMIENTO_FFMPEG. "
                       "Corre diagnosticar.py para ver los que hay en este equipo.")
    return ruta


def validar_archivo(args):
    ruta = os.path.expanduser(args.archivo)
    if not os.path.isfile(ruta):
        raise ErrorUso("No existe el archivo: %r. Si la carpeta termina en espacio, pasa la ruta entre comillas "
                       "con ese espacio incluido." % ruta)
    return ruta


def cmd_ffmpeg_base(ffmpeg):
    return [ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error"]


def medir_ffmpeg(args, modo):
    ffmpeg = resolver_ffmpeg(args)
    archivo = validar_archivo(args)
    info = dg.inspeccionar_ffmpeg(ffmpeg) or {}
    if "videotoolbox" not in info.get("hwaccels", []) or "h264_videotoolbox" not in info.get("codificadores_videotoolbox", []):
        raise ErrorUso("Este ffmpeg (%s) no trae VideoToolbox; usa otro con --ffmpeg." % ffmpeg)
    nombres = list(VAR_CODIFICAR) if modo == "codificar" else ["dec_cpu", "dec_hw"]
    planes = {}
    tmp = tempfile.mkdtemp(prefix="rendimiento-equipo-")
    try:
        for n in nombres:
            if modo == "codificar":
                v = VAR_CODIFICAR[n]
                salida = os.path.join(tmp, n + ".mp4")
                cmd = cmd_ffmpeg_base(ffmpeg) + v["entrada"] + ["-t", str(args.segundos), "-i", archivo, "-an", "-pix_fmt", "yuv420p"] + \
                    [x.replace("{b}", args.bitrate) for x in v["salida"]] + [salida]
            else:
                salida = None
                cmd = cmd_ffmpeg_base(ffmpeg) + (["-hwaccel", "videotoolbox"] if n == "dec_hw" else []) + \
                    ["-t", str(args.segundos), "-i", archivo, "-an", "-f", "null", "-"]
            planes[n] = {"cmd": cmd, "salida": salida}
        if args.solo_comandos:
            return {"solo_comandos": {n: p["cmd"] for n, p in planes.items()}}, None
        ctx_ruido = ruido()
        corridas = {n: [] for n in nombres}
        for _ in range(args.repeticiones):
            for n in nombres:  # intercalado
                if planes[n]["salida"] and os.path.exists(planes[n]["salida"]):
                    os.remove(planes[n]["salida"])
                corridas[n].append(correr(planes[n]["cmd"], timeout=900))
        res = {n: resumir(c) for n, c in corridas.items()}
        fallos = [n for n, r in res.items() if r.get("fallo")]
        tamanos, difs, comps = {}, {}, []
        if modo == "codificar":
            for n in nombres:
                if not res[n].get("fallo") and os.path.exists(planes[n]["salida"]):
                    tamanos[n] = round(os.path.getsize(planes[n]["salida"]) / 1e6, 2)
            t_mid = max(0.0, (min(args.segundos, duracion(ffmpeg, archivo) or args.segundos)) / 2)

            def frame_de(n):
                return fotograma(ffmpeg, planes[n]["salida"], t_mid) if not res[n].get("fallo") else b""
            f_x264, f_vtc, f_vth = frame_de("x264_cpu"), frame_de("vt_dec_cpu"), frame_de("vt_dec_hw")
            difs["vt_dec_cpu"] = diferencia(f_x264, f_vtc)
            difs["vt_dec_hw"] = diferencia(f_vtc, f_vth)
            comps.append(comparar(res, "x264_cpu", "vt_dec_cpu", difs["vt_dec_cpu"], args.criterio))
            comps.append(comparar(res, "vt_dec_cpu", "vt_dec_hw", difs["vt_dec_hw"], args.criterio))
            clave = {("ffmpeg", "codificacion"): comps[0], ("ffmpeg", "decodificacion"): comps[1]}
        else:
            t_mid = max(0.0, (min(args.segundos, duracion(ffmpeg, archivo) or args.segundos)) / 2)
            difs["dec_hw"] = diferencia(fotograma(ffmpeg, archivo, t_mid, False), fotograma(ffmpeg, archivo, t_mid, True))
            comps.append(comparar(res, "dec_cpu", "dec_hw", difs["dec_hw"], args.criterio))
            clave = {("ffmpeg", "decodificacion"): comps[0]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cambios = {}
    for k, c in clave.items():
        g = c["ganador"]
        if g is None:
            continue
        gano_cand = g == "candidato"
        nota = "%s (%s)" % (c["motivo"], "criterio " + args.criterio)
        if k[1] == "codificacion":
            cambios[k] = {"metodo": "h264_videotoolbox" if gano_cand else "libx264", "bitrate_final": args.bitrate,
                          "bitrate_vista_previa": pf.BITRATE_PREVIA, "estado": "gana", "fecha": hoy(), "nota": nota}
        else:
            cambios[k] = {"metodo": "videotoolbox" if gano_cand else "cpu", "estado": "gana", "fecha": hoy(), "nota": nota}
    ctx = {"ffmpeg": ffmpeg, "archivo": archivo, "segundos": args.segundos, "repeticiones": args.repeticiones,
           "criterio": args.criterio, "ruido": ctx_ruido}
    out = {"subcomando": modo, **ctx, "variantes": res, "tamanos_mb": tamanos, "dif_visual": difs, "comparaciones": comps}
    md = (filas_md(res, difs, tamanos), comps, ctx, cambios)
    return out, md if not fallos else None


def medir_ffmpeg_windows(args, modo):
    """Windows: la base en CPU frente a cada metodo por hardware que abre en este equipo.

    Mismo criterio que en macOS: gana el candidato al menos 15 % mejor y con diferencia visual
    media menor de 2/255; entre varios ganadores, el mejor en la metrica elegida.
    """
    ffmpeg = resolver_ffmpeg(args)
    archivo = validar_archivo(args)
    info = dg.inspeccionar_ffmpeg(ffmpeg) or {}
    pruebas = dg.probar_video(ffmpeg, info)
    base = cmd_ffmpeg_base(ffmpeg)
    entrada = ["-t", str(args.segundos), "-i", archivo, "-an"]
    tmp = tempfile.mkdtemp(prefix="rendimiento-equipo-")
    planes = {}
    if modo == "codificar":
        if not info.get("libx264"):
            raise ErrorUso("Este ffmpeg (%s) no trae libx264, que es la base de la comparacion; usa otro con --ffmpeg." % ffmpeg)
        cands = [c for c in dg.CODIFICADORES_WINDOWS if (pruebas["codificadores"].get(c) or {}).get("abre")]
        if not cands:
            raise ErrorUso("Ningun codificador por hardware abre en este equipo con este ffmpeg (%s). Probados: %s. "
                           "Revisa el controlador de la tarjeta grafica o usa otro ffmpeg con --ffmpeg."
                           % (ffmpeg, json.dumps(pruebas["codificadores"], ensure_ascii=False)))
        nombre_base = "x264_cpu"
        planes[nombre_base] = {"cmd": base + entrada + ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                                                        os.path.join(tmp, nombre_base + ".mp4")], "salida": os.path.join(tmp, nombre_base + ".mp4")}
        for c in cands:
            v = dg.CODIFICADORES_WINDOWS[c]
            salida = os.path.join(tmp, c + ".mp4")
            planes[c] = {"cmd": base + entrada + ["-pix_fmt", v["pix_fmt"], "-c:v", c, "-b:v", args.bitrate] + v["extra"] + [salida],
                         "salida": salida}
    else:
        cands = [a for a in dg.ACELERADORES_WINDOWS if (pruebas["decodificadores"].get(a) or {}).get("abre")]
        if not cands:
            raise ErrorUso("Ningun acelerador de decodificacion abre en este equipo con este ffmpeg (%s). Probados: %s."
                           % (ffmpeg, json.dumps(pruebas["decodificadores"], ensure_ascii=False)))
        nombre_base = "dec_cpu"
        planes[nombre_base] = {"cmd": base + entrada + ["-f", "null", "-"], "salida": None}
        for a in cands:
            planes["dec_" + a] = {"cmd": base + ["-hwaccel", a] + entrada + ["-f", "null", "-"], "salida": None}
    nombres = list(planes)
    try:
        if args.solo_comandos:
            return {"solo_comandos": {n: p["cmd"] for n, p in planes.items()}, "pruebas_hw": pruebas}, None
        ctx_ruido = ruido()
        corridas = {n: [] for n in nombres}
        for _ in range(args.repeticiones):
            for n in nombres:  # intercalado
                if planes[n]["salida"] and os.path.exists(planes[n]["salida"]):
                    os.remove(planes[n]["salida"])
                corridas[n].append(correr(planes[n]["cmd"], timeout=900))
        res = {n: resumir(c) for n, c in corridas.items()}
        fallos = [n for n, r in res.items() if r.get("fallo")]
        tamanos, difs, comps = {}, {}, []
        t_mid = max(0.0, (min(args.segundos, duracion(ffmpeg, archivo) or args.segundos)) / 2)
        if modo == "codificar":
            for n in nombres:
                if not res[n].get("fallo") and os.path.exists(planes[n]["salida"]):
                    tamanos[n] = round(os.path.getsize(planes[n]["salida"]) / 1e6, 2)
            f_base = fotograma(ffmpeg, planes[nombre_base]["salida"], t_mid) if not res[nombre_base].get("fallo") else b""
            for c in nombres[1:]:
                difs[c] = diferencia(f_base, fotograma(ffmpeg, planes[c]["salida"], t_mid) if not res[c].get("fallo") else b"")
        else:
            f_base = fotograma(ffmpeg, archivo, t_mid)
            for n in nombres[1:]:
                difs[n] = diferencia(f_base, fotograma(ffmpeg, archivo, t_mid, n[len("dec_"):]))
        for n in nombres[1:]:
            comps.append(comparar(res, nombre_base, n, difs[n], args.criterio))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    m = "real_s" if args.criterio == "tiempo" else "cpu_s"
    ganan = [c["candidato"] for c in comps if c["ganador"] == "candidato"]
    clave = ("ffmpeg", "codificacion" if modo == "codificar" else "decodificacion")
    cambios = {}
    nota = None
    if ganan:
        mejor = min(ganan, key=lambda n: res[n][m])
        metodo = mejor if modo == "codificar" else mejor[len("dec_"):]
        nota = next(c["motivo"] for c in comps if c["candidato"] == mejor)
    elif comps and all(c["ganador"] == "base" for c in comps):
        metodo = "libx264" if modo == "codificar" else "cpu"
        nota = "la CPU gano a todos los metodos por hardware"
    if nota:
        cambios[clave] = {"metodo": metodo, "estado": "gana", "fecha": hoy(), "nota": "%s (criterio %s)" % (nota, args.criterio)}
        if modo == "codificar":
            cambios[clave].update({"bitrate_final": args.bitrate, "bitrate_vista_previa": pf.BITRATE_PREVIA})
    ctx = {"ffmpeg": ffmpeg, "archivo": archivo, "segundos": args.segundos, "repeticiones": args.repeticiones,
           "criterio": args.criterio, "ruido": ctx_ruido}
    out = {"subcomando": modo, **ctx, "pruebas_hw": pruebas, "variantes": res, "tamanos_mb": tamanos,
           "dif_visual": difs, "comparaciones": comps}
    md = (filas_md(res, difs, tamanos), comps, ctx, cambios)
    return out, md if not fallos else None


def medir_paralelo(args):
    """Cuantas codificaciones por hardware rinden a la vez.

    Los chips Max y Ultra traen 2 y 4 motores de codificacion de video, pero ninguna API dice cuantos hay:
    se mide. La misma codificacion corre con 1, 2 y 4 copias a la vez y se compara cuantos segundos de video
    salen por segundo real. Se adopta el mayor numero de copias que rinde al menos 15 % mas que el anterior.
    """
    ffmpeg = resolver_ffmpeg(args)
    archivo = validar_archivo(args)
    info = dg.inspeccionar_ffmpeg(ffmpeg) or {}
    if dg.es_windows():
        pruebas = dg.probar_video(ffmpeg, info)
        cod = next((c for c in dg.CODIFICADORES_WINDOWS if (pruebas["codificadores"].get(c) or {}).get("abre")), None)
        if not cod:
            raise ErrorUso("Ningun codificador por hardware abre en este equipo con este ffmpeg (%s)." % ffmpeg)
        v = dg.CODIFICADORES_WINDOWS[cod]
        entrada, salida = [], ["-pix_fmt", v["pix_fmt"], "-c:v", cod, "-b:v", args.bitrate] + v["extra"]
    else:
        if "h264_videotoolbox" not in info.get("codificadores_videotoolbox", []):
            raise ErrorUso("Este ffmpeg (%s) no trae h264_videotoolbox; usa otro con --ffmpeg." % ffmpeg)
        cod = "h264_videotoolbox"
        entrada = ["-hwaccel", "videotoolbox"] if "videotoolbox" in info.get("hwaccels", []) else []
        salida = ["-c:v", cod, "-b:v", args.bitrate, "-allow_sw", "0"]
    try:
        niveles = sorted({int(x) for x in args.niveles.split(",") if x.strip()})
    except ValueError:
        raise ErrorUso("--niveles debe ser una lista de enteros, por ejemplo 1,2,4")
    if not niveles or niveles[0] != 1 or niveles[-1] > 16:
        raise ErrorUso("--niveles debe empezar en 1 y no pasar de 16, por ejemplo 1,2,4")
    tmp = tempfile.mkdtemp(prefix="rendimiento-equipo-")

    def comando(i):
        return cmd_ffmpeg_base(ffmpeg) + entrada + ["-t", str(args.segundos), "-i", archivo, "-an"] + salida + \
            [os.path.join(tmp, "copia%d.mp4" % i)]
    try:
        if args.solo_comandos:
            return {"solo_comandos": {str(n): [comando(i) for i in range(n)] for n in niveles}}, None
        ctx_ruido = ruido()
        corridas = {n: [] for n in niveles}
        for _ in range(args.repeticiones):
            for n in niveles:  # intercalado
                corridas[n].append(correr_varios([comando(i) for i in range(n)], timeout=1800))
        res = {n: resumir(c) for n, c in corridas.items()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    seg = min(args.segundos, duracion(ffmpeg, archivo) or args.segundos)
    ritmo = {n: round(n * seg / res[n]["real_s"], 2) for n in niveles if not res[n].get("fallo") and res[n]["real_s"]}
    escalado = {n: round(r / ritmo[1], 2) for n, r in ritmo.items()} if 1 in ritmo else {}
    cambios, comps, elegido = {}, [], None
    if 1 in ritmo:
        elegido = 1
        for n in niveles[1:]:
            mejora = ritmo[n] / ritmo[elegido] - 1 if n in ritmo else None
            gana = mejora is not None and mejora >= UMBRAL_MEJORA
            comps.append({"base": "%d a la vez" % elegido, "candidato": "%d a la vez" % n, "ganador": "candidato" if gana else None,
                          "motivo": ("falló" if mejora is None else "rinde %.0f %% más" % (mejora * 100) if gana else
                                     "rinde %.0f %% menos" % (-mejora * 100) if mejora < 0 else
                                     "rinde %.0f %% más: no llega al 15 %%" % (mejora * 100))})
            if not gana:
                break
            elegido = n
        if seg >= 5:  # con clips cortos el arranque de ffmpeg pesa y las copias a la vez parecen rendir mas de lo que rinden
            cambios[("video", "codificaciones_paralelas")] = {
                "valor": elegido, "codificador": cod, "escalado": {str(n): e for n, e in escalado.items()},
                "estado": "gana", "fecha": hoy(),
                "nota": "mayor numero de codificaciones a la vez que rinde al menos 15 % mas que el anterior"}
        else:
            comps.append({"base": "registro", "candidato": "perfil", "ganador": None,
                          "motivo": "menos de 5 s por copia: el arranque de ffmpeg exagera el resultado, no se registra"})
    filas = []
    for n in niveles:
        r = res[n]
        filas.append("| %d a la vez | %s | %s | | %s |" % (n, "falló" if r.get("fallo") else r["real_s"],
                                                         "" if r.get("fallo") else r["cpu_s"],
                                                         ("rinde %s×" % num_es(escalado[n])) if n in escalado else ""))
    ctx = {"ffmpeg": ffmpeg, "archivo": archivo, "segundos": args.segundos, "repeticiones": args.repeticiones,
           "criterio": "tiempo", "ruido": ctx_ruido}
    out = {"subcomando": "paralelo", **ctx, "codificador": cod, "variantes": {str(n): r for n, r in res.items()},
           "segundos_de_video_por_segundo": {str(n): r for n, r in ritmo.items()},
           "escalado": {str(n): e for n, e in escalado.items()}, "elegido": elegido, "comparaciones": comps}
    fallos = [n for n, r in res.items() if r.get("fallo")]
    return out, ((filas, comps, ctx, cambios) if not fallos else None)


UNIDADES = ("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciseis diecisiete "
            "dieciocho diecinueve veinte veintiuno veintidos veintitres veinticuatro veinticinco veintiseis veintisiete "
            "veintiocho veintinueve").split()
DECENAS = {30: "treinta", 40: "cuarenta", 50: "cincuenta", 60: "sesenta", 70: "setenta", 80: "ochenta", 90: "noventa"}
CENTENAS = {100: "ciento", 200: "doscientos", 300: "trescientos", 400: "cuatrocientos", 500: "quinientos", 600: "seiscientos",
            700: "setecientos", 800: "ochocientos", 900: "novecientos"}


def _numero_es(n):
    """Cifra a palabras en espanol, sin tildes (de 0 a 999.999). Asi «12 %» y «doce por ciento» cuentan igual."""
    if n < 30:
        return UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return DECENAS[d * 10] + ("" if not u else " y " + UNIDADES[u])
    if n == 100:
        return "cien"
    if n < 1000:
        c, r = divmod(n, 100)
        return CENTENAS[c * 100] + ("" if not r else " " + _numero_es(r))
    m, r = divmod(n, 1000)
    return ("mil" if m == 1 else _numero_es(m) + " mil") + ("" if not r else " " + _numero_es(r))


def _normalizar(t):
    """Minusculas, sin tildes ni puntuacion, cifras en palabras y «%» como «por ciento»."""
    import unicodedata
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.replace("%", " por ciento ")
    t = re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", t)
    t = re.sub(r"\d+", lambda m: " %s " % _numero_es(int(m.group())) if int(m.group()) < 10 ** 6 else m.group(), t)
    return re.findall(r"[a-z0-9]+", t)


def wer(referencia, hipotesis):
    """Porcentaje de palabras erradas (sustituciones + borradas + agregadas) / palabras de la referencia."""
    a, b = _normalizar(referencia), _normalizar(hipotesis)
    if not a:
        return None
    previo = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        actual = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            actual[j] = min(previo[j] + 1, actual[j - 1] + 1, previo[j - 1] + (x != y))
        previo = actual
    return round(100 * previo[-1] / len(a), 2)


def _memoria_mb(p):
    """Memoria residente actual del proceso en MB (ps en macOS; en Windows se lee el pico al final)."""
    if resource is None:
        return None
    rc, out, _ = dg.ejecutar(["ps", "-o", "rss=", "-p", str(p.pid)], 5)
    try:
        return int(out.strip()) / 1024 if rc == 0 else None
    except ValueError:
        return None


def _post_audio(puerto, wav, idioma, timeout):
    """whisper-server: POST /inference multipart con el WAV de 16 kHz."""
    import urllib.request
    limite = "----rendimientoequipo%d" % os.getpid()
    with open(wav, "rb") as f:
        datos = f.read()
    cuerpo = b"".join([
        ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.wav\"\r\nContent-Type: audio/wav\r\n\r\n" % limite).encode(),
        datos, b"\r\n",
        ("--%s\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson\r\n" % limite).encode(),
        ("--%s\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n%s\r\n" % (limite, idioma)).encode(),
        ("--%s--\r\n" % limite).encode()])
    req = urllib.request.Request("http://127.0.0.1:%d/inference" % puerto, data=cuerpo,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + limite})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        # los segmentos llegan en lineas y a veces cortan una palabra: el salto no es un espacio
        return json.loads(r.read().decode("utf-8", "replace")).get("text", "").replace("\n", "")


def _ws_offline(puerto, pcm_f32, timeout):
    """sherpa-onnx-ws, protocolo offline que usa OpenWhispr: [int32 tasa][int32 bytes][float32...], luego «Done».

    Cliente WebSocket minimo con la biblioteca estandar (texto y binario, sin extensiones).
    """
    import base64
    import socket
    s = socket.create_connection(("127.0.0.1", puerto), timeout=timeout)
    try:
        clave = base64.b64encode(os.urandom(16)).decode()
        s.sendall(("GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (puerto, clave)).encode())
        cab = b""
        while b"\r\n\r\n" not in cab:
            trozo = s.recv(4096)
            if not trozo:
                raise OSError("el servidor cerro durante el saludo WebSocket")
            cab += trozo
        if b" 101 " not in cab.split(b"\r\n", 1)[0]:
            raise OSError("saludo WebSocket rechazado: %r" % cab[:80])
        resto = cab.split(b"\r\n\r\n", 1)[1]

        def enviar(op, datos):
            mascara = os.urandom(4)
            n = len(datos)
            cab = bytes([0x80 | op]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n)
                                         if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
            s.sendall(cab + mascara + bytes(b ^ mascara[i % 4] for i, b in enumerate(datos)))

        buf = [resto]

        def leer(n):
            while len(buf[0]) < n:
                trozo = s.recv(65536)
                if not trozo:
                    raise OSError("el servidor cerro la conexion")
                buf[0] += trozo
            out, buf[0] = buf[0][:n], buf[0][n:]
            return out

        def recibir():
            b1, b2 = leer(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", leer(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", leer(8))[0]
            if b2 & 0x80:
                leer(4)
            return b1 & 0x0F, leer(n)

        enviar(2, struct.pack("<ii", 16000, len(pcm_f32)) + pcm_f32)
        texto = ""
        while True:
            op, datos = recibir()
            if op == 8:
                break
            if op == 1:
                msg = datos.decode("utf-8", "replace")
                if msg == "Done!":
                    break
                try:
                    texto = json.loads(msg).get("text", msg)
                except ValueError:
                    texto = msg
                enviar(1, b"Done")
        return texto
    finally:
        s.close()


def _sherpa(cat_m, carpeta, servidor, puerto, idioma):
    """Argumentos de sherpa-onnx-ws como los arma OpenWhispr (parakeetWsServer.js), o None si faltan archivos."""
    hilos = min(4, max(1, int((os.cpu_count() or 4) * 0.75)))
    f = lambda n: os.path.join(carpeta, n)  # noqa: E731
    if os.path.isfile(f("encoder.int8.onnx")) and os.path.isfile(f("joiner.int8.onnx")):
        args = ["--encoder=" + f("encoder.int8.onnx"), "--decoder=" + f("decoder.int8.onnx"), "--joiner=" + f("joiner.int8.onnx"),
                "--tokens=" + f("tokens.txt")] + (["--model-type=" + cat_m["sherpa_tipo"]] if cat_m.get("sherpa_tipo") else [])
    elif cat_m.get("tipo_modelo") == "cohere-transcribe" and os.path.isfile(f("encoder.int8.onnx")):
        args = ["--cohere-transcribe-encoder=" + f("encoder.int8.onnx"), "--cohere-transcribe-decoder=" + f("decoder.int8.onnx"),
                "--cohere-transcribe-language=" + idioma, "--tokens=" + f("tokens.txt")]
    else:
        return None
    return [servidor] + args + ["--port=%s" % puerto, "--num-threads=%d" % hilos, "--num-work-threads=3"], hilos


def medir_voz(args):
    """Transcribe el mismo audio con cada modelo de dictado de OpenWhispr descargado, en servidores propios.

    Whisper (whisper.cpp): con Metal y, si se pide, en CPU (-ng) para compararlos. Parakeet, Orukeet y Cohere
    (sherpa-onnx): con los mismos argumentos que OpenWhispr. Cada servidor es propio, en un puerto 88xx, y se
    apaga al terminar; nunca se toca el de OpenWhispr. Una peticion de calentamiento y luego --repeticiones
    medidas: tiempo medio, memoria pico y, con --texto, porcentaje de palabras erradas. Del registro de
    whisper-server se lee si la compilacion usa la API de tensores (los Neural Accelerators de M5 en adelante).
    """
    import hashlib
    import socket
    import threading
    import voz
    audio = os.path.expanduser(args.audio)
    if not os.path.isfile(audio):
        raise ErrorUso("No existe el audio: %r" % audio)
    referencia = None
    if args.texto:
        ruta = os.path.expanduser(args.texto)
        referencia = open(ruta, encoding="utf-8").read() if os.path.isfile(ruta) else args.texto
    cat, version, ruta_asar = voz.catalogo_openwhispr()
    if not cat:
        raise ErrorUso("No encuentro OpenWhispr instalado: sus modelos son los que se miden.")
    bin_ow = os.path.join(os.path.dirname(ruta_asar), "bin")
    whisper_bin = next(iter(sorted(glob_bin(bin_ow, "whisper-server"))), None) or \
        next((s["ruta"] for s in (dg.buscar_whisper() or {}).get("servidores") or []), None)
    sherpa_bin = next(iter(sorted(glob_bin(bin_ow, "sherpa-onnx-ws"))), None)
    todos = [m for m in voz.modelos(cat) if m["ruta"] and not m["streaming"]]
    pedidos = [x.strip() for x in (args.modelos or "").split(",") if x.strip()]
    elegidos = [m for m in todos if not pedidos or m["id"] in pedidos]
    if not elegidos:
        raise ErrorUso("No hay modelos de dictado de OpenWhispr descargados%s. Instalados: %s" % (
            " con esos nombres" if pedidos else "", ", ".join(m["id"] for m in todos) or "ninguno"))
    backends = [b.strip() for b in args.backends.split(",") if b.strip()] if args.backends else \
        (["metal"] if dg.es_macos() and dg.platform.machine() == "arm64" else ["cpu"])
    ffmpeg = resolver_ffmpeg(args)
    tmp = tempfile.mkdtemp(prefix="rendimiento-equipo-")
    wav, f32 = os.path.join(tmp, "audio.wav"), os.path.join(tmp, "audio.f32")
    for salida, fmt in ((wav, ["-c:a", "pcm_s16le"]), (f32, ["-f", "f32le"])):
        rc, _, err = dg.ejecutar([ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-i", audio,
                                  "-ar", "16000", "-ac", "1"] + fmt + [salida], 300)
        if rc != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise ErrorUso("ffmpeg no pudo convertir el audio: %s" % err.strip()[-200:])
    seg = duracion(ffmpeg, wav) or 0
    with open(wav, "rb") as fh:
        audio_id = hashlib.sha1(fh.read()).hexdigest()[:12]
    with open(f32, "rb") as fh:
        pcm = fh.read()
    planes = []
    for m in elegidos:
        if m["familia"] == "whisper":
            if not whisper_bin:
                continue
            for b in backends:
                planes.append((m, b, [whisper_bin, "-m", m["ruta"], "--port", "{p}", "-l", args.idioma] + (["-ng"] if b == "cpu" else []), None))
        elif sherpa_bin:
            arm = _sherpa(m, m["ruta"], sherpa_bin, "{p}", args.idioma)
            planes.append((m, "cpu", arm[0] if arm else None, arm[1] if arm else None))
    if args.solo_comandos:
        shutil.rmtree(tmp, ignore_errors=True)
        return {"solo_comandos": [[m["id"], b, c] for m, b, c, _ in planes]}, None
    ctx_ruido = ruido()
    res, tensor = {}, None
    try:
        for m, backend, cmd, hilos in planes:
            clave = m["id"] if len(backends) == 1 or m["familia"] != "whisper" else "%s@%s" % (m["id"], backend)
            if cmd is None:
                res[clave] = {"fallo": True, "error": "faltan archivos del modelo en %s" % m["ruta"]}
                continue
            puerto = pf.puerto_libre(set())
            cmd = [x.replace("{p}", str(puerto)) for x in cmd]
            registro = os.path.join(tmp, "servidor-%s.log" % len(res))
            with open(registro, "w") as fl:
                t0 = time.perf_counter()
                p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fl, stderr=subprocess.STDOUT)
            listo = False
            while time.perf_counter() - t0 < 300 and p.poll() is None:
                try:
                    socket.create_connection(("127.0.0.1", puerto), timeout=0.5).close()
                    listo = True
                    break
                except OSError:
                    time.sleep(0.2)
            carga = time.perf_counter() - t0
            pico, corriendo = [0.0], [True]

            def vigilar():
                while corriendo[0]:
                    v = _memoria_mb(p)
                    if v:
                        pico[0] = max(pico[0], v)
                    time.sleep(0.2)
            hilo = threading.Thread(target=vigilar, daemon=True)
            hilo.start()
            tiempos, texto, error = [], "", None
            try:
                if not listo:
                    raise OSError("el servidor no arranco en 300 s")
                for i in range(args.repeticiones + 1):  # la primera calienta y no cuenta
                    t1 = time.perf_counter()
                    texto = _ws_offline(puerto, pcm, 1800) if m["familia"] != "whisper" else _post_audio(puerto, wav, args.idioma, 1800)
                    if i:
                        tiempos.append(time.perf_counter() - t1)
            except Exception as e:  # noqa: BLE001 - un modelo que falla no tumba la medicion de los demas
                error = "%s: %s" % (type(e).__name__, e)
            corriendo[0] = False
            hilo.join(1)
            if resource is None:
                import plataforma_windows as pw
                pico[0] = pw.memoria_pico_mb(p) or 0
            p.terminate()
            try:
                p.wait(15)
            except subprocess.TimeoutExpired:
                p.kill()
            if m["familia"] == "whisper":
                with open(registro, encoding="utf-8", errors="replace") as fl:
                    t = re.search(r"has tensor\s*=\s*(true|false)", fl.read())
                if t:
                    tensor = t.group(1) == "true" if tensor is None else (tensor or t.group(1) == "true")
            if error:
                res[clave] = {"fallo": True, "error": error}
                continue
            dur = statistics.mean(tiempos)
            res[clave] = {"modelo": m["id"], "motor": m["motor"], "backend": backend, "hilos": hilos, "carga_s": round(carga, 2),
                          "transcribe_s": round(dur, 2), "veces_tiempo_real": round(seg / dur, 1) if dur else None,
                          "memoria_mb": round(pico[0]) or None, "wer": wer(referencia, texto) if referencia else None,
                          "texto": texto.strip()[:600]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cambios, comps = {}, []
    # Metal frente a CPU en el mismo modelo Whisper: ganador claro con el criterio de siempre (>=15 %)
    for mid in {r["modelo"] for r in res.values() if not r.get("fallo") and r["motor"] == "whisper.cpp"}:
        a, b = res.get(mid + "@cpu"), res.get(mid + "@metal")
        if a and b and not a.get("fallo") and not b.get("fallo"):
            mejora = 1 - b["transcribe_s"] / a["transcribe_s"]
            gana = "metal" if mejora >= UMBRAL_MEJORA else "cpu" if (1 - a["transcribe_s"] / b["transcribe_s"]) >= UMBRAL_MEJORA else None
            comps.append({"base": mid + " en CPU", "candidato": mid + " con Metal", "ganador": gana,
                          "motivo": "Metal %.1f veces mas rapido" % (a["transcribe_s"] / b["transcribe_s"])})
            if gana:
                cambios[("whisper", "backend")] = {"valor": gana, "estado": "gana", "fecha": hoy(),
                                                   "nota": "%s: Metal %s s frente a CPU %s s" % (mid, b["transcribe_s"], a["transcribe_s"])}
    for clave, r in res.items():
        if r.get("fallo"):
            continue
        actual = cambios.get(("voz", r["modelo"]))
        if actual and r["backend"] == "cpu" and r["motor"] == "whisper.cpp":
            continue  # se guarda el backend rapido de cada Whisper
        cambios[("voz", r["modelo"])] = {k: r[k] for k in ("backend", "hilos", "carga_s", "transcribe_s", "veces_tiempo_real", "memoria_mb", "wer")}
        cambios[("voz", r["modelo"])].update({"idioma": args.idioma, "audio_s": round(seg, 1), "audio_id": audio_id,
                                              "audio_sintetico": bool(args.audio_sintetico),
                                              "estado": "adoptado", "fecha": hoy(), "nota": "medido con medir.py voz"})
    if tensor is not None:
        cambios[("whisper", "api_tensores")] = {"valor": tensor, "estado": "adoptado", "fecha": hoy(),
                                                "nota": "registro de whisper-server de OpenWhispr %s: has tensor = %s" % (version, str(tensor).lower())}
    filas = ["| %s | %s | %s | %s MB | %s |" % (k, "falló" if r.get("fallo") else r["transcribe_s"],
                                               "" if r.get("fallo") else "%sx tiempo real" % r["veces_tiempo_real"],
                                               "" if r.get("fallo") else r["memoria_mb"],
                                               "" if r.get("fallo") or r["wer"] is None else "%s %% de error" % r["wer"])
             for k, r in res.items()]
    ctx = {"audio": audio, "audio_s": round(seg, 1), "audio_id": audio_id, "idioma": args.idioma, "openwhispr": version,
           "repeticiones": args.repeticiones, "criterio": "tiempo", "ruido": ctx_ruido, "archivo": audio,
           "api_tensores": tensor}
    out = {"subcomando": "voz", **ctx, "variantes": res, "comparaciones": comps}
    return out, (filas, comps, ctx, cambios)


def glob_bin(carpeta, prefijo):
    """Binarios de OpenWhispr que empiezan por un prefijo (whisper-server-darwin-arm64, sherpa-onnx-ws-win32-x64.exe...)."""
    import glob
    return [p for p in glob.glob(os.path.join(carpeta, prefijo + "*")) if os.path.isfile(p) and "online" not in os.path.basename(p)]


def num_es(x):
    return ("%.2f" % x).replace(".", ",")


def medir_remotion(args):
    proyecto = os.path.expanduser(args.proyecto)
    if not os.path.isdir(proyecto):
        raise ErrorUso("No existe el proyecto: %r" % proyecto)
    cli = os.path.join(proyecto, "node_modules", ".bin", "remotion")
    base_cmd = [cli] if os.path.exists(cli) else ["npx", "remotion"]
    if not re.fullmatch(r"\d+-\d+", args.fotogramas):
        raise ErrorUso("--fotogramas debe verse como 0-149")
    ffmpeg = resolver_ffmpeg(args)
    conc = args.concurrencia or pf.concurrencia_remotion(pf.nucleos_para_render(dg.leer_cpu())[0], 1)
    nombres = [v.strip() for v in args.variantes.split(",") if v.strip()]
    for v in nombres:
        if v not in VAR_REMOTION:
            raise ErrorUso("Variante desconocida %r. Opciones: %s" % (v, ", ".join(VAR_REMOTION)))
    if "base" not in nombres:
        nombres.insert(0, "base")
    tmp = tempfile.mkdtemp(prefix="rendimiento-equipo-")
    planes = {}
    for n in nombres:
        salida = os.path.join(tmp, n + ".mp4")
        flags = [f.replace("{b}", args.bitrate) for f in VAR_REMOTION[n]]
        planes[n] = {"cwd": proyecto, "salida": salida, "cmd": base_cmd + [
            "render", args.entrada, args.composicion, salida, "--frames=%s" % args.fotogramas,
            "--concurrency=%d" % conc, "--log=error", "--overwrite"] + flags}
    try:
        if args.solo_comandos:
            return {"solo_comandos": {n: p["cmd"] for n, p in planes.items()}, "cwd": proyecto}, None
        ctx_ruido = ruido()
        corridas = {n: [] for n in nombres}
        for _ in range(args.repeticiones):
            for n in nombres:
                corridas[n].append(correr(planes[n]["cmd"], cwd=proyecto, timeout=1800))
        res = {n: resumir(c) for n, c in corridas.items()}
        fallos = [n for n, r in res.items() if r.get("fallo")]
        tamanos, difs, comps = {}, {}, []
        base_f = b""
        if not res["base"].get("fallo"):
            d = duracion(ffmpeg, planes["base"]["salida"]) or 1.0
            t_mid = d / 2
            base_f = fotograma(ffmpeg, planes["base"]["salida"], t_mid)
        for n in nombres:
            if not res[n].get("fallo") and os.path.exists(planes[n]["salida"]):
                tamanos[n] = round(os.path.getsize(planes[n]["salida"]) / 1e6, 2)
                if n != "base":
                    difs[n] = diferencia(base_f, fotograma(ffmpeg, planes[n]["salida"], t_mid))
        for n in nombres:
            if n != "base":
                comps.append(comparar(res, "base", n, difs.get(n), args.criterio))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cambios = {}
    by = {c["candidato"]: c for c in comps}
    if "hardware" in by and by["hardware"]["ganador"]:
        c = by["hardware"]
        si = c["ganador"] == "candidato"
        cambios[("remotion", "hardware_acceleration")] = {
            "valor": "required" if si else "disable", "video_bitrate": args.bitrate, "estado": "gana" if args.criterio == "tiempo" else "adoptado",
            "fecha": hoy(), "nota": "%s (criterio %s)" % (c["motivo"], args.criterio)}
    if "angle" in by and by["angle"]["ganador"]:
        c = by["angle"]
        si = c["ganador"] == "candidato"
        cambios[("remotion", "gl")] = {"valor": "angle" if si else None, "estado": "gana" if args.criterio == "tiempo" else "adoptado",
                                       "fecha": hoy(), "nota": "%s (criterio %s)" % (c["motivo"], args.criterio)}
    ctx = {"proyecto": proyecto, "composicion": args.composicion, "fotogramas": args.fotogramas, "concurrencia": conc,
           "repeticiones": args.repeticiones, "criterio": args.criterio, "ruido": ctx_ruido}
    out = {"subcomando": "remotion", **ctx, "variantes": res, "tamanos_mb": tamanos, "dif_visual": difs, "comparaciones": comps}
    return out, ((filas_md(res, difs, tamanos), comps, ctx, cambios) if not fallos else None)


def _contar(procesos):
    c = {}
    for p in procesos:
        c[p["tipo"]] = c.get(p["tipo"], 0) + 1
    return c


def registrar(out, md, huella, titulo, aceptar_ruido):
    filas, comps, ctx, cambios = md
    reg = {"mediciones_md": None, "perfil_medido": {"actualizado": False}}
    ruido_ok = not ctx["ruido"]["hay_ruido"] or aceptar_ruido
    if cambios and ruido_ok:
        decision = "perfil actualizado: " + ", ".join("%s.%s" % k for k in cambios)
    elif cambios:
        decision = "ganador claro, pero había otros procesos pesados (ruido): el perfil NO se actualizó. Repite sin ruido o usa --aceptar-ruido."
    else:
        decision = "sin ganador claro: el perfil no cambia."
    resumen_ctx = "Equipo `%s` · %s · repeticiones %s · criterio %s · ruido: %s" % (
        huella, ctx.get("archivo") or ctx.get("proyecto"), ctx["repeticiones"], ctx["criterio"],
        ("sí (%s)" % ", ".join("%d %s" % (n, t) for t, n in sorted(_contar(ctx["ruido"]["procesos"]).items()))) if ctx["ruido"]["hay_ruido"] else "no")
    reg["mediciones_md"] = escribir_md(huella, titulo, resumen_ctx, filas, comps, decision)
    if cambios and ruido_ok:
        reg["perfil_medido"] = {"actualizado": True, "ruta": actualizar_perfil(huella, cambios),
                                "cambios": {"%s.%s" % k: v for k, v in cambios.items()}}
    else:
        reg["perfil_medido"]["motivo"] = decision
    out["registro"] = reg


def parser():
    ap = argparse.ArgumentParser(
        description="Pruebas cortas A/B (codificar, decodificar, remotion, paralelo) con tiempo real, CPU y diferencia visual.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("Con --registrar:")[1].join(["Con --registrar:", ""]))
    sub = ap.add_subparsers(dest="cmd", metavar="{codificar,decodificar,remotion,paralelo,voz}")

    def comunes(p):
        p.add_argument("--repeticiones", type=int, default=None, help="repeticiones por variante (por defecto 1 en ffmpeg, 2 en paralelo, 3 en remotion y voz)")
        p.add_argument("--criterio", choices=("tiempo", "cpu"), default="tiempo", help="metrica para elegir ganador (por defecto tiempo real)")
        p.add_argument("--bitrate", default=BITRATE, help="bitrate de los codificadores por hardware (por defecto %(default)s)")
        p.add_argument("--ffmpeg", help="ruta de ffmpeg (por defecto el mejor encontrado por diagnosticar.py)")
        p.add_argument("--registrar", action="store_true", help="agrega el resultado a mediciones.md y actualiza perfil-medido.json si hay ganador claro")
        p.add_argument("--aceptar-ruido", action="store_true", help="permite actualizar el perfil aunque haya otros procesos pesados")
        p.add_argument("--solo-comandos", action="store_true", help="muestra los comandos que correria y termina, sin ejecutar nada")

    for nombre, ayuda in (("codificar", "libx264 frente al codificador por hardware (VideoToolbox; en Windows NVENC, QSV, AMF o Media Foundation)"),
                          ("decodificar", "decodificar en CPU frente a la decodificacion por hardware (VideoToolbox; en Windows cuda, qsv o d3d11va)")):
        p = sub.add_parser(nombre, help=ayuda, description=ayuda)
        p.add_argument("--archivo", required=True, help="video de prueba")
        p.add_argument("--segundos", type=float, default=5 if nombre == "codificar" else 30, help="segundos a procesar (por defecto %(default)s)")
        comunes(p)
    p = sub.add_parser("remotion", help="render corto de una composicion con variantes base, angle, hardware y ambos",
                       description="Render corto de una composicion. NO lo corras mientras otros agentes renderizan: el ruido invalida la medicion.")
    p.add_argument("--proyecto", required=True, help="carpeta del proyecto Remotion")
    p.add_argument("--composicion", required=True, help="id de la composicion")
    p.add_argument("--fotogramas", default="0-149", help="rango de fotogramas (por defecto %(default)s)")
    p.add_argument("--entrada", default="src/index.ts", help="punto de entrada (por defecto %(default)s)")
    p.add_argument("--variantes", default="base,angle,hardware,ambos", help="lista separada por comas (por defecto %(default)s)")
    p.add_argument("--concurrencia", type=int, help="--concurrency igual para todas las variantes (por defecto la formula con 1 render)")
    comunes(p)
    p = sub.add_parser("voz", help="modelos de dictado de OpenWhispr instalados: tiempo, memoria y error",
                       description="Transcribe el mismo audio con cada modelo de dictado de OpenWhispr instalado (Whisper, Parakeet, "
                                   "Orukeet, Cohere), en servidores propios. Una pasada de calentamiento y luego --repeticiones (3).")
    p.add_argument("--audio", required=True, help="audio de prueba (mejor 30 a 120 s de tu voz)")
    p.add_argument("--texto", help="lo que dice el audio (archivo .txt o el texto mismo): con esto se calcula el error")
    p.add_argument("--idioma", default="es", help="idioma del audio (por defecto %(default)s)")
    p.add_argument("--modelos", help="ids separados por coma (por defecto todos los instalados)")
    p.add_argument("--audio-sintetico", action="store_true", help="el audio es voz sintetica (calibrar.py): tu voz real tendra prioridad")
    p.add_argument("--backends", help="en Whisper: metal, cpu o metal,cpu para compararlos (por defecto metal en Apple Silicon, cpu en lo demas)")
    comunes(p)
    p = sub.add_parser("paralelo", help="cuantas codificaciones por hardware rinden a la vez (1, 2, 4...)",
                       description="La misma codificacion con 1, 2, 4... copias a la vez. NO lo corras con otros renders en marcha.")
    p.add_argument("--archivo", required=True, help="video de prueba")
    p.add_argument("--segundos", type=float, default=10, help="segundos a codificar en cada copia (por defecto %(default)s)")
    p.add_argument("--niveles", default="1,2,4", help="copias a la vez que se prueban, empezando en 1 (por defecto %(default)s)")
    comunes(p)
    return ap


def main(argv=None):
    ap = parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help(sys.stderr)
        return 2
    if args.repeticiones is None:
        args.repeticiones = {"remotion": 3, "paralelo": 2, "voz": 3}.get(args.cmd, 1)
    if args.repeticiones < 1:
        print("error: --repeticiones debe ser 1 o mas", file=sys.stderr)
        return 2
    if not (dg.es_macos() or dg.es_windows()):
        print("error: medir.py solo tiene pruebas para macOS y Windows (%s en este sistema). Lee references/windows.md." % dg.SOPORTE_SIN_MEDIR, file=sys.stderr)
        return 2
    if dg.es_windows() and args.cmd == "remotion":
        print("error: en Windows, medir.py todavia no mide Remotion: solo codificar y decodificar. Lee references/windows.md.", file=sys.stderr)
        return 2
    try:
        if args.cmd == "remotion":
            out, md = medir_remotion(args)
        elif args.cmd == "voz":
            out, md = medir_voz(args)
        elif args.cmd == "paralelo":
            out, md = medir_paralelo(args)
        elif dg.es_windows():
            out, md = medir_ffmpeg_windows(args, args.cmd)
        else:
            out, md = medir_ffmpeg(args, args.cmd)
    except ErrorUso as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    if "solo_comandos" in out:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    huella = dg.calcular_huella(dg.platform.machine(), dg.leer_cpu(), dg.memoria_total())
    out["huella"] = huella
    out["fecha"] = datetime.now().astimezone().isoformat(timespec="seconds")
    if args.registrar:
        if md is None:
            out["registro"] = {"mediciones_md": None, "perfil_medido": {"actualizado": False, "motivo": "una variante fallo: no se registra"}}
        else:
            titulo = "%s · %s" % (args.cmd, os.path.basename(out.get("archivo") or out.get("composicion") or ""))
            registrar(out, md, huella, titulo, args.aceptar_ruido)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    fallidas = [n for n, r in out["variantes"].items() if r.get("fallo")]
    for n in fallidas:
        v = out["variantes"][n]
        ultimo = ((v.get("corridas") or [{}])[-1].get("error") or v.get("error") or "sin detalle")
        print("error: la variante %s fallo: %s" % (n, ultimo[-300:]), file=sys.stderr)
    if out.get("ruido", {}).get("hay_ruido"):
        print("aviso: habia otros procesos pesados en marcha; la medicion tiene ruido.", file=sys.stderr)
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
