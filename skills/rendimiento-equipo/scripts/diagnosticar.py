#!/usr/bin/env python3
"""Diagnostica el equipo donde corre y devuelve un JSON por stdout.

Consulta el hardware en tiempo de ejecucion (sysctl, memory_pressure, system_profiler y
un script de Swift con Metal, VideoToolbox y CoreML). No fija valores a mano, no usa red y
no instala nada. Solo biblioteca estandar de Python 3.

Uso tipico:
    python3 diagnosticar.py
    python3 diagnosticar.py --proyecto "$HOME/proyectos/mi-video-remotion"

Lo unico que escribe es una muestra pequena de swap en
~/.local/share/rendimiento-equipo/<huella>/estado-memoria.json, para poder decir si el swap
esta creciendo entre dos diagnosticos. Se desactiva con --sin-estado.

Codigos de salida: 0 = diagnostico entregado (aunque algunas partes falten, ver "avisos");
2 = argumentos invalidos.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

sys.dont_write_bytecode = True
ESQUEMA = 1
AQUI = os.path.dirname(os.path.abspath(__file__))
SWIFT_ARCHIVO = os.path.join(AQUI, "capacidades_macos.swift")
SWIFT_TIEMPO_LIMITE = 90
UMBRAL_SWAP_CRECE_MB = 256  # criterio, no medicion: crecimiento que se considera "creciendo"
VENTANA_SWAP_S = 3600
SOPORTE_SIN_MEDIR = "sin soporte medido todavía"

RUTAS_FFMPEG = [
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/local/bin/ffmpeg",
    "/Applications/OpenWhispr.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-static/ffmpeg",
    os.path.expanduser("~/Applications/OpenWhispr.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-static/ffmpeg"),
]
RUTAS_WHISPER_SERVER = [
    "/opt/homebrew/bin/whisper-server",
    "/usr/local/bin/whisper-server",
    "/Applications/OpenWhispr.app/Contents/Resources/bin/whisper-server-*",
]
DIRS_MODELOS_WHISPER = [
    "~/.cache/openwhispr/whisper-models",
    "~/.cache/whisper",
    "~/.cache/whisper.cpp",
    "~/whisper.cpp/models",
]
RUTA_CHROME = "/Applications/Google Chrome.app"
FILTROS_BUSCADOS = ("videotoolbox", "scale_vt", "zscale", "tonemap")


# ---------------------------------------------------------------- utilidades

def ejecutar(cmd, timeout=15):
    """Corre un comando sin shell. Nunca lanza: devuelve (codigo, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "no existe el comando: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "se agoto el tiempo (%ss): %s" % (timeout, " ".join(cmd)[:80])
    except Exception as e:  # noqa: BLE001 - el diagnostico no debe caerse por una sola consulta
        return 1, "", "%s: %s" % (type(e).__name__, e)


def sysctl(clave):
    rc, out, _ = ejecutar(["sysctl", "-n", clave], 5)
    return out.strip() if rc == 0 and out.strip() else None


def sysctl_int(clave):
    v = sysctl(clave)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def es_macos():
    return sys.platform == "darwin"


def directorio_datos(huella):
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "rendimiento-equipo", huella)


def escribir_json_atomico(ruta, datos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp-%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, ruta)


