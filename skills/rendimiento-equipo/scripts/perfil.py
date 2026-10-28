#!/usr/bin/env python3
"""Convierte el diagnostico del equipo en recomendaciones para trabajo pesado.

Primero calcula por formula (a partir de lo que el equipo realmente ofrece) y despues
sobrescribe con lo MEDIDO que haya en
    ~/.local/share/rendimiento-equipo/<huella>/perfil-medido.json
Lo medido gana a la formula. Entrega ademas un bloque de texto listo para pegar en el
encargo de un subagente (los subagentes no heredan skills ni contexto).

Uso:
    python3 perfil.py --renders 3 --formato texto
    python3 perfil.py --diagnostico diag.json          # sin volver a diagnosticar

Solo biblioteca estandar. No usa red. Con --diagnostico no ejecuta Swift ni escribe nada.
Codigos de salida: 0 = ok; 2 = argumentos o archivo invalido.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys

sys.dont_write_bytecode = True  # no ensuciar la carpeta compartida de la skill
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import diagnosticar as dg  # noqa: E402
import arquitectura as arq  # noqa: E402

# Criterios (no son mediciones): salen de la regla de la skill anterior y de la doc de Remotion.
# Se pueden sustituir con lo medido (npx remotion benchmark --concurrencies) en perfil-medido.json.
FRACCION_UN_RENDER = 0.6    # de los nucleos para render (ver nucleos_para_render) que usa un render solo
FRACCION_TOTAL = 0.9        # de los nucleos para render que se reparten entre renders en paralelo
FRACCION_CACHE = 0.25       # de la memoria total para las cache de OffthreadVideo, repartida entre renders
BITRATE_FINAL = "12M"
BITRATE_PREVIA = "3500k"
ESTADOS_VALIDOS = ("gana", "adoptado")
PUERTOS_AGENTES = range(8801, 8900)


# ---------------------------------------------------------------- lectura de lo medido

def cargar_medido(huella):
    ruta = os.path.join(dg.directorio_datos(huella), "perfil-medido.json")
    datos = dg.leer_json(ruta)
    if datos is None:
        return {}, None
    return datos, ruta


def vale(entrada):
    return isinstance(entrada, dict) and entrada.get("estado") in ESTADOS_VALIDOS


def origen(entrada):
    if isinstance(entrada, dict) and entrada.get("fecha"):
        return "medido (%s)" % entrada["fecha"]
    return "medido"


# ---------------------------------------------------------------- hechos del diagnostico

def hw_codifica(d, fourcc):
    v = d.get("video") or {}
    cod = (v.get("codificadores") or {}).get("codecs_por_hardware")
    return None if cod is None else fourcc in cod


def hw_decodifica(d, nombre):
    v = d.get("video") or {}
    dec = v.get("decodificadores_hw")
    return None if dec is None else bool(dec.get(nombre))


def ffmpeg_elegido(d):
    h = (d.get("herramientas") or {}).get("ffmpeg") or {}
    for c in h.get("candidatos", []):
        if c["ruta"] == h.get("elegido"):
            return c
    return None


def puerto_libre(ocupados):
    for p in PUERTOS_AGENTES:
        if p in ocupados:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return None


# ---------------------------------------------------------------- calculo

def calcular_frenos(d, medido):
    mem = d.get("memoria") or {}
    nivel = mem.get("nivel_presion")
    crece = mem.get("swap_creciendo")
    motivos = []
    if nivel is not None and nivel >= 2:
        motivos.append("presion de memoria %s (nivel %s)" % (mem.get("presion"), nivel))
    if crece:
        motivos.append("el swap esta creciendo")
    termico = d.get("termico")
    termico_activo = termico in ("serious", "critical")
    return {
        "memoria": {"activo": bool(motivos), "motivos": motivos,
                    "accion": "serializar: un render a la vez y nada de conversiones pesadas en paralelo"},
        "termico": {"activo": termico_activo, "estado": termico,
                    "accion": "mitad de concurrencia (--concurrency y renders en paralelo a la mitad)"},
        "bajo_consumo": {"activo": bool(d.get("bajo_consumo")),
                         "accion": "macOS limita el rendimiento: desactivar el modo de bajo consumo o esperar tiempos mayores"},
    }


def calcular_ffmpeg(d, medido):
    info = ffmpeg_elegido(d)
    m = medido.get("ffmpeg", {})
    avisos = []
    if not info:
        return {"disponible": False, "avisos": ["No hay ffmpeg: instala uno (por ejemplo con Homebrew) o apunta RENDIMIENTO_FFMPEG."]}, avisos
    tiene_vt = "h264_videotoolbox" in info["codificadores_videotoolbox"]
    swift_ok = d.get("video") is not None

    # Decodificacion
    hw_dec_fmt = hw_decodifica(d, "h264") or hw_decodifica(d, "hevc")
    formula_dec = "videotoolbox" in info["hwaccels"] and (hw_dec_fmt if swift_ok else True)
    dec = m.get("decodificacion")
    if vale(dec):
        usa_dec, o_dec = dec.get("metodo") == "videotoolbox", origen(dec)
    else:
        usa_dec, o_dec = bool(formula_dec), "formula"

    # Codificacion
    hw_enc = hw_codifica(d, "avc1")
    formula_enc = "h264_videotoolbox" if tiene_vt and (hw_enc if swift_ok else True) else (
        "libx264" if info["libx264"] else None)
    cod = m.get("codificacion")
    if vale(cod):
        metodo, o_enc = cod.get("metodo"), origen(cod)
        b_final = cod.get("bitrate_final", BITRATE_FINAL)
        b_previa = cod.get("bitrate_vista_previa", BITRATE_PREVIA)
    else:
        metodo, o_enc, b_final, b_previa = formula_enc, "formula", BITRATE_FINAL, BITRATE_PREVIA
    if not swift_ok and metodo == "h264_videotoolbox" and o_enc == "formula":
        avisos.append("Sin Swift no se pudo confirmar el codificador por hardware; -allow_sw 0 hace que ffmpeg falle en vez de caer a CPU sin avisar.")

    entrada = ["-nostdin"] + (["-hwaccel", "videotoolbox"] if usa_dec else [])
    if metodo == "h264_videotoolbox":
        final = ["-c:v", "h264_videotoolbox", "-b:v", b_final, "-allow_sw", "0"]
        previa = ["-c:v", "h264_videotoolbox", "-b:v", b_previa, "-allow_sw", "0"]
    elif metodo == "libx264":
        final = previa = ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    else:
        final = previa = []
        avisos.append("Este ffmpeg no trae libx264 ni h264_videotoolbox: usa otro ffmpeg.")

    # HDR -> SDR
    hdr = m.get("hdr_sdr", {})
    scale_vt_ok = info["scale_vt"] and hdr.get("scale_vt") == "validado"
    if scale_vt_ok:
        hdr_txt = "scale_vt por hardware (validado en este equipo, %s)" % hdr.get("fecha", "sin fecha")
    else:
        hdr_txt = "zscale+tonemap en CPU, una sola vez por tramo, guardado y reutilizado"
        if not (info["zscale"] and info["tonemap"]):
            avisos.append("Este ffmpeg no trae zscale o tonemap: el paso HDR a SDR necesita otro ffmpeg.")

    # ProRes para intermedios: el motor de ProRes si el chip lo trae (M1 Pro/Max, y los base desde M2)
    if hw_codifica(d, "apcn") and "prores_videotoolbox" in info["codificadores_videotoolbox"]:
        prores = {"args": ["-c:v", "prores_videotoolbox", "-profile:v", "hq", "-allow_sw", "0"], "hardware": True, "origen": "formula (detectado)"}
    else:
        prores = {"args": ["-c:v", "prores_ks", "-profile:v", "3"], "hardware": False,
                  "origen": "formula (sin motor de ProRes detectado)" if hw_codifica(d, "apcn") is False else "formula"}
    return {
        "disponible": True,
        "binario": info["ruta"],
        "version": info["version"],
        "decodificacion": {"hardware": usa_dec, "origen": o_dec},
        "codificador": {"metodo": metodo, "origen": o_enc},
        "args_entrada": entrada,
        "args_final": final,
        "args_vista_previa": previa,
        "hdr_a_sdr": {"metodo": hdr_txt, "origen": origen(hdr) if scale_vt_ok else "formula"},
        "decodificacion_por_codec": arq.decodificacion_por_codec(d, usa_dec),
        "prores": prores,
        "ejemplo": " ".join([info["ruta"]] + entrada + ["-i", "ENTRADA"] + final + ["SALIDA.mp4"]),
    }, avisos


def nucleos_para_render(cpu):
    """Nucleos fisicos de los niveles que no son de eficiencia, y sus nombres.

    Hasta el M4 eran el nivel 0 ("Performance"). Desde el M5 Pro hay chips con dos niveles rapidos
    ("Super" y "Performance", con o sin "Efficiency") y Remotion aprovecha los dos. Si algun nivel
    no trae nombre no se puede saber cual es de eficiencia, y se usa solo el nivel 0.
    """
    niveles = cpu.get("niveles") or []
    if not niveles:
        return cpu.get("logicalcpu") or 2, []
    if all(n.get("nombre") for n in niveles):
        rapidos = [n for n in niveles if "efficien" not in n["nombre"].lower()] or niveles[:1]
    else:
        rapidos = niveles[:1]
    total = sum(n.get("nucleos_fisicos") or 0 for n in rapidos) or cpu.get("logicalcpu") or 2
    return total, [n.get("nombre") or "nivel %s" % n.get("indice", 0) for n in rapidos]


REMOTION_H264_HW = (4, 0, 236)  # --hardware-acceleration con H.264 y H.265 (ProRes desde 4.0.228), segun Remotion


def version_remotion(d):
    """Version de Remotion del proyecto inspeccionado (--proyecto), como tupla, o None si no se sabe."""
    v = ((d.get("herramientas") or {}).get("remotion") or {}).get("version")
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else None


def concurrencia_remotion(nucleos, renders):
    unico = max(1, round(nucleos * FRACCION_UN_RENDER))
    reparto = max(1, int(nucleos * FRACCION_TOTAL) // max(1, renders))
    return min(unico, reparto)


def calcular_remotion(d, medido, renders, frenos):
    m = medido.get("remotion", {})
    nucleos, niveles_render = nucleos_para_render(d.get("cpu") or {})
    efectivos = renders
    notas = []
    if frenos["memoria"]["activo"]:
        efectivos = 1
        notas.append("freno de memoria: renders en serie")
    if frenos["termico"]["activo"]:
        efectivos = max(1, efectivos // 2)
    conc = None
    mc = (m.get("concurrencia_por_render") or {}).get(str(efectivos)) if isinstance(m.get("concurrencia_por_render"), dict) else None
    if isinstance(mc, int) and mc > 0:
        conc, o_conc = mc, "medido"
    else:
        conc, o_conc = concurrencia_remotion(nucleos, efectivos), "formula"
    if frenos["termico"]["activo"]:
        conc = max(1, conc // 2)
        notas.append("freno termico (%s): mitad de concurrencia" % frenos["termico"]["estado"])
    flags = ["--concurrency=%d" % conc]

    # Codificador por hardware
    hw = m.get("hardware_acceleration")
    hw_enc = hw_codifica(d, "avc1")
    rv = version_remotion(d)
    if rv and rv < REMOTION_H264_HW and not vale(hw):
        o_hw = "formula (Remotion %s: codifica H.264 por hardware desde 4.0.236; actualiza el proyecto)" % ".".join(map(str, rv))
    elif vale(hw):
        valor = hw.get("valor", "required")
        if valor in ("required", "if-possible"):
            flags += ["--hardware-acceleration=%s" % valor,
                      "--video-bitrate=%s" % hw.get("video_bitrate", BITRATE_FINAL)]
        o_hw = "%s%s [%s]" % (valor, (", " + hw.get("video_bitrate", BITRATE_FINAL)) if valor in ("required", "if-possible") else "", origen(hw))
    elif hw_enc or (hw_enc is None and d.get("video") is None and ffmpeg_elegido(d)):
        flags += ["--hardware-acceleration=required", "--video-bitrate=%s" % BITRATE_FINAL]
        o_hw = "required, %s [formula]" % BITRATE_FINAL
    else:
        o_hw = "formula (sin codificador H.264 por hardware: usa el codec por defecto de Remotion)"

    # Cache de OffthreadVideo (por render, repartida)
    memsize = (d.get("memoria") or {}).get("memsize")
    cache = None
    if memsize:
        cache = int(memsize * FRACCION_CACHE) // max(1, renders)
        cache -= cache % (1024 * 1024)
        flags.append("--offthreadvideo-cache-size-in-bytes=%d" % cache)

    gl = m.get("gl")
    if vale(gl) and gl.get("valor"):
        flags.append("--gl=%s" % gl["valor"])
        o_gl = origen(gl)
    else:
        o_gl = "pendiente: no se pasa --gl hasta medirlo (medir.py remotion, sin otros renders en marcha)"
    return {
        "renders_pedidos": renders,
        "renders_en_paralelo": efectivos,
        "nucleos_para_render": nucleos,
        "niveles_para_render": niveles_render,
        "concurrencia_por_render": conc,
        "origen_concurrencia": o_conc,
        "flags": flags,
        "hardware_acceleration": o_hw,
        "offthreadvideo_cache_bytes": cache,
        "gl": o_gl,
        "reglas": ["No pasar --crf junto con --hardware-acceleration: crf la desactiva y cae a libx264 sin avisar.",
                   "No tocar los hilos de OffthreadVideo (--offthreadvideo-video-threads): se dejan en 2."],
        "notas": notas,
    }


def calcular_whisper(d, medido, avisos):
    h = (d.get("herramientas") or {}).get("whisper") or {}
    m = medido.get("whisper", {})
    servidores, modelos = h.get("servidores", []), h.get("modelos", [])
    if not servidores or not modelos:
        avisos.append("Whisper: falta %s." % ("el servidor" if not servidores else "un modelo ggml-*.bin"))
        return {"disponible": False}
    s, mod = servidores[0], modelos[0]
    metal_ok = bool((d.get("gpu") or {}).get("metal")) and "metal" in s["backends_junto_al_binario"]
    b = m.get("backend")
    if vale(b):
        backend, o = b.get("valor", "metal"), origen(b)
    else:
        backend, o = ("metal" if metal_ok else "cpu"), "formula"
    procs = d.get("procesos_pesados") or []
    propios = [p for p in procs if p["tipo"] == "whisper-server" and p["clase"] == "propio"]
    ocupados = {p["puerto"] for p in procs if p.get("puerto")}
    puerto = propios[0]["puerto"] if propios else puerto_libre(ocupados)
    cmd = "%s -m %s --port %s" % (s["ruta"], mod["ruta"], puerto)
    return {
        "disponible": True,
        "servidores": 1,
        "backend": backend,
        "origen": o,
        "servidor": s["ruta"],
        "modelo": mod["ruta"],
        "reutilizar_propio": ("puerto %s (pid %s)" % (propios[0]["puerto"], propios[0]["pid"])) if propios else None,
        "puerto_sugerido": puerto,
        "comando": cmd,
        "coreml_disponible": mod["encoder_coreml"],
        "nota": "El servidor serializa las peticiones: un segundo no suma velocidad y duplica el modelo en memoria.",
    }


def calcular(d, renders):
    huella = d.get("huella")
    medido, ruta_medido = cargar_medido(huella)
    avisos = list(d.get("avisos", []))
    if d.get("soporte"):
        return {"huella": huella, "soporte": d["soporte"], "recomendaciones": None,
                "medido": medido or None, "perfil_medido": ruta_medido,
                "avisos": avisos, "bloque_subagentes": bloque_sin_medir(d)}
    frenos = calcular_frenos(d, medido)
    ffmpeg, a = calcular_ffmpeg(d, medido)
    avisos += a
    remotion = calcular_remotion(d, medido, renders, frenos)
    whisper = calcular_whisper(d, medido, avisos)
    ne = (d.get("neural_engine") or {}).get("nucleos")
    segm = {"motor": "Vision de macOS (elige Neural Engine o GPU solo)",
            "apis": ["VNGenerateForegroundInstanceMaskRequest", "VNGeneratePersonSegmentationRequest"],
            "nucleos_neural_engine": ne,
            "nota": "No instalar modelos de Python para recortar."}
    chrome = medido.get("carrusel_chrome")
    chrome_rec = None
    if vale(chrome):
        chrome_rec = {"flags": [chrome["flag"]] if chrome.get("flag") else [], "origen": origen(chrome),
                      "nota": chrome.get("nota")}
    if frenos["bajo_consumo"]["activo"]:
        avisos.append("Modo de bajo consumo activo: " + frenos["bajo_consumo"]["accion"])
    if frenos["memoria"]["activo"]:
        avisos.append("Freno de memoria: " + "; ".join(frenos["memoria"]["motivos"]) + ". " + frenos["memoria"]["accion"])
    if frenos["termico"]["activo"]:
        avisos.append("Freno termico (%s): %s" % (frenos["termico"]["estado"], frenos["termico"]["accion"]))
    if not medido:
        avisos.append("Sin perfil medido para esta huella: todo viene de formula. Mide con medir.py y registra con --registrar.")
    perfil = {
        "huella": huella,
        "renders": renders,
        "fuente": "formula+medido" if medido else "formula",
        "perfil_medido": ruta_medido,
        "frenos": frenos,
        "ffmpeg": ffmpeg,
        "remotion": remotion,
        "whisper": whisper,
        "segmentacion": segm,
        "carrusel_chrome": chrome_rec,
        "lotes": {"qos_fondo": "taskpolicy -c utility <comando>" if (d.get("herramientas") or {}).get("taskpolicy") else None},
        "arquitectura": {"saltos": arq.saltos(d), "codificaciones_paralelas": arq.codificaciones_paralelas(d, medido)},
        "avisos": avisos,
    }
    perfil["bloque_subagentes"] = bloque_subagentes(d, perfil)
    return perfil


# ---------------------------------------------------------------- salida

def bloque_subagentes(d, p):
    f, r, w = p["ffmpeg"], p["remotion"], p["whisper"]
    L = ["Rendimiento (skill rendimiento-equipo; equipo %s, perfil %s):" % (p["huella"], p["fuente"])]
    if f.get("disponible"):
        dec = "decodifica con -hwaccel videotoolbox (antes de -i)" if f["decodificacion"]["hardware"] else "decodifica en CPU"
        L.append("- ffmpeg: %s, siempre con -nostdin; %s. Finales: %s. Vistas previas: %s."
                 % (f["binario"], dec, " ".join(f["args_final"]) or "(sin codificador)",
                    " ".join(f["args_vista_previa"]) or "(sin codificador)"))
        L.append("- HDR a SDR: %s." % f["hdr_a_sdr"]["metodo"])
        dpc = f.get("decodificacion_por_codec") or {}
        if dpc:
            L.append("- Lectura por codec: %s." % ", ".join("%s %s" % (k, "por hardware" if v == "videotoolbox" else "en CPU") for k, v in dpc.items()))
        L.append("- Intermedios ProRes: %s." % " ".join(f["prores"]["args"]))
        cp = p["arquitectura"]["codificaciones_paralelas"]
        if cp.get("valor"):
            L.append("- Codificaciones por hardware a la vez: %d como maximo (%s); mas no rinde mas." % (cp["valor"], cp["origen"]))
        elif cp.get("referencia"):
            L.append("- Codificaciones por hardware a la vez: sin medir (%s). Sin medir, no lances mas que esa cantidad." % cp["referencia"])
    L.append("- Remotion (renders en paralelo: %d), cada render con: %s. Sin --crf junto al hardware."
             % (r["renders_en_paralelo"], " ".join(r["flags"])))
    if w.get("disponible"):
        extra = ("Ya hay uno propio vivo: reutilizalo (%s)." % w["reutilizar_propio"]) if w["reutilizar_propio"] else \
            "Si necesitas uno, lanza este (y solo este): %s" % w["comando"]
        L.append("- Whisper (backend %s): un solo servidor para todos los agentes; los tiempos por palabra se leen de "
                 "archivos ya calculados. %s" % (w["backend"], extra))
    L.append("- Recortes de personas u objetos: Vision de macOS (Swift), no modelos de Python.")
    if p["carrusel_chrome"]:
        L.append("- Laminas de carrusel con Chrome sin ventana: %s." % " ".join(p["carrusel_chrome"]["flags"] or ["sin flags extra"]))
    fr = [k for k in ("memoria", "termico", "bajo_consumo") if p["frenos"][k]["activo"]]
    if fr:
        L.append("- Frenos activos (%s): %s" % (", ".join(fr), "; ".join(p["frenos"][k]["accion"] for k in fr)))
    L.append("- Nunca toques procesos de OpenWhispr (whisper-server con --model y --host). Apaga por PID, con SIGTERM, "
             "solo lo que lanzaste tu. Reporta cuanto tardo el render final y adjunta el comando y su salida como evidencia.")
    return "\n".join(L)


def bloque_sin_medir(d):
    """Encargo para subagentes en un sistema sin recomendaciones medidas: solo reglas que no dependen del equipo."""
    L = ["Rendimiento (skill rendimiento-equipo; equipo %s, %s %s: sin recomendaciones medidas):"
         % (d.get("huella"), (d.get("so") or {}).get("nombre"), d.get("arquitectura")),
         "- No fijes codificadores, aceleradores ni concurrencias a mano: usa los valores por defecto de cada herramienta.",
         "- Whisper: un solo servidor para todos los agentes; un segundo no suma velocidad y duplica el modelo en memoria.",
         "- Nunca toques procesos de OpenWhispr. Apaga por PID solo lo que lanzaste tu.",
         "- Reporta cuanto tardo cada tarea y adjunta el comando y su salida como evidencia."]
    return "\n".join(L)


def resumen_sin_medir(d):
    """Lo que el diagnostico vio en un sistema sin recomendaciones medidas (Windows)."""
    L = []
    cpu, mem, gpu = d.get("cpu") or {}, d.get("memoria") or {}, d.get("gpu") or {}
    if cpu.get("niveles"):
        L.append("  CPU            %s | %s (%s logicos)" % (cpu.get("marca"), " + ".join(
            "%s %s" % (n["nombre"], n["nucleos_fisicos"]) for n in cpu["niveles"]), cpu.get("logicalcpu")))
    if mem.get("memsize_gb"):
        sw = mem.get("swap") or {}
        L.append("  Memoria        %s GB | libre %s%% | paginacion %s de %s MB | creciendo: %s" % (
            mem["memsize_gb"], mem.get("libre_porcentaje"), sw.get("usado_mb"), sw.get("total_mb"),
            {True: "si", False: "no", None: "sin datos"}[mem.get("swap_creciendo")]))
    for g in gpu.get("adaptadores") or []:
        L.append("  GPU            %s (%s) | %s | controlador %s" % (
            g.get("nombre"), g.get("fabricante"), ("%s MB" % g["vram_mb"]) if g.get("vram_mb") else "VRAM sin dato",
            g.get("controlador")) + (" | virtual" if g.get("virtual") else ""))
    vid = d.get("video") or {}
    for titulo, clave in (("Codifica (HW)", "codificadores"), ("Decodifica (HW)", "decodificadores")):
        r = vid.get(clave) or {}
        if r:
            si = [k for k, v in r.items() if v["abre"]]
            no = [k for k, v in r.items() if not v["abre"]]
            L.append("  %-14s abre: %s | no abre: %s" % (titulo, " ".join(si) or "ninguno", " ".join(no) or "ninguno"))
    ne = d.get("neural_engine") or {}
    if "dispositivos" in ne:
        L.append("  NPU            %s" % (", ".join(ne["dispositivos"]) or "no se detecto"))
    if d.get("energia"):
        e = d["energia"]
        L.append("  Energia        enchufado: %s | ahorro de energia: %s" % (
            {True: "si", False: "no", None: "sin dato"}[e.get("enchufado")], "si" if e.get("ahorro_energia") else "no"))
    return L


def a_texto(d, p):
    if p.get("soporte"):
        so = d.get("so") or {}
        L = ["EQUIPO  %s %s | %s | huella %s" % (so.get("nombre"), so.get("edicion") or so.get("version") or "",
                                                  d.get("arquitectura"), d.get("huella")),
             "  %s." % p["soporte"]]
        L.extend(resumen_sin_medir(d))
        if p.get("medido"):
            L.append("")
            L.append("MEDIDO en este equipo (%s): %s" % (p.get("perfil_medido"), json.dumps(p["medido"], ensure_ascii=False)))
        L.append("")
        L.append("No hay recomendaciones medidas para este sistema todavia. Para medir este equipo:")
        L.append("  python medir.py codificar --archivo <video> --registrar")
        L.append("  python medir.py decodificar --archivo <video> --registrar")
        L.append("Lee references/windows.md.")
        if p.get("avisos"):
            L.append("")
            L.append("AVISOS")
            L.extend("  - " + a for a in p["avisos"])
        L.append("")
        L.append("BLOQUE PARA SUBAGENTES (pegar en el encargo)")
        L.append("-" * 60)
        L.append(p["bloque_subagentes"])
        L.append("-" * 60)
        return "\n".join(L)
    cpu, mem, gpu = d["cpu"], d["memoria"], d["gpu"]
    niv = " + ".join("%s %s" % (n["nombre"], n["nucleos_fisicos"]) for n in cpu["niveles"]) or "sin niveles"
    sw = mem.get("swap") or {}
    metal = gpu.get("metal") or {}
    vid = d.get("video") or {}
    cod = vid.get("codificadores") or {}
    dec = vid.get("decodificadores_hw") or {}
    dec_si = [k for k, v in dec.items() if v]
    dec_no = [k for k, v in dec.items() if not v]
    L = []
    L.append("EQUIPO  %s %s | %s | %s | huella %s" % (d["so"]["nombre"], d["so"]["version"], d["arquitectura"], cpu.get("marca"), d["huella"]))
    L.append("  CPU            %s (%s logicos)" % (niv, cpu.get("logicalcpu")))
    L.append("  Memoria        %s GB | presion %s | libre %s%% | swap %s de %s MB | swap creciendo: %s" % (
        mem.get("memsize_gb"), mem.get("presion"), mem.get("libre_porcentaje"), sw.get("usado_mb"), sw.get("total_mb"),
        {True: "si", False: "no", None: "sin datos"}[mem.get("swap_creciendo")]))
    L.append("  GPU            %s nucleos | Metal %s | memoria unificada: %s" % (
        gpu.get("nucleos"), metal.get("familia_apple_maxima", "sin datos"), metal.get("hasUnifiedMemory", "sin datos")))
    L.append("  Video (HW)     codificadores %s de %s | decodifica: %s%s" % (
        cod.get("por_hardware", "?"), cod.get("total", "?"), " ".join(dec_si) or "sin datos",
        (" (no: %s)" % " ".join(dec_no)) if dec_no else ""))
    L.append("  Neural Engine  %s nucleos | termico %s | bajo consumo: %s" % (
        (d.get("neural_engine") or {}).get("nucleos", "sin datos"), d.get("termico"), "si" if d.get("bajo_consumo") else "no"))
    fr = p["frenos"]
    L.append("")
    L.append("FRENOS  memoria: %s | termico: %s | bajo consumo: %s" % tuple(
        ("ACTIVO" if fr[k]["activo"] else "libre") for k in ("memoria", "termico", "bajo_consumo")))
    f = p["ffmpeg"]
    L.append("")
    L.append("FFMPEG  (%s)" % p["fuente"])
    if f.get("disponible"):
        L.append("  binario        %s (%s)" % (f["binario"], f["version"]))
        L.append("  decodificar    %s [%s]" % ("-hwaccel videotoolbox" if f["decodificacion"]["hardware"] else "CPU", f["decodificacion"]["origen"]))
        L.append("  codificar      %s [%s]" % (f["codificador"]["metodo"], f["codificador"]["origen"]))
        L.append("  final          %s" % " ".join(f["args_final"]))
        L.append("  vista previa   %s" % " ".join(f["args_vista_previa"]))
        L.append("  HDR a SDR      %s" % f["hdr_a_sdr"]["metodo"])
        dpc = f.get("decodificacion_por_codec") or {}
        if dpc:
            L.append("  por codec      %s" % " | ".join("%s %s" % (k, "HW" if v == "videotoolbox" else "CPU") for k, v in dpc.items()))
            for k, v in dpc.items():
                if v.startswith("cpu ("):
                    L.append("  %-14s %s: %s" % ("", k, v[5:-1]))
        L.append("  ProRes         %s [%s]" % (" ".join(f["prores"]["args"]), f["prores"]["origen"]))
    else:
        L.append("  no disponible")
    a = p["arquitectura"]
    cp = a["codificaciones_paralelas"]
    L.append("")
    L.append("ARQUITECTURA  (lo que trae este chip y que hace la skill con cada cosa)")
    for s in a["saltos"]:
        L.append("  %-14s %s" % (s["modulo"], s["salto"]))
        L.append("  %-14s -> %s [%s]" % ("", s["uso"], s["nivel"]))
    if cp.get("valor"):
        L.append("  %-14s %d a la vez como maximo [%s]%s" % ("Codif. HW", cp["valor"], cp["origen"],
                 (" | rinde: " + ", ".join("%s=%sx" % (k, v) for k, v in sorted(cp["escalado"].items(), key=lambda x: int(x[0])))) if cp.get("escalado") else ""))
    else:
        L.append("  %-14s sin medir%s. Mide: %s" % ("Codif. HW", (" (" + cp["referencia"] + ")") if cp.get("referencia") else "", cp["medir"]))
    r = p["remotion"]
    L.append("")
    L.append("REMOTION  %d render(es) pedidos, %d en paralelo" % (r["renders_pedidos"], r["renders_en_paralelo"]))
    L.append("  concurrencia   %d por render (nucleos para render: %d, %s) [%s]" % (
        r["concurrencia_por_render"], r["nucleos_para_render"], " + ".join(r["niveles_para_render"]) or "sin niveles",
        r["origen_concurrencia"]))
    L.append("  flags          %s" % " ".join(r["flags"]))
    L.append("  hardware       %s" % r["hardware_acceleration"])
    L.append("  --gl           %s" % r["gl"])
    w = p["whisper"]
    L.append("")
    L.append("WHISPER")
    if w.get("disponible"):
        L.append("  1 servidor, backend %s [%s]" % (w["backend"], w["origen"]))
        L.append("  %s" % (("reutilizar el propio vivo en " + w["reutilizar_propio"]) if w["reutilizar_propio"] else "lanzar: " + w["comando"]))
    else:
        L.append("  no disponible")
    if p["carrusel_chrome"]:
        L.append("")
        L.append("CARRUSEL (Chrome sin ventana)  %s [%s]" % (" ".join(p["carrusel_chrome"]["flags"]), p["carrusel_chrome"]["origen"]))
    if p["avisos"]:
        L.append("")
        L.append("AVISOS")
        L.extend("  - " + a for a in p["avisos"])
    L.append("")
    L.append("BLOQUE PARA SUBAGENTES (pegar en el encargo)")
    L.append("-" * 60)
    L.append(p["bloque_subagentes"])
    L.append("-" * 60)
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Recomendaciones de rendimiento para este equipo: formula + lo medido (lo medido gana).")
    ap.add_argument("--renders", type=int, default=1, help="cuantos renders de Remotion se lanzaran en paralelo (por defecto 1)")
    ap.add_argument("--formato", choices=("json", "texto"), default="json", help="formato de salida (por defecto json)")
    ap.add_argument("--diagnostico", help="usa este archivo JSON de diagnosticar.py en vez de volver a diagnosticar")
    ap.add_argument("--proyecto", help="ruta de un proyecto Remotion (se pasa a diagnosticar.py)")
    ap.add_argument("--sin-estado", action="store_true", help="no guardar la muestra de swap")
    args = ap.parse_args(argv)
    if args.renders < 1:
        print("error: --renders debe ser 1 o mas", file=sys.stderr)
        return 2
    if args.diagnostico:
        d = dg.leer_json(os.path.expanduser(args.diagnostico))
        if not isinstance(d, dict) or "huella" not in d:
            print("error: %s no es un diagnostico valido. Genera uno con: python3 %s > diag.json"
                  % (args.diagnostico, os.path.join(AQUI, "diagnosticar.py")), file=sys.stderr)
            return 2
    else:
        d = dg.diagnosticar(args.proyecto, not args.sin_estado)
    p = calcular(d, args.renders)
    if args.formato == "texto":
        print(a_texto(d, p))
    else:
        print(json.dumps(p, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
