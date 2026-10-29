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


def paralelo(ruta, codigo):
    codigo = int(codigo)
    if codigo not in (0, 1):
        falla("medir.py paralelo salio con %s" % codigo)
    out = leer(ruta)
    uno = out["variantes"].get("1") or {}
    if uno.get("fallo"):
        falla("una sola codificacion fallo: %r" % uno)
    if out.get("elegido") is None or "1" not in out.get("escalado", {}):
        falla("sin escalado ni eleccion: %r" % out)
    print("OK paralelo: rinde %s, elige %s" % (out["escalado"], out["elegido"]))


def voz(ruta):
    d = leer(ruta)
    if len(d.get("modelos") or []) < 6:
        falla("catalogo de modelos de dictado vacio: %r" % d.get("catalogo"))
    if not d.get("recomendado"):
        falla("sin modelo recomendado con %s MB de presupuesto" % d.get("presupuesto_mb"))
    print("OK voz: %s recomienda %s (%s %% de error, %s MB)" % (d["catalogo"], d["recomendado"]["nombre"],
                                                              d["recomendado"]["wer"], d["recomendado"]["memoria_mb"]))


def voz_unidad():
    """Sin OpenWhispr: error con cifras y tildes, cliente WebSocket de sherpa-onnx y recomendacion con lo medido."""
    import base64
    import hashlib
    import socket
    import struct
    import threading
    import medir as m
    import voz as v
    w = m.wer("Midió doce modelos: 2,3 por ciento en 2026", "midio 12 modelos 2,3 % en dos mil veintiseis")
    if w != 0:
        falla("el error deberia ser 0 con cifras y tildes normalizadas: %r" % w)

    def servir(srv):
        c, _ = srv.accept()
        d = b""
        while b"\r\n\r\n" not in d:
            d += c.recv(4096)
        k = [x.split(b": ")[1] for x in d.split(b"\r\n") if x.lower().startswith(b"sec-websocket-key")][0]
        acc = base64.b64encode(hashlib.sha1(k + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n")
        buf = [b""]

        def leer_n(n):
            while len(buf[0]) < n:
                buf[0] += c.recv(65536)
            o, buf[0] = buf[0][:n], buf[0][n:]
            return o

        def rec():
            _, b2 = leer_n(2)
            n = b2 & 127
            n = struct.unpack(">H", leer_n(2))[0] if n == 126 else struct.unpack(">Q", leer_n(8))[0] if n == 127 else n
            mk = leer_n(4)
            return bytes(x ^ mk[i % 4] for i, x in enumerate(leer_n(n)))

        def env(p):
            c.sendall(bytes([0x81, len(p)]) + p)
        p = rec()
        tasa, nb = struct.unpack("<ii", p[:8])
        env(json.dumps({"text": "%d %d %d" % (tasa, nb, len(p) - 8)}).encode())
        if rec() == b"Done":
            env(b"Done!")
        c.close()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    threading.Thread(target=servir, args=(srv,), daemon=True).start()
    t = m._ws_offline(srv.getsockname()[1], b"\x00" * 200000, 20)
    if t != "16000 200000 200000":
        falla("cliente WebSocket: %r" % t)
    med = {"parakeet-tdt-0.6b-v3": {"wer": 2.3, "audio_id": "a", "veces_tiempo_real": 30, "memoria_mb": 700},
           "small": {"wer": 6.1, "audio_id": "a", "veces_tiempo_real": 25, "memoria_mb": 900}}
    r = v.recomendar(16 * 1024 ** 3, "es", med, False, True, {"ancho_banda_gbs": 153})
    if not r["recomendado"] or r["recomendado"]["id"] != "parakeet-tdt-0.6b-v3" or "medido" not in r["criterio"]:
        falla("con error medido en el mismo audio deberia elegir Parakeet: %r" % (r["recomendado"] or {}).get("id"))
    print("OK voz_unidad: error normalizado, WebSocket y recomendacion medida (%s)" % r["criterio"])


def cpu(ruta_diag):
    import medir as m
    ffmpeg = leer(ruta_diag)["herramientas"]["ffmpeg"]["elegido"]
    r = m.correr([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                  "testsrc2=size=1280x720:rate=30:duration=3", "-c:v", "libx264", "-f", "null", "-"])
    if r["rc"] != 0 or not r["cpu_s"] or r["cpu_s"] <= 0:
        falla("correr() no midio CPU: %r" % r)
    if r["cpu_s"] < 0.5 * r["real_s"]:  # libx264 usa al menos un nucleo entero: menos es medir un atajo y no ffmpeg
        falla("CPU sospechosamente baja para libx264: %r" % r)
    print("OK cpu: %r" % r)


if __name__ == "__main__":
    modo, resto = sys.argv[1], sys.argv[2:]
    {"diagnostico": diagnostico, "medir": medir, "cpu": cpu, "paralelo": paralelo, "voz": voz, "voz_unidad": voz_unidad}[modo](*resto)