def leer_json(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def a_segundos(etime):
    """Convierte el etime de ps ([[dd-]hh:]mm:ss) a segundos."""
    try:
        dias = 0
        if "-" in etime:
            d, etime = etime.split("-", 1)
            dias = int(d)
        partes = [int(p) for p in etime.split(":")]
        while len(partes) < 3:
            partes.insert(0, 0)
        return dias * 86400 + partes[0] * 3600 + partes[1] * 60 + partes[2]
    except ValueError:
        return None


# ---------------------------------------------------------------- CPU y huella

def leer_cpu():
    n = sysctl_int("hw.nperflevels") or 0
    niveles = []
    for i in range(n):
        base = "hw.perflevel%d." % i
        niveles.append({
            "indice": i,
            "nombre": sysctl(base + "name"),
            "nucleos_fisicos": sysctl_int(base + "physicalcpu"),
            "nucleos_logicos": sysctl_int(base + "logicalcpu"),
            "cpus_por_l2": sysctl_int(base + "cpusperl2"),
        })
    return {
        "marca": sysctl("machdep.cpu.brand_string"),
        "modelo": sysctl("hw.model"),
        "niveles": niveles,  # el nivel 0 es el mas rapido; no se asume cuantos hay ni como se llaman
        "logicalcpu": sysctl_int("hw.logicalcpu"),
        "pagesize": sysctl_int("hw.pagesize"),
    }


def calcular_huella(arquitectura, cpu, memsize):
    """Hash corto de SO + arquitectura + marca + memoria + niveles de rendimiento.

    No incluye la version del SO a proposito: una actualizacion menor no debe tirar lo medido.
    """
    pieza = {
        "so": "macOS" if es_macos() else platform.system(),
        "arq": arquitectura,
        "marca": cpu.get("marca"),
        "memsize": memsize,
        "niveles": [
            [n["nombre"], n["nucleos_fisicos"], n["nucleos_logicos"], n["cpus_por_l2"]]
            for n in cpu.get("niveles", [])
        ],
    }
    crudo = json.dumps(pieza, sort_keys=True).encode("utf-8")
    return hashlib.sha256(crudo).hexdigest()[:12]


# ---------------------------------------------------------------- memoria

def _mb(valor, unidad):
    v = float(valor)
    return v * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}.get(unidad.upper(), 1)


def leer_swap():
    s = sysctl("vm.swapusage")
    if not s:
        return None
    r = {}
    for clave in ("total", "used", "free"):
        m = re.search(r"%s\s*=\s*([\d.,]+)([KMGT])" % clave, s)
        if m:
            r[clave] = round(_mb(m.group(1).replace(",", "."), m.group(2)), 1)
    if not r:
        return None
    return {"total_mb": r.get("total"), "usado_mb": r.get("used"), "libre_mb": r.get("free")}


def swap_creciendo(directorio, usado_mb, guardar=True):
    """Compara el swap actual con la muestra mas antigua dentro de la ventana (1 h)."""
    if usado_mb is None:
        return None
    ruta = os.path.join(directorio, "estado-memoria.json")
    ahora = time.time()
    estado = leer_json(ruta) or {}
    muestras = [m for m in estado.get("muestras", []) if ahora - m.get("t", 0) <= VENTANA_SWAP_S]
    resultado = None
    if muestras:
        base = min(muestras, key=lambda m: m["t"])
        resultado = (usado_mb - base["swap_usado_mb"]) >= UMBRAL_SWAP_CRECE_MB
    if guardar:
        if not muestras or ahora - max(m["t"] for m in muestras) > 60:
            muestras.append({"t": ahora, "swap_usado_mb": usado_mb})
        try:
            escribir_json_atomico(ruta, {"muestras": muestras[-12:]})
        except OSError:
            pass
    return resultado


def leer_memoria(directorio, guardar_estado, avisos):
    memsize = sysctl_int("hw.memsize")
    # memory_pressure SIN argumentos: con -l o -p aplica presion real y altera el sistema.
    rc, out, err = ejecutar(["memory_pressure"], 30)
    libre = None
    if rc == 0:
        m = re.search(r"free percentage:\s*(\d+)\s*%", out)
        libre = int(m.group(1)) if m else None
    else:
        avisos.append("memory_pressure fallo: %s" % (err.strip() or rc))
    swap = leer_swap()
    nivel = sysctl_int("kern.memorystatus_vm_pressure_level")
    nombres = {1: "normal", 2: "aviso", 4: "critica"}
    return {
        "memsize": memsize,
        "memsize_gb": round(memsize / 1024 ** 3, 1) if memsize else None,
        "libre_porcentaje": libre,
        "swap": swap,
        "swap_creciendo": swap_creciendo(directorio, swap["usado_mb"] if swap else None, guardar_estado),
        "nivel_presion": nivel,
        "presion": nombres.get(nivel, "desconocida"),
    }


# ---------------------------------------------------------------- GPU y Swift

def leer_gpu(avisos):
    rc, out, err = ejecutar(["system_profiler", "SPDisplaysDataType", "-json"], 30)
    gpu = {"nombre": None, "nucleos": None}
    if rc != 0:
        avisos.append("system_profiler fallo: %s" % (err.strip() or rc))
        return gpu
    try:
        items = json.loads(out).get("SPDisplaysDataType", [])
    except ValueError:
        avisos.append("system_profiler no devolvio JSON valido")
        return gpu
    for it in items:
        if it.get("sppci_cores") or it.get("sppci_model"):
            gpu["nombre"] = it.get("sppci_model") or it.get("_name")
            try:
                gpu["nucleos"] = int(it.get("sppci_cores"))
            except (TypeError, ValueError):
                gpu["nucleos"] = None
            break
    return gpu


