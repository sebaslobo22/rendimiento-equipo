#!/usr/bin/env python3
"""Calibra este equipo: mide en el las tareas pesadas y deja el punto dulce de cada una en su perfil.

Sin opciones, solo mide con lo que ya hay en el equipo, sin descargar nada:

  Dictado  todos los modelos de OpenWhispr descargados, con un audio de prueba en espanol que genera la voz del
           sistema (say en macOS, System.Speech en Windows) o con tu propio audio (--audio y --texto).
  Video    codificar en CPU frente al motor de video y cuantas codificaciones rinden a la vez. Con --video
           (un video real tuyo) lo que gane se guarda; sin el, una prueba orientativa con un clip generado que
           NO se guarda: un clip sintetico se comprime mucho mas facil que un video real y engana.

Despues dice que modelo de dictado conviene y por que, y que candidatos faltan por medir.

  --descargar   ademas descarga los candidatos que faltan (los de menos error publico que caben en este
                equipo) en una carpeta de la skill, NO en OpenWhispr; los mide y los borra al terminar
                (--conservar para dejarlos). Pide un si del usuario antes: son cientos de MB o varios GB.
  --plan        solo muestra que mediria y que descargaria, sin hacer nada.

Todo queda en ~/.local/share/rendimiento-equipo/<huella>/ (mediciones.md y perfil-medido.json). Nunca cambia
la configuracion de OpenWhispr ni toca sus procesos: el modelo lo cambias tu, si quieres.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime

sys.dont_write_bytecode = True
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import diagnosticar as dg  # noqa: E402
import voz  # noqa: E402

TEXTO = os.path.join(AQUI, "..", "assets", "texto_calibracion_es.txt")
VOCES_PREFERIDAS = ("Paulina", "Mónica", "Monica", "Juan", "Jorge", "Diego")


def decir(msg=""):
    print(msg, flush=True)


def huella():
    return dg.calcular_huella(dg.platform.machine(), dg.leer_cpu(), dg.memoria_total())


def medir(args, timeout=3600):
    """Corre medir.py y devuelve su JSON (o None) y el error, sin tumbar la calibracion."""
    r = subprocess.run([sys.executable, os.path.join(AQUI, "medir.py")] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    try:
        return json.loads(r.stdout), r.stderr.strip()
    except ValueError:
        return None, (r.stderr or r.stdout).strip()[-400:]


# ---------------------------------------------------------------- audio de prueba

def voz_sistema(texto, salida):
    """Lee el texto con una voz en espanol del sistema. Devuelve (ruta, nombre de la voz) o (None, motivo)."""
    if dg.es_macos():
        rc, out, _ = dg.ejecutar(["say", "-v", "?"], 15)
        voces = [ln.split(" es_")[0].strip() for ln in out.splitlines() if " es_" in ln] if rc == 0 else []
        if not voces:
            return None, "no hay voces en espanol instaladas (Ajustes > Accesibilidad > Contenido leido)"
        elegida = next((v for p in VOCES_PREFERIDAS for v in voces if v.startswith(p)), voces[0])
        rc, _, err = dg.ejecutar(["say", "-v", elegida, "-o", salida + ".aiff", "-f", texto], 120)
        return (salida + ".aiff", elegida) if rc == 0 else (None, err.strip()[-200:])
    if dg.es_windows():
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'es*' } | Select-Object -First 1; "
              "if (-not $v) { exit 3 }; $s.SelectVoice($v.VoiceInfo.Name); $s.SetOutputToWaveFile($env:RE_SALIDA); "
              "$s.Speak([IO.File]::ReadAllText($env:RE_TEXTO)); $s.Dispose(); Write-Output $v.VoiceInfo.Name")
        env = dict(os.environ, RE_SALIDA=salida + ".wav", RE_TEXTO=os.path.abspath(texto))
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                           text=True, env=env, timeout=180)
        if r.returncode == 3:
            return None, "no hay voces en espanol instaladas (Configuracion > Hora e idioma > Voz)"
        return (salida + ".wav", r.stdout.strip()) if r.returncode == 0 else (None, r.stderr.strip()[-200:])
    return None, "sistema sin voz de prueba"


# ---------------------------------------------------------------- descargas

def espacio_libre_mb(carpeta):
    os.makedirs(carpeta, exist_ok=True)
    return shutil.disk_usage(carpeta).free / 1024 ** 2


def bajar(url, destino):
    """Descarga con avance cada 10 %. Escribe a un .parcial y lo renombra al final."""
    parcial = destino + ".parcial"
    with urllib.request.urlopen(url, timeout=60) as r, open(parcial, "wb") as f:
        total, hecho, marca = int(r.headers.get("Content-Length") or 0), 0, 0
        while True:
            trozo = r.read(1 << 20)
            if not trozo:
                break
            f.write(trozo)
            hecho += len(trozo)
            if total and hecho * 10 // total > marca:
                marca = hecho * 10 // total
                decir("    %d %% de %d MB" % (marca * 10, total // 1024 ** 2))
    os.replace(parcial, destino)


def extraer_seguro(archivo, carpeta):
    """Extrae un .tar.bz2 sin dejar que nada salga de la carpeta (rutas absolutas, .. o enlaces)."""
    base = os.path.realpath(carpeta)
    with tarfile.open(archivo, "r:*") as t:
        for m in t.getmembers():
            dest = os.path.realpath(os.path.join(base, m.name))
            if not (dest == base or dest.startswith(base + os.sep)) or m.issym() or m.islnk() or m.isdev():
                raise ValueError("el archivo trae una ruta insegura: %s" % m.name)
        t.extractall(base)


def descargar(m):
    """Deja el modelo en la carpeta de pruebas de la skill. Devuelve la ruta creada."""
    base = voz.carpeta_pruebas()
    if m["familia"] == "whisper":
        carpeta = os.path.join(base, "whisper-models")
        os.makedirs(carpeta, exist_ok=True)
        destino = os.path.join(carpeta, m["archivo"])
        bajar(m["url"], destino)
        return destino
    carpeta = os.path.join(base, "parakeet-models")
    os.makedirs(carpeta, exist_ok=True)
    comprimido = os.path.join(carpeta, m["archivo"] + ".tar.bz2")
    bajar(m["url"], comprimido)
    try:
        extraer_seguro(comprimido, carpeta)
    finally:
        os.remove(comprimido)
    return os.path.join(carpeta, m["archivo"])


# ---------------------------------------------------------------- pasos

def plan_voz(idioma):
    rec = voz.recomendar(dg.memoria_total(), idioma, None, False, dg.es_macos() and dg.platform.machine() == "arm64",
                         equipo_ref())
    ya, faltan = voz.candidatos_prueba(rec)
    return rec, ya, faltan


def equipo_ref():
    import arquitectura as arq
    ref = arq.referencia_apple((dg.leer_cpu() or {}).get("marca") or "") or {}
    return {"ancho_banda_gbs": ref.get("ancho_banda_gbs")}


def calibrar_voz(args, tmp, resumen):
    decir("DICTADO")
    rec, ya, faltan = plan_voz(args.idioma)
    if not rec["catalogo"].startswith("OpenWhispr"):
        decir("  OpenWhispr no esta instalado: no hay modelos que medir. Recomendacion por ficha publica: %s." %
              ((rec.get("recomendado") or {}).get("nombre") or "ninguna"))
        resumen["voz"] = {"estado": "sin OpenWhispr"}
        return
    decir("  Ya en el equipo y utiles: %s" % (", ".join(m["nombre"] for m in ya) or "ninguno"))
    total = sum(m["mb"] or 0 for m in faltan)
    if faltan:
        decir("  Candidatos que faltan por medir: %s (%d MB en total)" % (
            ", ".join("%s (%s MB, %s)" % (m["nombre"], m["mb"], "%s %% de error publico" % m["wer"] if m["wer"] is not None
                                                else "nuevo, sin ficha publica") for m in faltan), total))
    if args.plan:
        resumen["voz"] = {"estado": "plan", "medir": [m["id"] for m in ya], "descargar": [m["id"] for m in faltan]}
        return
    creados = []
    if faltan and args.descargar:
        libre = espacio_libre_mb(voz.carpeta_pruebas())
        if libre < total * 2.5:
            decir("  No descargo: hacen falta unos %d MB libres y hay %d." % (total * 2.5, libre))
        else:
            for m in faltan:
                decir("  descargando %s..." % m["nombre"])
                try:
                    creados.append(descargar(m))
                except Exception as e:  # noqa: BLE001 - un modelo que no baja no detiene los demas
                    decir("    no se pudo: %s" % e)
    elif faltan:
        decir("  No descargo nada sin permiso. Para medirlos tambien: calibrar.py --descargar")
    try:
        if args.audio:
            audio, texto, origen = args.audio, args.texto, "tu audio"
        else:
            if args.idioma != "es":
                decir("  El audio de prueba incluido es en espanol: para %s usa --audio y --texto." % args.idioma)
                resumen["voz"] = {"estado": "falta audio"}
                return
            audio, origen = voz_sistema(TEXTO, os.path.join(tmp, "prueba"))
            texto = TEXTO
            if not audio:
                decir("  Sin audio de prueba: %s. Usa --audio y --texto." % origen)
                resumen["voz"] = {"estado": "sin audio", "motivo": origen}
                return
            origen = "voz sintetica del sistema (%s)" % origen
        decir("  midiendo con %s; una pasada de calentamiento y 3 medidas por modelo..." % origen)
        cmd = ["voz", "--audio", audio, "--idioma", args.idioma, "--registrar"] + ([] if args.audio else ["--audio-sintetico"])
        if texto:
            cmd += ["--texto", texto]
        if args.aceptar_ruido:
            cmd.append("--aceptar-ruido")
        out, err = medir(cmd)
    finally:
        if creados and not args.conservar:
            for c in creados:
                shutil.rmtree(c, ignore_errors=True) if os.path.isdir(c) else os.remove(c)
            decir("  modelos de prueba borrados (--conservar para dejarlos)")
    if not out:
        decir("  la medicion fallo: %s" % err)
        resumen["voz"] = {"estado": "fallo", "error": err}
        return
    for k, r in out["variantes"].items():
        if r.get("fallo"):
            decir("  %-28s fallo: %s" % (k, r["error"][:120]))
        else:
            decir("  %-28s %5s s  %5sx tiempo real  %5s MB  %s" % (
                k, r["transcribe_s"], r["veces_tiempo_real"], r["memoria_mb"],
                "" if r["wer"] is None else "%s %% de error" % r["wer"]))
    if out.get("api_tensores") is not None:
        decir("  Neural Accelerators en el Whisper de OpenWhispr: %s" % ("si" if out["api_tensores"] else "no"))
    reg = (out.get("registro") or {}).get("perfil_medido") or {}
    if not reg.get("actualizado"):
        decir("  aviso: no se guardo en el perfil (%s)" % reg.get("motivo", "sin detalle"))
    resumen["voz"] = {"estado": "medido", "audio": origen, "modelos": list(out["variantes"])}


def calibrar_video(args, tmp, resumen):
    decir("")
    decir("VIDEO")
    if args.plan:
        decir("  mediria: codificar en CPU frente al motor de video y codificaciones a la vez, con un clip generado")
        return
    ff = ((dg.buscar_ffmpeg([]) or {}).get("elegido"))
    if not ff:
        decir("  sin ffmpeg: no se mide video")
        resumen["video"] = {"estado": "sin ffmpeg"}
        return
    if args.video:
        clip, registrar = os.path.expanduser(args.video), True
        decir("  con tu video: lo que gane se guarda en el perfil")
    else:
        # Un clip generado sirve para ver que todo funciona, no para decidir: se comprime mucho mas facil que un
        # video real y le da ventaja a la CPU. Por eso no se guarda.
        clip, registrar = os.path.join(tmp, "clip.mp4"), False
        rc, _, err = dg.ejecutar([ff, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                  "testsrc2=size=1080x1920:rate=30:duration=12", "-c:v", "libx264", "-preset", "veryfast",
                                  "-pix_fmt", "yuv420p", clip], 300)
        if rc != 0:
            decir("  ffmpeg no pudo generar el clip: %s" % err.strip()[-200:])
            resumen["video"] = {"estado": "fallo"}
            return
        decir("  sin video tuyo: prueba orientativa con un clip generado, NO se guarda (usa --video con un video real)")
    extra = ["--aceptar-ruido"] if args.aceptar_ruido else []
    hechos = {}
    for nombre, cmd in (("codificar", ["codificar", "--archivo", clip, "--segundos", "10"]),
                        ("paralelo", ["paralelo", "--archivo", clip, "--segundos", "10"])):
        decir("  midiendo %s..." % nombre)
        out, err = medir(cmd + (["--registrar"] if registrar else []) + extra)
        if not out:
            decir("    fallo: %s" % err[-200:])
            continue
        for c in out.get("comparaciones") or []:
            decir("    %s frente a %s: gana %s (%s)" % (c.get("candidato"), c.get("base"), c.get("ganador") or "ninguno claro", c.get("motivo", "")))
        if out.get("elegido") is not None:
            decir("    codificaciones a la vez que rinden: %s" % out["elegido"])
        hechos[nombre] = True
    resumen["video"] = {"estado": ("medido" if registrar else "orientativo") if hechos else "fallo", "pruebas": list(hechos)}


def conclusion(resumen):
    decir("")
    decir("PUNTO DULCE DE ESTE EQUIPO")
    r = subprocess.run([sys.executable, os.path.join(AQUI, "perfil.py"), "--formato", "json"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    try:
        p = json.loads(r.stdout)
    except ValueError:
        decir("  no se pudo leer el perfil: %s" % r.stderr[-200:])
        return
    v = p.get("voz") or {}
    rec = v.get("recomendado")
    if rec:
        decir("  Dictado: %s. %s %% de palabras erradas (%s), unos %s MB%s." % (
            rec["nombre"], rec["wer"], rec["wer_fuente"], rec["memoria_mb"],
            ", %s veces el tiempo real" % rec["velocidad"] if rec.get("velocidad") else ""))
        decir("           %s. Criterio: %s." % ("Ya lo tienes en OpenWhispr" if rec["instalado"] else
                                                "Para usarlo: " + v["como_cambiarlo"], v.get("criterio")))
        if v.get("medir_tambien"):
            decir("           Podria ganar si se mide: %s (calibrar.py --descargar)." % ", ".join(v["medir_tambien"]))
    ff = p.get("ffmpeg") or {}
    if ff.get("disponible"):
        decir("  Video:   codificar con %s [%s]; %s codificacion(es) a la vez." % (
            ff["codificador"]["metodo"], ff["codificador"]["origen"],
            ((p.get("arquitectura") or {}).get("codificaciones_paralelas") or {}).get("valor") or "sin medir"))
    resumen["perfil"] = {"voz": rec and rec["id"], "video": ff.get("codificador")}


def guardar(resumen):
    """calibracion.json: con que version de OpenWhispr y que modelos se calibro, para saber cuando repetir."""
    cat, version, _ = voz.catalogo_openwhispr()
    resumen.update({"fecha": datetime.now().astimezone().isoformat(timespec="seconds"), "openwhispr": version,
                    "modelos_catalogo": sorted(m["id"] for m in voz.modelos(cat)) if cat else []})
    carpeta = dg.directorio_datos(huella())
    os.makedirs(carpeta, exist_ok=True)
    dg.escribir_json_atomico(os.path.join(carpeta, "calibracion.json"), resumen)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mide este equipo y deja el punto dulce de cada tarea en su perfil.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--plan", action="store_true", help="solo muestra que mediria y que descargaria")
    ap.add_argument("--descargar", action="store_true", help="descarga los candidatos de dictado que faltan (pide permiso antes)")
    ap.add_argument("--conservar", action="store_true", help="no borra los modelos descargados para la prueba")
    ap.add_argument("--audio", help="tu propio audio de prueba (mejor que la voz sintetica)")
    ap.add_argument("--texto", help="lo que dice tu audio (archivo .txt o el texto)")
    ap.add_argument("--video", help="un video real tuyo (mejor 15 s o mas): solo con el se guarda lo que gane en video")
    ap.add_argument("--idioma", default="es", help="idioma en que dictas (por defecto %(default)s)")
    ap.add_argument("--solo", choices=("voz", "video"), help="calibrar solo una tarea")
    ap.add_argument("--aceptar-ruido", action="store_true", help="guarda aunque haya otros procesos pesados")
    a = ap.parse_args(argv)
    if a.audio and not a.texto:
        decir("aviso: sin --texto se mide velocidad y memoria, pero no el error.")
    if not (dg.es_macos() or dg.es_windows()):
        decir("calibrar.py mide en macOS y Windows; este sistema no tiene pruebas todavia.")
        return 2
    decir("Calibrando este equipo (huella %s). Nada cambia en OpenWhispr ni en tus apps." % huella())
    decir("")
    t0 = time.time()
    resumen = {}
    tmp = tempfile.mkdtemp(prefix="rendimiento-equipo-calibra-")
    try:
        if a.solo != "video":
            calibrar_voz(a, tmp, resumen)
        if a.solo != "voz":
            calibrar_video(a, tmp, resumen)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if a.plan:
        return 0
    conclusion(resumen)
    guardar(resumen)
    decir("")
    decir("Listo en %d s. Detalle en %s" % (time.time() - t0, os.path.join(dg.directorio_datos(huella()), "mediciones.md")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