def correr_swift(avisos, tiempo_limite=SWIFT_TIEMPO_LIMITE):
    """Ejecuta capacidades_macos.swift. Si falla, devuelve None y deja un aviso."""
    if not shutil.which("swift"):
        avisos.append("No hay swift (instala las Command Line Tools con 'xcode-select --install'): "
                      "faltan Metal, VideoToolbox, Neural Engine y estado termico.")
        return None
    if not os.path.exists(SWIFT_ARCHIVO):
        avisos.append("Falta %s" % SWIFT_ARCHIVO)
        return None
    rc, out, err = ejecutar(["swift", SWIFT_ARCHIVO], tiempo_limite)
    if rc != 0:
        resumen = (err.strip().splitlines() or [str(rc)])[-1][:200]
        avisos.append("swift fallo (%s): faltan Metal, VideoToolbox, Neural Engine y estado termico." % resumen)
        return None
    try:
        return json.loads(out)
    except ValueError:
        avisos.append("swift no devolvio JSON valido")
        return None


# ---------------------------------------------------------------- herramientas

def inspeccionar_ffmpeg(ruta):
    rc, out, _ = ejecutar([ruta, "-hide_banner", "-version"], 10)
    if rc != 0:
        return None
    primera = out.splitlines()[0] if out else ""
    m = re.search(r"version\s+(\S+)", primera)
    _, enc, _ = ejecutar([ruta, "-hide_banner", "-encoders"], 15)
    codificadores = re.findall(r"^\s*[VAS][.\w]{5}\s+(\S+)", enc, re.M)
    _, fil, _ = ejecutar([ruta, "-hide_banner", "-filters"], 15)
    filtros = re.findall(r"^\s*[T.][S.][C.]\s+(\S+)", fil, re.M)
    _, hw, _ = ejecutar([ruta, "-hide_banner", "-hwaccels"], 10)
    hwaccels = [l.strip() for l in hw.splitlines()[1:] if l.strip()]
    relevantes = sorted({f for f in filtros if any(b in f for b in FILTROS_BUSCADOS)})
    vt = sorted(e for e in codificadores if "videotoolbox" in e)
    return {
        "ruta": ruta,
        "version": m.group(1) if m else primera[:60],
        "codificadores_videotoolbox": vt,
        "libx264": "libx264" in codificadores,
        "hwaccels": hwaccels,
        "filtros_relevantes": relevantes,
        "scale_vt": "scale_vt" in filtros,
        "zscale": "zscale" in filtros,
        "tonemap": "tonemap" in filtros,
    }


def puntaje_ffmpeg(f):
    return (len(f["codificadores_videotoolbox"]) * 10 + (5 if f["zscale"] else 0)
            + (5 if f["tonemap"] else 0) + (3 if f["libx264"] else 0)
            + (3 if "videotoolbox" in f["hwaccels"] else 0))


def buscar_ffmpeg(avisos):
    candidatos = []
    vistos = set()
    rutas = [os.environ.get("RENDIMIENTO_FFMPEG"), shutil.which("ffmpeg")] + RUTAS_FFMPEG
    for r in rutas:
        if not r or not os.path.isfile(r) or not os.access(r, os.X_OK):
            continue
        real = os.path.realpath(r)
        if real in vistos:
            continue
        vistos.add(real)
        info = inspeccionar_ffmpeg(r)
        if info:
            candidatos.append(info)
    elegido = max(candidatos, key=puntaje_ffmpeg)["ruta"] if candidatos else None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe and elegido:
        hermano = os.path.join(os.path.dirname(elegido), "ffprobe")
        ffprobe = hermano if os.path.isfile(hermano) else None
    if not candidatos:
        avisos.append("No se encontro ningun ffmpeg (ni en PATH ni en rutas conocidas).")
    return {"elegido": elegido, "candidatos": candidatos, "ffprobe": ffprobe}


def buscar_whisper():
    servidores = []
    cand = [shutil.which("whisper-server")]
    for patron in RUTAS_WHISPER_SERVER:
        cand.extend(glob.glob(patron))
    vistos = set()
    for r in cand:
        if not r or not os.path.isfile(r) or not os.access(r, os.X_OK):
            continue
        real = os.path.realpath(r)
        if real in vistos:
            continue
        vistos.add(real)
        carpeta = os.path.dirname(real)
        backends = sorted({
            re.sub(r"^libggml-|\..*$", "", os.path.basename(p))
            for p in glob.glob(os.path.join(carpeta, "libggml-*.dylib"))
        } - {"base"})
        servidores.append({"ruta": r, "backends_junto_al_binario": backends,
                           "de_openwhispr": "OpenWhispr.app" in real})
    modelos = []
    dirs = [os.environ.get("WHISPER_MODELS_DIR")] + DIRS_MODELOS_WHISPER
    for d in dirs:
        if not d:
            continue
        d = os.path.expanduser(d)
        for p in sorted(glob.glob(os.path.join(d, "ggml-*.bin"))):
            try:
                mb = round(os.path.getsize(p) / 1024 ** 2)
            except OSError:
                mb = None
            coreml = bool(glob.glob(p[:-4] + "-encoder.mlmodelc"))
            modelos.append({"ruta": p, "mb": mb, "encoder_coreml": coreml})
    return {"servidores": servidores, "modelos": modelos}


def leer_remotion(proyecto):
    if not proyecto:
        return {"estado": "no consultado (pasa --proyecto <ruta> para inspeccionarlo)"}
    proyecto = os.path.expanduser(proyecto)
    if not os.path.isdir(proyecto):
        return {"estado": "la ruta no existe", "proyecto": proyecto}
    info = {"proyecto": proyecto}
    pkg = leer_json(os.path.join(proyecto, "package.json")) or {}
    deps = {}
    deps.update(pkg.get("dependencies", {}))
    deps.update(pkg.get("devDependencies", {}))
    info["version"] = deps.get("remotion") or deps.get("@remotion/cli")
    binario = os.path.join(proyecto, "node_modules", ".bin", "remotion")
    info["cli"] = binario if os.path.exists(binario) else None
    info["config"] = os.path.exists(os.path.join(proyecto, "remotion.config.ts"))
    shells = glob.glob(os.path.join(proyecto, "node_modules", ".remotion", "chrome-headless-shell", "*", "*", "chrome-headless-shell"))
    info["chrome_headless_shell"] = shells[0] if shells else None
    node = shutil.which("node")
    info["node"] = node
    if node:
        _, v, _ = ejecutar([node, "--version"], 5)
        info["node_version"] = v.strip()
    info["estado"] = "listo" if info["cli"] else "falta node_modules (npm install en el proyecto)"
    return info


def leer_chrome():
    plist = os.path.join(RUTA_CHROME, "Contents", "Info.plist")
    binario = os.path.join(RUTA_CHROME, "Contents", "MacOS", "Google Chrome")
    if not os.path.exists(binario):
        return {"ruta": None}
    version = None
    try:
        with open(plist, "rb") as f:
            version = plistlib.load(f).get("CFBundleShortVersionString")
    except (OSError, ValueError, plistlib.InvalidFileException):
        pass
    return {"ruta": binario, "version": version}


def leer_swift():
    ruta = shutil.which("swift")
    if not ruta:
        return {"ruta": None}
    rc, out, _ = ejecutar([ruta, "--version"], 15)
    return {"ruta": ruta, "version": out.splitlines()[0][:120] if rc == 0 and out else None}


# ---------------------------------------------------------------- procesos

PATRONES_EXE = [
    # (tipo, regex anclado al inicio del comando: asi un "grep remotion" o este mismo script no cuentan)
    ("whisper-server", re.compile(r"^(?:\S[^\n]*?/)?whisper-server[^/\s]*(?:\s|$)")),
    ("chrome-headless", re.compile(r"^(?:\S[^\n]*?/)?(?:chrome-headless-shell|Google Chrome(?: Helper[^/]*)?)(?:\s|$)")),
    ("ffmpeg", re.compile(r"^(?:\S[^\n]*?/)?ffmpeg(?:\s|$)")),
    ("remotion", re.compile(r"^(?:\S[^\n]*?/)?remotion(?:\s|$)")),                      # compositor
    ("remotion", re.compile(r"^(?:\S*/)?node(?:\s+-\S+)*\s+\S[^\n]*?(?:/\.bin/remotion|/@remotion/cli/)")),
    ("remotion", re.compile(r"^(?:\S*/)?(?:npx|npm)\s+(?:exec\s+)?remotion\b")),
]


def tipo_de_proceso(cmd):
    for tipo, rx in PATRONES_EXE:
        if rx.search(cmd):
            if tipo == "chrome-headless" and "Google Chrome" in cmd.split(" --")[0] and "--headless" not in cmd:
                continue  # Chrome normal del usuario, no el que corre sin ventana
            return tipo
    return None


def listar_procesos():
    rc, out, _ = ejecutar(["ps", "-axo", "pid=,ppid=,etime=,command="], 15)
    tabla = {}
    for linea in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\S+)\s+(.*)$", linea)
        if m:
            tabla[int(m.group(1))] = {"pid": int(m.group(1)), "ppid": int(m.group(2)),
                                      "etime": m.group(3), "cmd": m.group(4)}
    return tabla


def cadena_de_padres(tabla, pid):
    cadena, visto = [], set()
    actual = tabla.get(pid, {}).get("ppid")
    while actual and actual not in visto and actual in tabla:
        visto.add(actual)
        cadena.append(actual)
        actual = tabla[actual]["ppid"]
    return cadena


def descendientes(tabla, pid):
    hijos = {}
    for p in tabla.values():
        hijos.setdefault(p["ppid"], []).append(p["pid"])
    resultado, pila = [], list(hijos.get(pid, []))
    while pila:
        h = pila.pop()
        resultado.append(h)
        pila.extend(hijos.get(h, []))
    return resultado


def clasificar(tabla, pid, tipo):
    """Devuelve (clase, motivo). Clases: protegido, propio, en_uso.

    protegido: de OpenWhispr (usa --model y --host, o cuelga de OpenWhispr.app). Nunca se toca.
    propio:    whisper-server lanzado por un agente (-m y --port 88xx), o remotion/chrome sin
               ventana cuyo padre es launchd (huerfano) o desciende de uno.
    en_uso:    cualquier otro caso (por ejemplo un render con su padre vivo). Tampoco se toca.
    """
    p = tabla[pid]
    cmd = p["cmd"]
    padres = cadena_de_padres(tabla, pid)
    de_app = any("OpenWhispr.app" in tabla[a]["cmd"] for a in padres)
    if tipo == "whisper-server":
        modelo_host = bool(re.search(r"(^|\s)--model(\s|=)", cmd) and re.search(r"(^|\s)--host(\s|=)", cmd))
        if modelo_host or de_app:
            razones = (["usa --model y --host"] if modelo_host else []) + (["cuelga de OpenWhispr.app"] if de_app else [])
            return "protegido", "servidor de la app OpenWhispr: " + " y ".join(razones)
        if re.search(r"(^|\s)-m\s", cmd) and re.search(r"--port\s+88\d\d(\s|$)", cmd):
            return "propio", "lanzado por un agente (-m ... --port 88xx)"
        return "en_uso", "whisper-server que no encaja con el patron de agentes: no se toca"
    if de_app:
        return "protegido", "cuelga de OpenWhispr.app"
    if tipo in ("remotion", "chrome-headless"):
        if p["ppid"] == 1:
            if tipo == "remotion" and re.search(r"\bremotion\s+(render|still|studio|benchmark|preview)\b", cmd):
                if descendientes(tabla, pid):
                    return "en_uso", "CLI de remotion sin padre pero con procesos hijos activos: puede ser un render lanzado en segundo plano"
            return "propio", "huerfano (padre = launchd)"
        for a in padres:
            if tabla[a]["ppid"] == 1 and tipo_de_proceso(tabla[a]["cmd"]) in ("remotion", "chrome-headless"):
                if tipo_de_proceso(tabla[a]["cmd"]) == "remotion" and descendientes(tabla, a):
                    break
                return "propio", "hijo del proceso huerfano %d" % a
        return "en_uso", "tiene un padre vivo (%d): probablemente un render en curso" % p["ppid"]
    return "en_uso", "se informa pero nunca se termina desde aqui"


def procesos_pesados():
    tabla = listar_procesos()
    yo = {os.getpid(), os.getppid()}
    lista = []
    for pid, p in tabla.items():
        if pid in yo:
            continue
        tipo = tipo_de_proceso(p["cmd"])
        if not tipo:
            continue
        clase, motivo = clasificar(tabla, pid, tipo)
        puerto = re.search(r"--port\s+(\d+)", p["cmd"])
        lista.append({
            "pid": pid,
            "tipo": tipo,
            "puerto": int(puerto.group(1)) if puerto else None,
            "edad_s": a_segundos(p["etime"]),
            "edad": p["etime"],
            "padre": p["ppid"],
            "padre_cmd": (tabla.get(p["ppid"], {}).get("cmd") or "")[:100],
            "clase": clase,
            "protegido": clase == "protegido",
            "motivo": motivo,
            "comando": p["cmd"][:240],
        })
    lista.sort(key=lambda x: (x["tipo"], x["pid"]))
    return lista


# ---------------------------------------------------------------- diagnostico completo

def diagnosticar(proyecto=None, guardar_estado=True, tiempo_swift=SWIFT_TIEMPO_LIMITE):
    avisos = []
    arq = platform.machine()
    if not es_macos():
        huella = hashlib.sha256(("%s|%s|%s" % (platform.system(), arq, platform.processor())).encode()).hexdigest()[:12]
        return {
            "esquema": ESQUEMA,
            "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
            "so": {"nombre": platform.system(), "version": platform.release()},
            "arquitectura": arq,
            "huella": huella,
            "soporte": SOPORTE_SIN_MEDIR,
            "cpu": {"logicalcpu": os.cpu_count()},
            "procesos_pesados": [],
            "avisos": ["%s: %s. Lee references/windows.md; no hay recomendaciones medidas." % (platform.system(), SOPORTE_SIN_MEDIR)],
        }

    cpu = leer_cpu()
    memsize = sysctl_int("hw.memsize")
    huella = calcular_huella(arq, cpu, memsize)
    rc, ver, _ = ejecutar(["sw_vers", "-productVersion"], 5)
    memoria = leer_memoria(directorio_datos(huella), guardar_estado, avisos)
    gpu = leer_gpu(avisos)
    sw = correr_swift(avisos, tiempo_swift)
    metal = video = ne = None
    termico = None
    bajo = None
    if sw:
        metal = sw.get("metal")
        video = {
            "codificadores": sw.get("codificadores"),
            "decodificadores_hw": sw.get("decodificadores_hw"),
        }
        ne = sw.get("neural_engine")
        termico = sw.get("termico")
        bajo = sw.get("bajo_consumo")
        avisos.extend(sw.get("avisos", []))
    gpu["metal"] = metal

    return {
        "esquema": ESQUEMA,
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "so": {"nombre": "macOS", "version": ver.strip() if rc == 0 else platform.mac_ver()[0],
               "kernel": "%s %s" % (platform.system(), platform.release())},
        "arquitectura": arq,
        "huella": huella,
        "directorio_datos": directorio_datos(huella),
        "cpu": cpu,
        "memoria": memoria,
        "gpu": gpu,
        "video": video,
        "neural_engine": ne,
        "termico": termico,
        "bajo_consumo": bajo,
        "herramientas": {
            "ffmpeg": buscar_ffmpeg(avisos),
            "whisper": buscar_whisper(),
            "remotion": leer_remotion(proyecto),
            "chrome": leer_chrome(),
            "swift": leer_swift(),
            "taskpolicy": shutil.which("taskpolicy"),
        },
        "procesos_pesados": procesos_pesados(),
        "avisos": avisos,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Diagnostica el equipo (CPU por niveles, memoria, GPU, video por hardware, "
                    "Neural Engine, termico, herramientas y procesos pesados) y lo imprime como JSON.")
    ap.add_argument("--proyecto", help="ruta de un proyecto Remotion para inspeccionarlo (opcional)")
    ap.add_argument("--sin-estado", action="store_true",
                    help="no guardar la muestra de swap en el directorio de datos")
    ap.add_argument("--tiempo-swift", type=int, default=SWIFT_TIEMPO_LIMITE,
                    help="tiempo limite en segundos para el script de Swift (por defecto %(default)s)")
    ap.add_argument("--compacto", action="store_true", help="JSON en una linea")
    args = ap.parse_args(argv)
    d = diagnosticar(args.proyecto, not args.sin_estado, args.tiempo_swift)
    print(json.dumps(d, ensure_ascii=False, indent=None if args.compacto else 2))
    for a in d.get("avisos", []):
        print("aviso: %s" % a, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
