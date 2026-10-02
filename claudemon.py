#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""claudemon — controla cuánto gastás de Claude Code y qué sesión se lleva el cupo.

Mac, Linux y Windows · Python 3.8 o más nuevo · sin instalar nada para los informes
(solo la pantalla en vivo pide `pip install psutil`).

    claudemon                      pantalla en vivo
    claudemon sesiones             cada sesión con su NOMBRE, gasto y modelos
    claudemon modelos              quién usó cada modelo (tu conversación o los subagentes)
    claudemon comenzar / uso / reset    contador por períodos (ej. por semana)
    claudemon plan / semana / limites / calibrar    tu plan y qué tan cerca estás del tope
    claudemon demo                 mira cómo se ve con datos inventados
    claudemon diagnostico          revisa que todo esté bien instalado
    claudemon ayuda [tema]         explicaciones en castellano

Todo es de SOLO LECTURA: lee los archivos que Claude Code guarda en tu compu
(~/.claude/projects) y no envía nada a ningún lado.
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time

VERSION = "1.0.0"
ES_WIN = os.name == "nt"
CONFIG_CLAUDE = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
RAIZ = os.path.join(CONFIG_CLAUDE, "projects")
CARPETA = os.environ.get("CLAUDEMON_DIR") or os.path.join(CONFIG_CLAUDE, "monitor")
VENTANA = 24 * 3600                       # la pantalla en vivo mira las últimas 24 h
MAX_LEER_INICIAL = 60 * 1024 * 1024       # de los archivos enormes solo se lee el final al arrancar
ASCII = bool(os.environ.get("CLAUDEMON_ASCII"))
HORAS_BLOQUE = 5
PLANES = {"pro": ("Pro", 1), "max5": ("Max 5x", 5), "max20": ("Max 20x", 20)}
DIAS_SEM = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


# ================================================================ color
SIN_COLOR = os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb"


def _auto_color():
    """Color solo si hay una terminal (o si lo forzás con CLAUDEMON_COLOR=1) y no pediste lo contrario (NO_COLOR / --sin-color)."""
    if os.environ.get("CLAUDEMON_COLOR"):
        return True
    if SIN_COLOR:
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


COLOR = _auto_color()
# Colores pensados para fondo OSCURO (y legibles en claro): variantes brillantes y un gris medio (el «negro brillante» 90 y el modo tenue
# se pierden en una consola negra).
_CODIGOS = {"b": "1", "ul": "4", "inv": "7", "rojo": "91", "verde": "92", "amarillo": "93", "azul": "94",
            "magenta": "95", "cian": "96", "gris": "38;5;246", "dim": "38;5;246", "cab": "1;97;44",
            "fv": "1;30;102", "fa": "1;30;103", "fr": "1;97;101"}
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def c(txt, *estilos):
    """Pinta el texto (si hay color). El color se pone DESPUÉS de alinear, para no desalinear columnas."""
    estilos = [e for e in estilos if e]
    if not COLOR or not estilos or not txt:
        return txt
    return "\x1b[%sm%s\x1b[0m" % (";".join(_CODIGOS[e] for e in estilos), txt)


def sin_color(txt):
    return _ANSI.sub("", txt)


def recortar(txt, n):
    """Corta a n caracteres VISIBLES sin partir los códigos de color."""
    if "\x1b" not in txt:
        return txt[:n]
    out, vis = [], 0
    for m in re.finditer(r"(\x1b\[[0-9;?]*[A-Za-z])|(.)", txt, re.S):
        if m.group(1):
            out.append(m.group(1))
        elif vis < n:
            out.append(m.group(2))
            vis += 1
    return "".join(out) + "\x1b[0m"


def rel(txt, ancho, *estilos, der=False):
    """Celda de tabla: recorta, alinea a `ancho` y recién después pinta."""
    t = str(txt)[:ancho]
    return c(("%*s" if der else "%-*s") % (ancho, t), *estilos)


def color_pct(pct):
    return "verde" if pct < 60 else "amarillo" if pct < 85 else "rojo"


def est_modelo(nombre):
    m = (nombre or "").lower()
    return "magenta" if "opus" in m else "cian" if "sonnet" in m else "verde" if "haiku" in m else "amarillo" if "fable" in m else "gris"


def est_sub(pct):
    """Qué tan cargado de subagentes está el gasto (los subagentes suelen ser lo que dispara el consumo)."""
    return "magenta" if pct >= 80 else "amarillo" if pct >= 40 else "gris"


def marca(ok):
    return c("✔", "verde", "b") if ok else c("✖", "rojo", "b")


# ================================================================ utilidades de texto
def fmt(n):
    n = float(n)
    if n >= 1e9:
        return "%.1fG" % (n / 1e9)
    if n >= 1e6:
        return "%.1fM" % (n / 1e6)
    if n >= 1e3:
        return "%.0fk" % (n / 1e3)
    return "%.0f" % n


def parsear_cantidad(txt):
    m = re.fullmatch(r"\s*([\d.,]+)\s*([kKmMgG]?)\s*", txt or "")
    if not m:
        raise ValueError("no entiendo «%s» (ejemplos: 600M, 1.2G, 800000k)" % txt)
    return float(m.group(1).replace(",", ".")) * {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}[m.group(2).lower()]


def barra(pct, ancho=20, estilo=None):
    n = int(round(max(0, min(100, pct)) / 100 * ancho))
    lleno, vacio = ("#", "-") if ASCII else ("█", "░")
    return c(lleno * n, estilo or color_pct(pct)) + c(vacio * (ancho - n), "gris")


def linea_titulo(txt):
    raya = "=" if ASCII else "━"
    return c("%s %s %s" % (raya * 2, txt, raya * 2), "b", "cian")


def seccion(txt):
    return c(txt, "b", "ul")


def dur(seg):
    d, r = divmod(int(seg), 86400)
    h, r = divmod(r, 3600)
    return "%d d %d h" % (d, h) if d else "%d h %d min" % (h, r // 60)


def a_epoch(ts):
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def local(epoch):
    return datetime.datetime.fromtimestamp(epoch)


def _enc(txt):
    """Claude Code nombra la carpeta de cada proyecto con la ruta, cambiando todo lo que no es letra o número por «-»."""
    return re.sub(r"[^A-Za-z0-9]", "-", txt)


_HOME = _enc(os.path.expanduser("~"))
_CARPETAS = ("Projects", "projects", "Proyectos", "proyectos", "Documents", "Documentos", "Desktop", "Escritorio",
             "Developer", "dev", "code", "Code", "repos", "src", "work", "git", "GitHub", "github")


def corto_proyecto(nombre):
    """«-Users-ana-Projects-tienda--claude-worktrees-x» -> «tienda ⎇x»."""
    n = nombre
    if n == _HOME:
        return "~"
    if n.startswith(_HOME + "-"):
        n = n[len(_HOME) + 1:]
    for c in _CARPETAS:
        if n.startswith(c + "-"):
            n = n[len(c) + 1:]
            break
    n = n.replace("--claude-worktrees-", " [wt]" if ASCII else " ⎇")
    return (n.lstrip("-") or "~")[:26]


def abrev_modelo(m):
    """claude-sonnet-5-5 -> «Sonnet 5.5»; claude-opus-5-5[1m] -> «Opus 5.5 1M»."""
    m = (m or "").replace("claude-", "")
    if m in ("", "<synthetic>"):
        return "—"
    ctx = " 1M" if "[1m]" in m else ""
    mm = re.match(r"([a-z]+)-([\d-]+?)(?:-\d{8})?$", m.replace("[1m]", ""))
    return "%s %s%s" % (mm.group(1).capitalize(), mm.group(2).replace("-", "."), ctx) if mm else m[:16]


def familia(modelo):
    m = (modelo or "").lower()
    return "opus" if "opus" in m else "sonnet" if "sonnet" in m else "otros"


def nombre_sesion(S):
    """El nombre que ves en Claude Code: el que le pusiste (/rename), si no el que genera Claude, si no tu primer mensaje."""
    return S.get("custom") or S.get("ai") or S.get("titulo") or "(sin nombre)"


def texto_modelos(cuentas, total=None):
    """{'Sonnet 5.5': 120, 'Opus 5.5': 80} -> «Sonnet 5.5 60% · Opus 5.5 40%»"""
    total = total or sum(cuentas.values()) or 1
    sep = " | " if ASCII else " · "
    return sep.join("%s %s" % (c(m, est_modelo(m)), c("%.0f%%" % (100 * v / total), "gris")) for m, v in sorted(cuentas.items(), key=lambda x: -x[1])[:3]) or "—"


def sh(cmd, timeout=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


# ================================================================ lectura de las sesiones de Claude Code
def leer_linea(S, crudo, es_sub, agente=""):
    """Acumula en S una línea de sesión: nombre, costo registrado y uso de tokens (deduplicado por id de mensaje)."""
    if (b'"usage"' not in crudo and b'"custom-title"' not in crudo and b'"ai-title"' not in crudo and b'"cost-state"' not in crudo
            and (S.get("titulo") or es_sub or b'"type":"user"' not in crudo)):
        return
    try:
        d = json.loads(crudo)
    except Exception:
        return
    t = d.get("type")
    if t == "custom-title":
        if not es_sub and d.get("customTitle"):
            S["custom"] = d["customTitle"]
        return
    if t == "ai-title":
        if not es_sub and d.get("aiTitle"):
            S["ai"] = d["aiTitle"]
        return
    if t == "cost-state":                               # costo acumulado que calcula Claude Code (USD, equivalente de API)
        if not es_sub:
            S.setdefault("costos", []).append({
                "t": S.get("_ts", 0.0), "inicio": d.get("startTime"), "total": float(d.get("totalCostUSD") or 0),
                "modelos": {m: float((u or {}).get("costUSD") or 0) for m, u in (d.get("modelUsage") or {}).items()}})
        return
    if d.get("timestamp"):
        S["_ts"] = a_epoch(d["timestamp"])
    if t == "user" and not S.get("titulo") and not es_sub:
        c = (d.get("message") or {}).get("content")
        if isinstance(c, list):
            c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
        if isinstance(c, str) and c.strip() and not c.lstrip().startswith("<"):
            S["titulo"] = " ".join(c.split())[:70]
    m = d.get("message") or {}
    u = m.get("usage")
    if t != "assistant" or not u:
        return
    mid = m.get("id") or d.get("uuid")
    reg = {"t": a_epoch(d.get("timestamp", "")), "in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0),
           "cw": u.get("cache_creation_input_tokens", 0), "cr": u.get("cache_read_input_tokens", 0), "sub": es_sub,
           "modelo": m.get("model", ""), "agente": agente}
    previo = S["msgs"].get(mid)
    if not previo or reg["out"] >= previo["out"]:
        S["msgs"][mid] = reg
    if m.get("model") and m["model"] != "<synthetic>" and not es_sub:
        S["modelo"] = m["model"]                        # el modelo de TU conversación; los subagentes se cuentan aparte


def offset_desde(f, tamano, desde):
    """Búsqueda binaria del primer byte cuyo timestamp es >= `desde` (los archivos están en orden cronológico)."""
    lo, hi = 0, tamano
    while hi - lo > 2 * 1024 * 1024:
        mid = (lo + hi) // 2
        f.seek(mid)
        f.readline()
        ts = 0.0
        for _ in range(60):
            linea = f.readline()
            if not linea:
                break
            m = re.search(rb'"timestamp":"([^"]+)"', linea)
            if m:
                ts = a_epoch(m.group(1).decode())
                break
        if ts and ts < desde:
            lo = mid
        else:
            hi = mid
    return lo


def costo_previo(f, off):
    """Último registro de costo anterior al byte `off`: sirve para restar lo que se gastó antes del período."""
    ini = max(0, off - 24 * 1024 * 1024)
    f.seek(ini)
    datos = f.read(off - ini)
    i = datos.rfind(b'"cost-state"')
    if i < 0:
        return None
    a = datos.rfind(b"\n", 0, i) + 1
    b = datos.find(b"\n", i)
    try:
        d = json.loads(datos[a:b if b > 0 else None])
    except Exception:
        return None
    return {"inicio": d.get("startTime"), "total": float(d.get("totalCostUSD") or 0),
            "modelos": {m: float((u or {}).get("costUSD") or 0) for m, u in (d.get("modelUsage") or {}).items()}}


def escanear(desde, hasta=None):
    """Sesiones con su uso entre `desde` y `hasta` (epoch). Rápido aun con archivos de cientos de MB."""
    hasta = hasta or time.time() + 60
    sesiones = {}
    for ruta in glob.glob(os.path.join(RAIZ, "**", "*.jsonl"), recursive=True):
        try:
            st = os.stat(ruta)
        except OSError:
            continue
        if st.st_mtime < desde:
            continue
        rel = os.path.relpath(ruta, RAIZ).split(os.sep)
        clave = (rel[0], rel[1].replace(".jsonl", ""))
        S = sesiones.setdefault(clave, {"msgs": {}, "titulo": "", "modelo": "", "mtime": 0})
        S["mtime"] = max(S["mtime"], st.st_mtime)
        es_sub = "subagents" in rel
        agente = ""
        if es_sub:                                       # el tipo de agente (implementer, reviewer…) está en el .meta.json vecino
            try:
                with open(ruta.replace(".jsonl", ".meta.json"), encoding="utf-8") as g:
                    agente = json.load(g).get("agentType", "") or ""
            except Exception:
                agente = ""
        try:
            with open(ruta, "rb") as f:
                off = offset_desde(f, st.st_size, desde)
                if off and not es_sub:
                    prev = costo_previo(f, off)
                    if prev:
                        S["costo_prev"] = prev
                f.seek(off)
                if off:
                    f.readline()
                for crudo in f:
                    leer_linea(S, crudo, es_sub, agente)
        except OSError:
            continue
    for S in sesiones.values():
        S["msgs"] = {k: m for k, m in S["msgs"].items() if desde <= m["t"] <= hasta}
        S["costos"] = [c for c in S.get("costos", []) if c["t"] <= hasta]
    return sesiones


def costo_sesion(S):
    """USD del período según los registros «cost-state» de Claude Code (son acumulados: se resta lo anterior)."""
    ultimo = {}
    for c in S.get("costos", []):
        ultimo[c["inicio"]] = c                          # el último de cada corrida de la sesión
    prev = S.get("costo_prev")
    total, modelos = 0.0, collections.Counter()
    for ini, c in ultimo.items():
        mismo = bool(prev) and prev["inicio"] == ini
        total += max(0.0, c["total"] - (prev["total"] if mismo else 0.0))
        for m, v in c["modelos"].items():
            modelos[m] += max(0.0, v - (prev["modelos"].get(m, 0.0) if mismo else 0.0))
    return total, modelos


def resumir(sesiones):
    """Totales por proyecto, modelo, rol (conversación / subagentes), tipo de agente, día, sesión y costo."""
    R = {"tot": collections.Counter(), "proyectos": collections.defaultdict(collections.Counter), "modelos": collections.Counter(),
         "dias": collections.Counter(), "sesiones": [], "msgs": 0, "roles": collections.Counter(), "agentes": collections.Counter(),
         "usd": 0.0, "usd_modelos": collections.Counter(), "proy_modelos": collections.defaultdict(collections.Counter)}
    for (proyecto, sesion), S in sesiones.items():
        pes = sub = salida = cr = n = 0
        mp, ms, ag = collections.Counter(), collections.Counter(), collections.Counter()
        for m in S["msgs"].values():
            p = m["in"] + m["out"] + m["cw"]
            pes += p
            salida += m["out"]
            cr += m["cr"]
            n += 1
            mod = abrev_modelo(m["modelo"])
            R["dias"][local(m["t"]).strftime("%Y-%m-%d")] += p
            if mod == "—":
                continue
            R["modelos"][mod] += p
            R["proy_modelos"][proyecto][mod] += p
            if m["sub"]:
                sub += p
                ms[mod] += p
                tipo = m.get("agente") or "(sin tipo)"
                ag[(tipo, mod)] += p
                R["agentes"][(tipo, mod)] += p
                R["roles"][("subagentes", mod)] += p
            else:
                mp[mod] += p
                R["roles"][("conversación", mod)] += p
        usd, usd_m = costo_sesion(S)
        if not n and not usd:
            continue
        R["tot"]["nuevos"] += pes
        R["tot"]["salida"] += salida
        R["tot"]["cr"] += cr
        R["tot"]["sub"] += sub
        R["msgs"] += n
        R["usd"] += usd
        for m, v in usd_m.items():
            R["usd_modelos"][abrev_modelo(m)] += v
        P = R["proyectos"][proyecto]
        P["nuevos"] += pes
        P["sub"] += sub
        P["n"] += 1
        P["usd"] += usd
        R["sesiones"].append({"proyecto": proyecto, "sesion": sesion, "titulo": nombre_sesion(S), "nuevos": pes, "msgs": n, "sub": sub,
                              "mp": dict(mp), "ms": dict(ms), "ag": dict(ag), "usd": usd})
    R["sesiones"].sort(key=lambda s: -s["nuevos"])
    return R


# ================================================================ archivos de configuración del monitor
def ruta(nombre):
    os.makedirs(CARPETA, exist_ok=True)
    return os.path.join(CARPETA, nombre)


def cargar(nombre, defecto):
    try:
        with open(ruta(nombre), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def guardar(nombre, valor):
    with open(ruta(nombre), "w", encoding="utf-8") as f:
        json.dump(valor, f, ensure_ascii=False, indent=1)


# ================================================================ contador por períodos
def resumen_periodo(inicio, fin=None, nombre=""):
    R = resumir(escanear(inicio, fin))
    return {"nombre": nombre, "inicio": inicio, "fin": fin or time.time(), "nuevos": R["tot"]["nuevos"], "salida": R["tot"]["salida"],
            "cache_lect": R["tot"]["cr"], "subagentes": R["tot"]["sub"], "mensajes": R["msgs"],
            "proyectos": {p: dict(c) for p, c in R["proyectos"].items()}, "modelos": dict(R["modelos"]), "dias": dict(R["dias"]),
            "usd": R["usd"], "usd_modelos": dict(R["usd_modelos"])}, R


def imprimir_periodo(res, R, titulo, limite=None, anterior=None):
    ahora = res["fin"]
    dias = max((ahora - res["inicio"]) / 86400, 1 / 24)
    print(linea_titulo("%s: %s → %s  (%s)" % (titulo, local(res["inicio"]).strftime("%a %d/%m %H:%M"),
                                                local(ahora).strftime("%a %d/%m %H:%M"), dur(ahora - res["inicio"]))))
    sub_pct = 100 * res["subagentes"] / max(1, res["nuevos"])
    print("%s %s   %s %s   %s %s (%s)   %s %s   %s %d" % (
        c("Tokens nuevos:", "gris"), c(fmt(res["nuevos"]), "b"), c("salida:", "gris"), fmt(res["salida"]),
        c("subagentes:", "gris"), fmt(res["subagentes"]), c("%.0f%%" % sub_pct, est_sub(sub_pct)),
        c("lecturas de caché:", "gris"), fmt(res["cache_lect"]), c("mensajes:", "gris"), res["mensajes"]))
    print("%s %s/día" % (c("Ritmo:", "gris"), c(fmt(res["nuevos"] / dias), "b")) +
          ("  →  proyección a 7 días: %s" % c(fmt(res["nuevos"] / dias * 7), "b") if dias < 7 else ""))
    if res.get("usd"):
        print("%s %s %s → USD %s/día   %s" % (
            c("Costo registrado por Claude Code:", "gris"), c("USD " + format(res["usd"], ",.0f"), "amarillo", "b"),
            c("(equivalente de API, no tu factura)", "gris"), format(res["usd"] / dias, ",.0f"),
            " · ".join("%s %s" % (c(m, est_modelo(m)), c("$" + format(v, ",.0f"), "amarillo")) for m, v in sorted(res["usd_modelos"].items(), key=lambda x: -x[1])[:3])))
    if limite:
        pct = 100 * res["nuevos"] / limite
        resto = limite - res["nuevos"]
        agota = "; a este ritmo se agota en %s" % dur(resto / (res["nuevos"] / dias) * 86400) if resto > 0 and res["nuevos"] else ""
        print("Tope %s: usaste %s %s%s" % (fmt(limite), c("%.0f%%" % pct, color_pct(pct), "b"), barra(pct),
                                        agota if resto > 0 else c("  ¡SUPERADO!", "rojo", "b")))
    if anterior:
        d = anterior["nuevos"]
        print("Período anterior «%s»: %s en %s → ahora vas al %.0f%% de ese total" % (
            anterior["nombre"], fmt(d), dur(anterior["fin"] - anterior["inicio"]), 100 * res["nuevos"] / max(1, d)))
    print("\n" + seccion("Por proyecto (tokens nuevos):"))
    for p, cu in sorted(R["proyectos"].items(), key=lambda x: -x[1]["nuevos"])[:10]:
        usd = "  " + rel("$" + format(cu["usd"], ",.0f"), 6, "amarillo", der=True) if cu.get("usd") else ""
        print("  %s %s%s  %s %s  %s %2d  %s" % (rel(fmt(cu["nuevos"]), 8, "b", der=True), c("%4.0f%%" % (100 * cu["nuevos"] / max(1, res["nuevos"])), "gris"), usd,
                                              c("subagentes", "gris"), rel(fmt(cu["sub"]), 7, der=True), c("sesiones", "gris"), cu["n"],
                                              c(corto_proyecto(p), "b")))
    print("\n" + seccion("Por modelo (quién lo usó: tu conversación o los subagentes):"))
    for m, v in sorted(res["modelos"].items(), key=lambda x: -x[1])[:6]:
        conv, sub = R["roles"].get(("conversación", m), 0), R["roles"].get(("subagentes", m), 0)
        print("  %s %s  %s %s %s · %s %s" % (rel(fmt(v), 8, "b", der=True), c("%4.0f%%" % (100 * v / max(1, res["nuevos"])), "gris"), rel(m, 14, est_modelo(m)),
                                           c("conversación", "gris"), rel(fmt(conv), 7, der=True), c("subagentes", "gris"), rel(fmt(sub), 7, der=True)))
    print("\n" + seccion("Por día:"))
    mx = max(res["dias"].values(), default=1)
    for dia, v in sorted(res["dias"].items()):
        print("  %s  %s  %s" % (c(dia, "gris"), rel(fmt(v), 8, "b", der=True), c(("#" if ASCII else "█") * int(v / mx * 30), "cian")))
    print("\n" + seccion("Sesiones que más gastaron") + c(" (nombre · modelo de la conversación → modelo de sus subagentes):", "gris"))
    for x in R["sesiones"][:8]:
        usd = rel("$" + format(x["usd"], ",.0f"), 6, "amarillo", der=True) + " " if x.get("usd") else "       "
        print("  %s %s%s %s %s → %s  %s" % (rel(fmt(x["nuevos"]), 8, "b", der=True), usd, rel(corto_proyecto(x["proyecto"]), 24, "b"), rel(x["titulo"], 40),
                                         texto_modelos(x["mp"]), texto_modelos(x["ms"]), c("[%s]" % x["sesion"][:8], "gris")))


def cmd_comenzar(nombre):
    p = cargar("periodo.json", None)
    if p:
        print("Ya hay un período abierto desde %s («%s»). Usá «claudemon reset» para cerrarlo y empezar otro." % (
            local(p["inicio"]).strftime("%d/%m %H:%M"), p["nombre"]))
        return
    nombre = nombre or "período %s" % local(time.time()).strftime("%d/%m")
    guardar("periodo.json", {"nombre": nombre, "inicio": time.time()})
    print("✔ Período «%s» iniciado ahora (%s). Mirá el avance con «claudemon uso»." % (nombre, local(time.time()).strftime("%a %d/%m %H:%M")))


def _historial_periodos():
    hist = []
    if os.path.exists(ruta("periodos.jsonl")):
        with open(ruta("periodos.jsonl"), encoding="utf-8") as f:
            for linea in f:
                try:
                    hist.append(json.loads(linea))
                except Exception:
                    pass
    return hist


def cmd_uso():
    p = cargar("periodo.json", None)
    if not p:
        print("No hay período abierto. Empezá uno con «claudemon comenzar».")
        return
    res, R = resumen_periodo(p["inicio"], None, p["nombre"])
    hist = _historial_periodos()
    imprimir_periodo(res, R, "«%s» (abierto)" % p["nombre"], cargar("config.json", {}).get("limite"), hist[-1] if hist else None)


def cmd_reset(nombre):
    p = cargar("periodo.json", None)
    ahora = time.time()
    if p:
        res, R = resumen_periodo(p["inicio"], ahora, p["nombre"])
        imprimir_periodo(res, R, "CERRADO «%s»" % p["nombre"], cargar("config.json", {}).get("limite"))
        with open(ruta("periodos.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
        print("\n%s Guardado en el historial de períodos." % marca(True))
    else:
        print("(no había período abierto)")
    nombre = nombre or "período %s" % local(ahora).strftime("%d/%m")
    guardar("periodo.json", {"nombre": nombre, "inicio": ahora})
    print("%s Nuevo período «%s» iniciado ahora." % (marca(True), nombre))


def cmd_periodos():
    hist = _historial_periodos()
    if not hist:
        print("Todavía no cerraste ningún período (usá «claudemon reset» al terminar uno).")
        return
    print(c("%-22s %-12s %-9s %8s %8s %7s  %s" % ("PERÍODO", "DESDE", "DURÓ", "NUEVOS", "POR DÍA", "SUBAG.", "PROYECTO PRINCIPAL"), "dim", "b"))
    for r in hist:
        d = max((r["fin"] - r["inicio"]) / 86400, 1 / 24)
        top = max(r["proyectos"].items(), key=lambda x: x[1]["nuevos"])[0] if r["proyectos"] else "-"
        sp = 100 * r["subagentes"] / max(1, r["nuevos"])
        print("%s %-12s %-9s %s %s %s  %s" % (rel(r["nombre"], 22, "b"), local(r["inicio"]).strftime("%d/%m %H:%M"), dur(r["fin"] - r["inicio"]),
                                             rel(fmt(r["nuevos"]), 8, "b", der=True), rel(fmt(r["nuevos"] / d), 8, der=True),
                                             rel("%.0f%%" % sp, 6, est_sub(sp), der=True), corto_proyecto(top)))


def cmd_limite(valor):
    cfg = cargar("config.json", {})
    if not valor:
        print("Tope actual: %s. Ponelo con «claudemon limite 600M»." % (fmt(cfg["limite"]) if cfg.get("limite") else "ninguno"))
        return
    cfg["limite"] = parsear_cantidad(valor)
    guardar("config.json", cfg)
    print("✔ Tope por período: %s tokens nuevos. Tip: cuando el plan te corte, mirá «claudemon uso» y poné ese total como tope." % fmt(cfg["limite"]))


def cmd_hoy():
    ini = datetime.datetime.combine(datetime.date.today(), datetime.time()).timestamp()
    res, R = resumen_periodo(ini, None, "hoy")
    imprimir_periodo(res, R, "HOY")


def cmd_historial(dias):
    res, R = resumen_periodo(time.time() - dias * 86400, None, "%d días" % dias)
    imprimir_periodo(res, R, "ÚLTIMOS %d DÍAS" % dias)


def _base(valor):
    """Período abierto si hay; si no, los últimos N días (7 por defecto)."""
    if valor and valor.isdigit():
        return time.time() - int(valor) * 86400, "últimos %s días" % valor
    p = cargar("periodo.json", None)
    if p:
        return p["inicio"], "período «%s»" % p["nombre"]
    return time.time() - 7 * 86400, "últimos 7 días"


def cmd_sesiones(valor):
    """Todas las sesiones de cada proyecto, con su nombre real, cuánto gastaron y qué modelos usaron."""
    ini, etiqueta = _base(valor)
    R = resumir(escanear(ini))
    if not R["sesiones"]:
        print("No encontré sesiones en %s (¿usaste Claude Code en ese tiempo? probá «claudemon diagnostico»)." % etiqueta)
        return
    print(seccion("Sesiones") + " — %s (desde %s)" % (etiqueta, local(ini).strftime("%d/%m %H:%M")))
    print(c("tokens nuevos · USD según Claude Code · % que fue de subagentes", "gris"))
    por = collections.defaultdict(list)
    for s_ in R["sesiones"]:
        por[s_["proyecto"]].append(s_)
    for proyecto, lista in sorted(por.items(), key=lambda x: -sum(y["nuevos"] for y in x[1])):
        tot = sum(y["nuevos"] for y in lista)
        usd = sum(y["usd"] for y in lista)
        print("\n%s %s%s" % (c("#" if ASCII else "▌", "cian", "b"), c(corto_proyecto(proyecto), "b", "cian"),
                             c(" — %d sesiones, %s tokens%s" % (len(lista), fmt(tot), ", USD %s" % format(usd, ",.0f") if usd else ""), "gris")))
        for y in lista[:14]:
            sub = 100 * y["sub"] / max(1, y["nuevos"])
            print("   %s %s  %s %s  %s  %s" % (
                rel(fmt(y["nuevos"]), 7, "b", der=True), rel(("$%.0f" % y["usd"]) if y["usd"] else "", 6, "amarillo", der=True),
                c("sub", "gris"), rel("%.0f%%" % sub, 4, est_sub(sub), der=True), rel(y["titulo"], 46), c("[%s]" % y["sesion"][:8], "gris")))
            print("%s%s %s %s %s" % (" " * 25, c("conv:", "gris"), texto_modelos(y["mp"]), c("| subag.:", "gris"), texto_modelos(y["ms"])))
            if y.get("ag"):                                  # qué tipo de agente gastó, y en qué modelo
                top = sorted(y["ag"].items(), key=lambda x: -x[1])
                partes = ["%s %s %s" % (tipo, c("(%s)" % mod, est_modelo(mod)), c(fmt(v), "gris")) for (tipo, mod), v in top[:3]]
                print("%s%s %s%s" % (" " * 25, c("agentes:", "gris"), (" · " if not ASCII else " | ").join(partes), c(" · +%d más" % (len(top) - 3), "gris") if len(top) > 3 else ""))
        if len(lista) > 14:
            print(c("   … y %d más pequeñas" % (len(lista) - 14), "gris"))
    print("\n" + c("Para retomar una: claude --resume <los 8 caracteres entre corchetes>  (o elegila por nombre con claude --resume)", "gris"))


def cmd_modelos(valor):
    """Quién usó cada modelo: tu conversación vs los subagentes (y qué tipo de agente)."""
    ini, etiqueta = _base(valor)
    R = resumir(escanear(ini))
    total = R["tot"]["nuevos"] or 1
    print(seccion("Modelos") + " — %s (desde %s) · tokens nuevos %s" % (etiqueta, local(ini).strftime("%d/%m %H:%M"), c(fmt(total), "b")))
    print("\n" + c("%-16s%9s%5s   %-12s%13s%12s%8s" % ("MODELO", "TOTAL", "%", "", "CONVERSACIÓN", "SUBAGENTES", "USD"), "dim", "b"))
    for m, v in sorted(R["modelos"].items(), key=lambda x: -x[1]):
        conv, sub = R["roles"].get(("conversación", m), 0), R["roles"].get(("subagentes", m), 0)
        usd = R["usd_modelos"].get(m, 0)
        pct = 100 * v / total
        print("%s%s%s   %s%s%s%s" % (rel(m, 16, est_modelo(m), "b"), rel(fmt(v), 9, "b", der=True), rel("%.0f%%" % pct, 5, "gris", der=True),
                                     barra(pct, 10, est_modelo(m)) + "  ", rel(fmt(conv), 13, der=True), rel(fmt(sub), 12, "magenta" if sub > conv else "", der=True),
                                     rel(("$%.0f" % usd) if usd else "", 8, "amarillo", der=True)))
    print("\n" + seccion("Tu conversación vs subagentes, en total:"))
    for rol in ("conversación", "subagentes"):
        cu = collections.Counter({m: v for (r_, m), v in R["roles"].items() if r_ == rol})
        print("  %s %s  %s" % (rel(rol, 13, "b"), rel(fmt(sum(cu.values())), 8, der=True), texto_modelos(cu)))
    if R["agentes"]:
        print("\n" + seccion("Subagentes por tipo de agente y modelo:"))
        for (tipo, mod), v in sorted(R["agentes"].items(), key=lambda x: -x[1])[:12]:
            print("  %s %s  %s %s" % (rel(fmt(v), 8, "b", der=True), c("%4.0f%%" % (100 * v / total), "gris"), rel(tipo, 28), c(mod, est_modelo(mod))))
    print("\n" + seccion("Por proyecto, qué modelo se usó:"))
    for p, cu in sorted(R["proy_modelos"].items(), key=lambda x: -sum(x[1].values()))[:8]:
        print("  %s  %s %s" % (rel(fmt(sum(cu.values())), 8, "b", der=True), rel(corto_proyecto(p), 26, "b"), texto_modelos(cu)))
    opus_sub = sum(v for (r_, m), v in R["roles"].items() if r_ == "subagentes" and "Opus" in m)
    opus_tot = sum(v for m, v in R["modelos"].items() if "Opus" in m)
    if opus_tot:
        print("\n" + c("→ Del Opus total, %.0f%% lo usaron SUBAGENTES (no tu conversación)." % (100 * opus_sub / opus_tot), "amarillo", "b"))
        ancho = max(60, min(100, shutil.get_terminal_size((100, 24)).columns - 4))
        for linea in textwrap.wrap("Un subagente corre en el modelo que fija su definición (.claude/agents/<tipo>.md, campo model:) "
                                   "aunque tu conversación esté en otro.", ancho):
            print("  " + c(linea, "gris"))


# ================================================================ plan y límites
def mensajes_desde(desde):
    """Todos los mensajes (conversación + subagentes) desde `desde`: [(epoch, tokens nuevos, familia)]."""
    out = []
    for S in escanear(desde).values():
        for m in S["msgs"].values():
            out.append((m["t"], m["in"] + m["out"] + m["cw"], familia(m["modelo"])))
    out.sort()
    return out


def bloque_actual(msgs, ahora):
    """Bloque de 5 h en curso (empieza con el primer mensaje; el siguiente después del fin abre otro). None si no hay uno activo."""
    ini = fin = None
    for t, _, _ in msgs:
        if ini is None or t >= fin:
            ini, fin = t, t + HORAS_BLOQUE * 3600
    return (ini, fin) if ini is not None and fin > ahora else None


def ultimo_reinicio_semanal(cfg, ahora):
    """Último reinicio semanal según lo que cargaste (día y hora de Ajustes → Uso); si no, los últimos 7 días móviles."""
    sem = cfg.get("semana")
    if not sem:
        return ahora - 7 * 86400, False
    hh, mm = (int(x) for x in sem["hora"].split(":"))
    d = local(ahora).replace(hour=hh, minute=mm, second=0, microsecond=0)
    d = d - datetime.timedelta(days=(d.weekday() - sem["dia"]) % 7)
    if d.timestamp() > ahora:
        d -= datetime.timedelta(days=7)
    return d.timestamp(), True


def uso_ventana(msgs, ini, fin=None):
    r = collections.Counter()
    for t, p, fam in msgs:
        if t >= ini and (fin is None or t < fin):
            r["todos"] += p
            r[fam] += p
    return r


def limite_calibrado(cfg, que):
    """Mediana de las últimas calibraciones (cada una: «100 % ≈ N tokens»), prefiriendo las hechas con 20 % o más."""
    recientes = cfg.get("calibracion", {}).get(que, [])[-5:]
    buenas = [x for x in recientes if x["pct"] >= 20] or recientes
    c = sorted(x["limite"] for x in buenas)
    return c[len(c) // 2] if c else None


def estado_limites():
    cfg, ahora = cargar("config.json", {}), time.time()
    sem_ini, sem_conf = ultimo_reinicio_semanal(cfg, ahora)
    msgs = mensajes_desde(min(sem_ini, ahora - 24 * 3600))
    blq = bloque_actual([m for m in msgs if m[0] >= ahora - 24 * 3600], ahora)
    return {"cfg": cfg, "ahora": ahora, "sem_ini": sem_ini, "sem_conf": sem_conf, "bloque": blq,
            "uso_bloque": uso_ventana(msgs, blq[0], blq[1]) if blq else collections.Counter(),
            "uso_semana": uso_ventana(msgs, sem_ini)}


def texto_limites():
    """Una línea corta para la pantalla en vivo, solo si ya elegiste plan."""
    try:
        E = estado_limites()
    except Exception:
        return None
    cfg, partes = E["cfg"], []
    if not cfg.get("plan"):
        return None
    lim5, limS = limite_calibrado(cfg, "sesion"), limite_calibrado(cfg, "semana")
    if E["bloque"]:
        u = E["uso_bloque"]["todos"]
        partes.append("5h %s" % fmt(u) + (" (%.0f%%)" % (100 * u / lim5) if lim5 else "") + " quedan %s" % dur(E["bloque"][1] - E["ahora"]))
    else:
        partes.append("5h sin bloque activo")
    u = E["uso_semana"]["todos"]
    partes.append("semana %s" % fmt(u) + (" (%.0f%%)" % (100 * u / limS) if limS else ""))
    return " · ".join(partes)


def texto_periodo():
    p = cargar("periodo.json", None)
    if not p:
        return None
    r, _ = resumen_periodo(p["inicio"], None, p["nombre"])
    lim = cargar("config.json", {}).get("limite")
    return "«%s» %s" % (p["nombre"], fmt(r["nuevos"])) + (" (%.0f%% del tope)" % (100 * r["nuevos"] / lim) if lim else "")


def texto_encabezado():
    partes = [x for x in (texto_limites(), texto_periodo()) if x]
    return " · ".join(partes) or None


def datos_limites():
    """Los límites como números (para el semáforo de la pantalla en vivo). None si todavía no elegiste plan."""
    try:
        E = estado_limites()
    except Exception:
        return None
    cfg, ahora = E["cfg"], E["ahora"]
    if cfg.get("plan") not in PLANES:
        return None
    lim5, limS = limite_calibrado(cfg, "sesion"), limite_calibrado(cfg, "semana")
    u5, uS = E["uso_bloque"]["todos"], E["uso_semana"]["todos"]
    dias = max((ahora - E["sem_ini"]) / 86400, 1 / 24)
    return {"plan": PLANES[cfg["plan"]][0], "u5": u5, "uS": uS, "lim5": lim5, "limS": limS,
            "pct5": 100 * u5 / lim5 if lim5 else None, "pctS": 100 * uS / limS if limS else None,
            "rest5": E["bloque"][1] - ahora if E["bloque"] else None,
            "rest_sem": E["sem_ini"] + 7 * 86400 - ahora if E["sem_conf"] else None,
            "proyS": 100 * uS / dias * 7 / limS if limS and E["sem_conf"] else None}


def cmd_plan(valor):
    cfg = cargar("config.json", {})
    if not valor:
        p = cfg.get("plan")
        print("Plan actual: %s. Elegí con «claudemon plan max20» (opciones: pro, max5, max20)." % (PLANES[p][0] if p in PLANES else "ninguno"))
        return
    v = re.sub(r"[\s-]", "", valor.lower()).rstrip("x")           # «Max 20x» -> «max20»
    v = {"max20": "max20", "max5": "max5", "pro": "pro", "20": "max20", "5": "max5"}.get(v, v)
    if v not in PLANES:
        print("Plan no reconocido. Opciones: pro, max5, max20.")
        return
    cfg["plan"] = v
    guardar("config.json", cfg)
    nombre, mult = PLANES[v]
    print("✔ Plan: %s (%d× el uso de Pro)." % (nombre, mult))
    print(AYUDA["limites"])


def cmd_semana(valor):
    cfg = cargar("config.json", {})
    if not valor:
        sem = cfg.get("semana")
        print("Reinicio semanal: %s. Cargalo con «claudemon semana mar 09:00»." % (
            DIAS_SEM[sem["dia"]] + " " + sem["hora"] if sem else "sin cargar (se usan los últimos 7 días móviles)"))
        return
    m = re.fullmatch(r"\s*([a-zA-Zéáó]{3})\w*\s+(\d{1,2}):(\d{2})\s*", valor)
    if not m:
        print("Formato: día y hora, por ejemplo «claudemon semana mar 09:00» (los días: lun mar mié jue vie sáb dom).")
        return
    d = m.group(1).lower().replace("mie", "mié").replace("sab", "sáb")
    if d not in DIAS_SEM:
        print("No entiendo el día. Usá: " + " ".join(DIAS_SEM))
        return
    cfg["semana"] = {"dia": DIAS_SEM.index(d), "hora": "%02d:%s" % (int(m.group(2)), m.group(3))}
    guardar("config.json", cfg)
    ini, _ = ultimo_reinicio_semanal(cfg, time.time())
    print("✔ Reinicio semanal: %s %s. La semana en curso empezó el %s." % (d, cfg["semana"]["hora"], local(ini).strftime("%a %d/%m %H:%M")))


def cmd_limites():
    E = estado_limites()
    cfg, ahora = E["cfg"], E["ahora"]
    plan = cfg.get("plan")
    print(linea_titulo("LÍMITES · plan %s · %s" % (PLANES[plan][0] if plan in PLANES else "(sin elegir: «claudemon plan max20»)",
                                                  local(ahora).strftime("%a %d/%m %H:%M"))))
    lim5, limS, limSo = (limite_calibrado(cfg, k) for k in ("sesion", "semana", "sonnet"))
    print("\n" + seccion("Ventana de 5 horas:"))
    if E["bloque"]:
        ini, fin = E["bloque"]
        u = E["uso_bloque"]
        print("  bloque desde %s hasta %s (quedan %s)   tokens nuevos %s   %s %s · %s %s · otros %s" % (
            local(ini).strftime("%H:%M"), local(fin).strftime("%H:%M"), dur(fin - ahora), c(fmt(u["todos"]), "b"),
            c("Opus", "magenta"), fmt(u["opus"]), c("Sonnet", "cian"), fmt(u["sonnet"]), fmt(u["otros"])))
        if lim5:
            pct = 100 * u["todos"] / lim5
            ritmo = u["todos"] / max(ahora - ini, 60)
            extra = "; a este ritmo llegás al tope en %s" % dur((lim5 - u["todos"]) / ritmo) if ritmo and u["todos"] < lim5 else ""
            print("  tope calibrado %s: %s %s%s" % (fmt(lim5), c("%.0f%%" % pct, color_pct(pct), "b"), barra(pct), extra if pct < 100 else c("  ¡AL LÍMITE!", "rojo", "b")))
        else:
            print(c("  (sin calibrar: cuando /usage muestre el % de la sesión, cargalo con «claudemon calibrar sesion 70»)", "amarillo"))
    else:
        print(c("  sin bloque activo: el próximo mensaje abre uno nuevo.", "gris"))
    ini, conf = E["sem_ini"], E["sem_conf"]
    u = E["uso_semana"]
    print("\n" + seccion("Semana (%s: %s):" % ("desde el reinicio" if conf else "últimos 7 días, sin día de reinicio cargado", local(ini).strftime("%a %d/%m %H:%M"))))
    print("  tokens nuevos %s   %s %s · %s %s · otros %s" % (c(fmt(u["todos"]), "b"), c("Opus", "magenta"), fmt(u["opus"]), c("Sonnet", "cian"), fmt(u["sonnet"]), fmt(u["otros"])))
    dias = max((ahora - ini) / 86400, 1 / 24)
    if conf:
        print("  faltan %s para el reinicio · ritmo %s/día · al reinicio llegarías a %s" % (dur(ini + 7 * 86400 - ahora), fmt(u["todos"] / dias), fmt(u["todos"] / dias * 7)))
    for nombre, lim, usado in (("todos los modelos", limS, u["todos"]), ("solo Sonnet", limSo, u["sonnet"])):
        if lim:
            pct = 100 * usado / lim
            print("  tope %s calibrado %s: %s %s" % (nombre, fmt(lim), c("%.0f%%" % pct, color_pct(pct), "b"), barra(pct)) +
                  ("; a este ritmo se agota en %s" % dur((lim - usado) / (usado / dias) * 86400) if usado and pct < 100 else c("  ¡AL LÍMITE!", "rojo", "b")))
    if not limS:
        print(c("  (sin calibrar: mirá el % semanal en /usage y cargalo con «claudemon calibrar semana 48»)", "amarillo"))
    print("\n" + c("Ojo: solo cuenta Claude Code. Si usás claude.ai o la app, también gastan del mismo cupo y no se ven acá.", "gris"))
    print(c("Los tokens de Opus y de Sonnet no pesan igual en el cupo real; recalibrá si cambia tu mezcla de modelos.", "gris"))


def cmd_calibrar(que, pct_txt):
    cfg = cargar("config.json", {})
    if que not in ("sesion", "semana", "sonnet"):
        print("Uso: claudemon calibrar sesion|semana|sonnet <porcentaje que muestra /usage>   (ej. «claudemon calibrar semana 62»)")
        return
    try:
        pct = float((pct_txt or "100").replace("%", "").replace(",", "."))
    except ValueError:
        print("El porcentaje tiene que ser un número (ej. 62).")
        return
    if not 1 <= pct <= 100:
        print("El porcentaje va de 1 a 100.")
        return
    E = estado_limites()
    usado = {"sesion": E["uso_bloque"]["todos"], "semana": E["uso_semana"]["todos"], "sonnet": E["uso_semana"]["sonnet"]}[que]
    if not usado:
        print("No hay uso registrado en esa ventana todavía: no se puede calibrar.")
        return
    limite = usado / (pct / 100)
    cfg.setdefault("calibracion", {}).setdefault(que, []).append({"t": time.time(), "pct": pct, "usado": usado, "limite": limite})
    guardar("config.json", cfg)
    print("✔ Calibrado «%s»: %s tokens = %.0f%%  →  el 100 %% ≈ %s tokens." % (que, fmt(usado), pct, fmt(limite)))
    if pct < 20:
        print("  Aviso: con menos de 20 % la estimación es poco confiable; volvé a calibrar cuando estés más cerca del tope (50 % o más).")
    n = len(cfg["calibracion"][que])
    print("  Usa la mediana de las últimas %d calibraciones (%s)." % (min(n, 5), fmt(limite_calibrado(cfg, que))))


# ================================================================ diagnóstico y demo
def cmd_diagnostico():
    ok = marca
    print(linea_titulo("DIAGNÓSTICO de claudemon %s" % VERSION))
    py = sys.version_info
    print("%s Sistema: %s · Python %d.%d.%d%s" % (ok(py >= (3, 8)), sys.platform, py[0], py[1], py[2], "" if py >= (3, 8) else "  ← hace falta Python 3.8 o más nuevo"))
    try:
        import psutil
        print(marca(True) + " psutil %s instalado (la pantalla en vivo funciona)" % psutil.__version__)
    except ImportError:
        print(marca(False) + " psutil NO instalado: los informes funcionan, pero la pantalla en vivo no. Instalalo con:  pip install psutil")
    print("%s Carpeta de Claude Code: %s" % (ok(os.path.isdir(RAIZ)), RAIZ))
    archivos = glob.glob(os.path.join(RAIZ, "**", "*.jsonl"), recursive=True)
    if not archivos:
        print(marca(False) + " No hay sesiones guardadas todavía (usá Claude Code un rato, o probá «claudemon demo» para ver cómo se ve).")
    else:
        recientes = sorted(archivos, key=os.path.getmtime, reverse=True)[:30]
        vio = collections.Counter()
        for r in recientes:
            try:
                with open(r, "rb") as f:
                    inicio = f.read(3 * 1024 * 1024)
                    f.seek(max(0, os.path.getsize(r) - 3 * 1024 * 1024))
                    datos = inicio + b"\n" + f.read()
            except OSError:
                continue
            for clave, b in (("usage", b'"usage"'), ("ai-title", b'"ai-title"'), ("custom-title", b'"custom-title"'), ("cost-state", b'"cost-state"')):
                if b in datos:
                    vio[clave] += 1
        print(marca(True) + " %d archivos de sesión · %d proyectos · última actividad %s" % (
            len(archivos), len({os.path.relpath(a, RAIZ).split(os.sep)[0] for a in archivos}),
            local(os.path.getmtime(recientes[0])).strftime("%d/%m %H:%M")))
        print("%s Registro de tokens en las sesiones recientes: %d de %d" % (ok(vio["usage"]), vio["usage"], len(recientes)))
        print("%s Nombres de sesión (ai-title/custom-title): %d de %d  · si no hay, se muestra tu primer mensaje" % (
            ok(vio["ai-title"] or vio["custom-title"]), max(vio["ai-title"], vio["custom-title"]), len(recientes)))
        print("%s Costo en USD (cost-state): %d de %d  · si no hay, no se muestran dólares (los tokens sí)" % (ok(vio["cost-state"]), vio["cost-state"], len(recientes)))
    try:
        os.makedirs(CARPETA, exist_ok=True)
        probe = os.path.join(CARPETA, ".prueba")
        open(probe, "w").close()
        os.remove(probe)
        print(marca(True) + " Carpeta del monitor escribible: %s" % CARPETA)
    except OSError as e:
        print(marca(False) + " No puedo escribir en %s (%s)" % (CARPETA, e))
    enc = (getattr(sys.stdout, "encoding", None) or "?").lower()
    print("%s Terminal con UTF-8 (%s)%s" % (ok("utf" in enc), enc, "" if "utf" in enc else "  ← si ves símbolos raros, usá:  claudemon --ascii"))
    cfg = cargar("config.json", {})
    print(c("·", "gris") + " Plan: %s · reinicio semanal: %s · período abierto: %s" % (
        PLANES[cfg["plan"]][0] if cfg.get("plan") in PLANES else "sin elegir",
        "%s %s" % (DIAS_SEM[cfg["semana"]["dia"]], cfg["semana"]["hora"]) if cfg.get("semana") else "sin cargar",
        (cargar("periodo.json", None) or {}).get("nombre", "ninguno")))


def _iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _jl(x):
    return json.dumps(x, separators=(",", ":"))                # mismo formato compacto que escribe Claude Code


def crear_datos_demo(base):
    """Crea sesiones INVENTADAS con el mismo formato que Claude Code, para probar y para mostrar cómo se ve."""
    import random
    r = random.Random(7)
    ahora = time.time()
    proyectos = {
        "-demo-tienda-online": [("Carrito y pagos con MercadoPago", "sonnet-5-5", True), ("Arreglar el buscador", "sonnet-5-5", False),
                                ("Rediseño de la home", "opus-5-5", True)],
        "-demo-api-clientes": [("Migración a PostgreSQL 16", "opus-5-5", True), ("Revisar los permisos de la API", "sonnet-5-5", False)],
        "-demo": [("Script de backup semanal", "sonnet-5-5", False), ("Dudas de Docker", "sonnet-5-5", False)],
    }
    n = 0
    for proy, sesiones in proyectos.items():
        for titulo, modelo, con_agentes in sesiones:
            n += 1
            sid = "%08x-demo-%04d-0000-000000000000" % (r.getrandbits(32), n)
            carpeta = os.path.join(base, proy)
            os.makedirs(carpeta, exist_ok=True)
            t0 = ahora - r.uniform(0.3, 6) * 86400
            lineas, costo = [], 0.0
            lineas.append({"type": "user", "timestamp": _iso(t0),
                           "message": {"role": "user", "content": "Hola, necesito ayuda con: " + titulo.lower()}})
            lineas.append({"type": "ai-title", "aiTitle": titulo, "sessionId": sid})
            if r.random() < .4:
                lineas.append({"type": "custom-title", "customTitle": titulo + " (v2)", "sessionId": sid})
            for i in range(r.randint(20, 80)):
                t = t0 + i * r.uniform(60, 900)
                if t > ahora:
                    break
                u = {"input_tokens": r.randint(2, 40), "output_tokens": r.randint(300, 4000),
                     "cache_creation_input_tokens": r.randint(2000, 40000), "cache_read_input_tokens": r.randint(60000, 400000)}
                costo += u["output_tokens"] / 1e6 * 25 + u["cache_creation_input_tokens"] / 1e6 * 6 + u["cache_read_input_tokens"] / 1e6 * 0.5
                lineas.append({"type": "assistant", "timestamp": _iso(t), "sessionId": sid,
                               "message": {"id": "msg_%s_%d" % (sid[:8], i), "model": "claude-" + modelo, "usage": u}})
            costo_sub = 0.0
            sub_dir = os.path.join(carpeta, sid, "subagents")
            if con_agentes:                              # subagentes (implementer / reviewer) corriendo en Opus, como pasa en la vida real
                os.makedirs(sub_dir, exist_ok=True)
                for k, tipo in enumerate(("implementer", "reviewer", "implementer")):
                    aid = "agent-%s%d" % (sid[:6], k)
                    with open(os.path.join(sub_dir, aid + ".meta.json"), "w", encoding="utf-8") as f:
                        json.dump({"agentType": tipo, "description": "demo"}, f)
                    sl = []
                    for i in range(r.randint(30, 90)):
                        t = t0 + 600 + i * r.uniform(20, 200) + k * 3600
                        if t > ahora:
                            break
                        u = {"input_tokens": 5, "output_tokens": r.randint(500, 5000), "cache_creation_input_tokens": r.randint(5000, 60000),
                             "cache_read_input_tokens": r.randint(100000, 600000)}
                        costo_sub += u["output_tokens"] / 1e6 * 25 + u["cache_creation_input_tokens"] / 1e6 * 6 + u["cache_read_input_tokens"] / 1e6 * 0.5
                        sl.append({"type": "assistant", "isSidechain": True, "timestamp": _iso(t),
                                   "message": {"id": "msg_%s_%d_%d" % (aid, k, i), "model": "claude-opus-5-5", "usage": u}})
                    with open(os.path.join(sub_dir, aid + ".jsonl"), "w", encoding="utf-8") as f:
                        f.write("\n".join(_jl(x) for x in sl) + "\n")
            # Claude Code anota en la sesión principal el costo de TODO (conversación + subagentes), por modelo
            usos = collections.Counter({"claude-" + modelo: costo})
            usos["claude-opus-5-5"] += costo_sub
            lineas.append({"type": "cost-state", "sessionId": sid, "startTime": str(int(t0 * 1000)), "totalCostUSD": str(costo + costo_sub),
                           "modelUsage": {m: {"costUSD": v} for m, v in usos.items()}})
            with open(os.path.join(carpeta, sid + ".jsonl"), "w", encoding="utf-8") as f:
                f.write("\n".join(_jl(x) for x in lineas) + "\n")
    return n


def cmd_demo():
    """Muestra los informes con datos inventados, sin tocar los tuyos."""
    global RAIZ, CARPETA
    viejo = (RAIZ, CARPETA)
    tmp = tempfile.mkdtemp(prefix="claudemon_demo_")
    try:
        RAIZ, CARPETA = os.path.join(tmp, "projects"), os.path.join(tmp, "monitor")
        n = crear_datos_demo(RAIZ)
        guardar("config.json", {"plan": "max20", "semana": {"dia": 1, "hora": "09:00"},
                                "calibracion": {"semana": [{"t": time.time(), "pct": 60, "usado": 1, "limite": 90e6}]}})
        print(linea_titulo("DEMO — %d sesiones INVENTADAS (tus datos no se tocan)" % n))
        for titulo, f in (("claudemon sesiones 7", lambda: cmd_sesiones("7")), ("claudemon modelos 7", lambda: cmd_modelos("7")),
                          ("claudemon limites", cmd_limites)):
            print("\n%s %s\n" % (c("$", "verde", "b"), c(titulo, "b")))
            f()
        print("\n(Esto fue una demostración. Para ver lo tuyo: «claudemon sesiones» y «claudemon modelos».)")
    finally:
        RAIZ, CARPETA = viejo
        shutil.rmtree(tmp, ignore_errors=True)


# ================================================================ ayuda en castellano
AYUDA = {
    "general": """claudemon — controla cuánto gastás de Claude Code.

Empezá por acá (2 minutos):
  claudemon demo                  mirá cómo se ve con datos inventados
  claudemon sesiones              tus sesiones, con su nombre y lo que gastó cada una
  claudemon modelos               quién usó Opus y quién Sonnet (¡a veces son los subagentes!)
  claudemon                       pantalla en vivo (necesita: pip install psutil)

Para llevar la cuenta de una semana:
  claudemon comenzar "semana 41"  marca el inicio
  claudemon uso                   cuánto llevás gastado desde esa marca
  claudemon reset                 cierra el período y empieza otro

Tu plan y tus límites:
  claudemon plan max20            (o max5, pro)
  claudemon semana mar 09:00      día y hora en que se te reinicia la semana (Ajustes → Uso)
  claudemon calibrar semana 62    le decís el % que muestra /usage y aprende tu tope
  claudemon limites               dónde estás en la ventana de 5 h y en la semana

Si algo falla:  claudemon diagnostico
Ayuda de un comando:  claudemon ayuda <tema>   (temas: sesiones, modelos, uso, limites, vivo, privacidad)""",
    "sesiones": """claudemon sesiones [días]
Lista todas tus sesiones, agrupadas por proyecto, con:
  · el NOMBRE de la sesión (el que le pusiste con /rename, o el que le genera Claude);
  · tokens nuevos gastados y USD que calcula Claude Code (equivalente de API, no tu factura);
  · qué % del gasto fue de subagentes;
  · qué modelo usó tu conversación (conv:) y cuál sus subagentes (subag.:);
  · los 8 caracteres entre corchetes: sirven para retomarla con  claude --resume <esos 8>.
Sin número usa el período abierto (si hiciste «comenzar») o los últimos 7 días.  Ej.:  claudemon sesiones 30""",
    "modelos": """claudemon modelos [días]
Responde «¿quién usó Opus?». Separa el gasto de tu CONVERSACIÓN del de los SUBAGENTES (los agentes que
lanza Claude para tareas en paralelo, como implementer o reviewer) y muestra el tipo de agente.
Un subagente corre en el modelo que dice su definición (.claude/agents/<tipo>.md, campo «model:»),
aunque vos estés usando Sonnet. Por eso a veces el 80 % del gasto es Opus sin que lo hayas elegido.""",
    "uso": """Contador por períodos (por ejemplo, una semana):
  claudemon comenzar "semana 41"   marca el inicio de un período
  claudemon uso                    cuánto llevás desde la marca: por proyecto, modelo, día y sesión, con ritmo y proyección
  claudemon reset                  cierra el período (lo guarda) y abre otro desde ahora
  claudemon periodos               compara los períodos cerrados
  claudemon hoy                    lo gastado desde las 00:00, sin tocar el período
  claudemon limite 600M            tu propio tope, para ver el % y cuánto falta (lo calibrás vos)""",
    "limites": """Cómo funcionan los límites de los planes (según las fuentes públicas; Anthropic no publica el tope exacto en tokens):
  · Ventana de 5 horas: arranca con tu primer mensaje y es móvil. Al agotarla, esperás a que pase.
  · Tope semanal de TODOS los modelos, y otro aparte solo para Sonnet. Se reinician en un horario fijo de tu cuenta.
  · El cupo se comparte con claude.ai y la app: acá solo se ve lo de Claude Code, así que estas cifras son un MÍNIMO.
Para que los porcentajes sean reales falta calibrar (una vez):
  1) Tu día y hora de reinicio semanal: mirá «Ajustes → Uso» (o /usage) y cargalo:  claudemon semana mar 09:00
  2) Cuando /usage te muestre un porcentaje (ej. 62 % de la semana):  claudemon calibrar semana 62
     (lo mismo con «sesion» para la ventana de 5 h y «sonnet» para el tope de Sonnet; cuanto más cerca del 100 %, mejor)
Después: «claudemon limites» muestra dónde estás, y la pantalla en vivo lo lleva en el encabezado.""",
    "vivo": """Pantalla en vivo:  claudemon   (necesita:  pip install psutil)
Se actualiza sola cada 3 segundos. Muestra CPU, memoria, los tokens de cada sesión en los últimos 5 min / 60 min / 24 h
y los procesos que más pesan. Columnas: 5 min / 60 min / 24 h = tokens nuevos · caché = % de lecturas baratas ·
sub60 = lo que gastaron los subagentes en la última hora · últ. = hace cuánto se movió · PID = proceso de esa sesión.
Al elegir una sesión (↑ ↓) aparece debajo de la tabla su detalle de 24 h: conversación, subagentes y tipo de agente con su modelo.
Teclas:  ↑ ↓ elegir sesión · z pausar o reanudar · k terminar (pide confirmación) · x terminar el proceso más pesado ·
n activar/desactivar avisos · q salir.
Pausar (z) congela la sesión sin perder nada; reanudar la sigue. Terminar corta el proceso y lo que cuelga de él;
la conversación queda guardada y se retoma con  claude --resume.
No se puede saber con exactitud qué proceso es cada sesión: si hay varios candidatos, te los muestra con su CPU y elegís vos.
Alertas:  claudemon --notificar  avisa (notificación del sistema y pitido) cuando una sesión pasa los 3 M de tokens en 5 min
o un proceso claude pasa 150 % de CPU. Ajustables con --umbral-5m y --umbral-cpu.""",
    "privacidad": """Privacidad: claudemon es de SOLO LECTURA y trabaja en tu compu. No envía datos a ningún lado ni usa internet.
Lee los archivos de sesión de Claude Code (~/.claude/projects), que contienen tus conversaciones, y muestra totales y
los TÍTULOS de las sesiones (a veces salen de tu primer mensaje). Cuidado al compartir pantallazos: pueden mostrar
nombres de proyectos o de sesiones. Guarda su configuración (plan, períodos) en ~/.claude/monitor.""",
}


def cmd_ayuda(tema):
    t = (tema or "general").lower()
    if t not in AYUDA:
        print("No tengo ayuda de «%s». Temas: %s" % (t, ", ".join(AYUDA)))
        return
    print(AYUDA[t])


# ================================================================ pantalla en vivo
def cargar_psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def sistema(psutil):
    """CPU, memoria y procesos de la máquina (psutil funciona igual en Mac, Linux y Windows)."""
    d = {"carga": os.getloadavg() if hasattr(os, "getloadavg") else None, "ncpu": os.cpu_count() or 1}
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    d["cpu"] = psutil.cpu_percent(None)
    d["mem_total"], d["mem_usada"] = vm.total, vm.total - vm.available
    d["swap_total"], d["swap_usado"] = sw.total / 2**20, sw.used / 2**20
    procs = []
    for p in psutil.process_iter(["pid", "ppid", "name", "status", "cmdline", "memory_info", "create_time"]):
        try:
            i = p.info
            cmd = " ".join(i["cmdline"] or []) or (i["name"] or "")
            procs.append({"pid": i["pid"], "ppid": i["ppid"] or 0, "cpu": p.cpu_percent(None), "rss": i["memory_info"].rss if i["memory_info"] else 0,
                          "estado": "T" if i["status"] == psutil.STATUS_STOPPED else "S", "etime": dur(time.time() - (i["create_time"] or time.time())),
                          "cmd": cmd, "args": i["cmdline"] or [], "nombre": (i["name"] or "").lower()})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    d["procs"] = procs
    return d


def es_claude(p):
    """¿Es un proceso de Claude Code? (el ejecutable `claude`, o la instalación por npm que corre cli.js con node)."""
    args = p["args"]
    base = re.split(r"[\\/]", args[0])[-1].lower() if args else p["nombre"]      # entiende «/» y «\\» sin importar el sistema
    if base in ("claude", "claude.exe"):
        return True
    if base in ("node", "node.exe") and len(args) > 1:
        rutas = " ".join(args[1:3]).replace("\\", "/").lower()
        return "claude-code" in rutas and ("cli.js" in rutas or "cli.mjs" in rutas or "/bin/claude" in rutas)
    return False


def mapear_pids(psutil, procs, filas):
    """Asocia cada proceso `claude` a su proyecto por la carpeta de trabajo (cwd)."""
    por_pid = {p["pid"]: p for p in procs}
    hijos = collections.defaultdict(list)
    for p in procs:
        hijos[p["ppid"]].append(p["pid"])
    claude = [p for p in procs if es_claude(p)]
    for p in claude:
        try:
            p["cwd"] = psutil.Process(p["pid"]).cwd()
        except Exception:
            p["cwd"] = "?"
        p["proyecto"] = _enc(p["cwd"])
        cola, desc = [p["pid"]], []
        while cola:
            for h in hijos.get(cola.pop(), []):
                desc.append(h)
                cola.append(h)
        p["hijos"] = len(desc)
        p["arbol_cpu"] = p["cpu"] + sum(por_pid[h]["cpu"] for h in desc if h in por_pid)
    for f in filas:
        f["pids"] = [p["pid"] for p in claude if p["proyecto"] == f["proyecto"] and f["edad"] < 1800]
    return claude


def _arbol(psutil, pid):
    try:
        p = psutil.Process(pid)
        return [p] + p.children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def pausar_reanudar(psutil, pid, estado):
    for p in _arbol(psutil, pid):
        try:
            p.resume() if estado.startswith("T") else p.suspend()
        except psutil.Error:
            pass
    return "reanudado" if estado.startswith("T") else "PAUSADO"


def terminar(psutil, pid):
    arbol = _arbol(psutil, pid)
    for p in arbol:
        try:
            p.resume()                                   # un proceso pausado no atiende el pedido de terminar
            p.terminate()
        except psutil.Error:
            pass
    _, vivos = psutil.wait_procs(arbol, timeout=3)
    for p in vivos:
        try:
            p.kill()
        except psutil.Error:
            pass


def ancestros_propios(psutil):
    try:
        return {os.getpid()} | {p.pid for p in psutil.Process(os.getpid()).parents()}
    except Exception:
        return {os.getpid()}


def notificar(titulo, texto):
    """Aviso del sistema (Mac y Linux) y pitido en la terminal (todos). Se llama SOLO desde el hilo principal."""
    sys.stdout.write("\a")
    try:
        if sys.platform == "darwin":
            cmd = ["osascript", "-e", 'display notification "%s" with title "%s" sound name "Funk"' % (texto.replace('"', "'")[:120], titulo)]
        elif sys.platform.startswith("linux") and shutil.which("notify-send"):
            cmd = ["notify-send", titulo, texto[:200]]
        else:
            return
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)      # sin esperar a que termine
    except Exception:
        pass


class Rastreador:
    """Lee de forma incremental las líneas nuevas de las sesiones tocadas en las últimas 24 h."""

    def __init__(self):
        self.pos, self.ses = {}, {}

    def refrescar(self):
        corte = time.time() - VENTANA
        for ruta_ in glob.glob(os.path.join(RAIZ, "**", "*.jsonl"), recursive=True):
            try:
                st = os.stat(ruta_)
            except OSError:
                continue
            if st.st_mtime < corte:
                continue
            ini = self.pos.get(ruta_)
            primera = ini is None
            if primera:
                if st.st_size > MAX_LEER_INICIAL:
                    with open(ruta_, "rb") as g:
                        ini = offset_desde(g, st.st_size, corte)
                else:
                    ini = 0
            elif st.st_size <= ini:
                continue
            rel = os.path.relpath(ruta_, RAIZ).split(os.sep)
            es_sub = "subagents" in rel
            S = self.ses.setdefault((rel[0], rel[1].replace(".jsonl", "")), {"msgs": {}, "titulo": "", "modelo": "", "mtime": 0})
            S["mtime"] = max(S["mtime"], st.st_mtime)
            agente = ""
            if es_sub and primera:
                try:
                    with open(ruta_.replace(".jsonl", ".meta.json"), encoding="utf-8") as g:
                        agente = json.load(g).get("agentType", "") or ""
                except Exception:
                    agente = ""
            try:
                with open(ruta_, "rb") as f:
                    f.seek(ini)
                    if primera and ini:
                        ini += len(f.readline())
                    for crudo in f:
                        if not crudo.endswith(b"\n"):
                            break                       # línea a medio escribir: se lee en la próxima vuelta
                        ini += len(crudo)
                        leer_linea(S, crudo, es_sub, agente)
                self.pos[ruta_] = ini
            except OSError:
                pass
        for S in self.ses.values():
            for k in [k for k, m in S["msgs"].items() if m["t"] < corte]:
                del S["msgs"][k]

    def tabla(self):
        ahora, filas = time.time(), []
        for (proyecto, sesion), S in self.ses.items():
            w5 = w60 = w24 = cr60 = cw60 = sub60 = 0
            msub, mp24, ms24, ag24 = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
            for m in S["msgs"].values():
                p, edad = m["in"] + m["out"] + m["cw"], ahora - m["t"]
                w24 += p
                mod = abrev_modelo(m["modelo"])
                if mod != "—":                                  # detalle de 24 h: conversación vs subagentes y tipo de agente
                    if m["sub"]:
                        ms24[mod] += p
                        ag24[(m.get("agente") or "(sin tipo)", mod)] += p
                    else:
                        mp24[mod] += p
                if edad <= 3600:
                    w60 += p
                    cr60 += m["cr"]
                    cw60 += m["cw"]
                    if m["sub"]:
                        sub60 += p
                        msub[abrev_modelo(m["modelo"])] += p
                if edad <= 300:
                    w5 += p
            if w24:
                filas.append({"proyecto": proyecto, "sesion": sesion, "titulo": nombre_sesion(S), "modelo": abrev_modelo(S["modelo"]), "w5": w5,
                              "w60": w60, "w24": w24, "cache": 100.0 * cr60 / (cr60 + cw60) if (cr60 + cw60) else 0.0,
                              "sub60": sub60, "msub": msub.most_common(1)[0][0] if msub else "", "mp": dict(mp24), "ms": dict(ms24), "ag": dict(ag24), "edad": ahora - S["mtime"], "pids": []})
        filas.sort(key=lambda f: (-f["w5"], -f["w60"], -f["w24"]))
        return filas


class Avisos:
    def __init__(self, u5, ucpu, activos):
        self.u5, self.ucpu, self.activos, self.ultimo, self.pendientes = u5, ucpu, activos, {}, []

    def evaluar(self, filas, claude):
        res = [("%s: %s tokens en 5 min (%s/min)" % (corto_proyecto(f["proyecto"]), fmt(f["w5"]), fmt(f["w5"] / 5)), f["sesion"]) for f in filas if f["w5"] >= self.u5]
        res += [("claude PID %d usa %.0f%% de CPU (%s)" % (p["pid"], p["cpu"], corto_proyecto(p.get("proyecto", "?"))), "cpu%d" % p["pid"])
                for p in claude if p["cpu"] >= self.ucpu]
        if self.activos:
            for texto, clave in res:
                if time.time() - self.ultimo.get(clave, 0) > 600:
                    self.ultimo[clave] = time.time()
                    self.pendientes.append(texto)               # los avisa el hilo principal
        return [t for t, _ in res]


def evaluar_estado(d, filas, claude=None, lim=None, u5=3e6, ucpu=150.0):
    """Semáforo de la pantalla en vivo. Devuelve [(nivel, qué pasa, pista, sesión)] con nivel 2 = ALERTA y 1 = ATENCIÓN.
    La pista dice si puede ser normal: lo que consume mucho no siempre es un problema."""
    R = []
    for f in filas:
        nom = "%s · %s" % (corto_proyecto(f["proyecto"]), f["titulo"][:30])
        sub_dom = f["sub60"] > 0.6 * max(1, f["w60"])
        if f["w5"] >= u5:
            R.append((2, "%s gastó %s en 5 min (%s/min)" % (nom, fmt(f["w5"]), fmt(f["w5"] / 5)),
                      "casi todo son subagentes: normal si lanzaste varios en paralelo; si no, revisá qué hacen" if sub_dom else
                      "relee mucho contexto en cada turno: si no es lo esperado, /clear o una sesión nueva", f["sesion"]))
        elif f["w5"] >= u5 / 3:
            R.append((1, "%s va a buen ritmo: %s en 5 min" % (nom, fmt(f["w5"])), "normal mientras trabaja activamente; fijate que termine", f["sesion"]))
        elif f["sub60"] >= 1e6 and sub_dom:
            R.append((1, "%s: subagentes gastaron %s en la última hora%s" % (nom, fmt(f["sub60"]), " (%s)" % f["msub"] if f.get("msub") else ""),
                      "normal si pediste agentes; son lo que más cupo consume (suelen correr en Opus)", f["sesion"]))
        elif f["w24"] >= 20e6:
            R.append((1, "%s acumula %s en 24 h" % (nom, fmt(f["w24"])), "sesión larga: conviene cerrarla y empezar otra al terminar esta tarea", f["sesion"]))
    for p in claude or []:
        if p["cpu"] >= ucpu:
            R.append((2, "claude PID %d usa %.0f%% de CPU (%s)" % (p["pid"], p["cpu"], corto_proyecto(p.get("proyecto", "?"))),
                      "normal si corre tests o compila; si no, pausalo con z", None))
        elif p["cpu"] >= ucpu * 0.6:
            R.append((1, "claude PID %d usa %.0f%% de CPU (%s)" % (p["pid"], p["cpu"], corto_proyecto(p.get("proyecto", "?"))), "normal si está trabajando", None))
    pmem = 100 * d["mem_usada"] / max(1, d["mem_total"])
    pswap = 100 * d["swap_usado"] / max(1, d["swap_total"]) if d["swap_total"] else 0
    if pmem >= 90:
        R.append((2, "memoria al %.0f%%" % pmem, "cerrá apps pesadas o sesiones de Claude que no uses", None))
    elif pmem >= 80:
        R.append((1, "memoria al %.0f%%" % pmem, "normal con muchas apps abiertas; si sube más, cerrá alguna", None))
    if pswap >= 90:
        R.append((2, "swap al %.0f%%: la máquina se está ahogando" % pswap, "cerrá sesiones o apps; reiniciar ayuda", None))
    elif pswap >= 75:
        R.append((1, "swap al %.0f%%" % pswap, "la memoria está justa; puede ir lento", None))
    if d["cpu"] >= 90:
        R.append((1, "CPU total al %.0f%%" % d["cpu"], "normal en una tarea pesada; si dura, mirá la lista de procesos de abajo", None))
    if lim:
        for etiqueta, pct in (("la ventana de 5 h", lim.get("pct5")), ("la semana", lim.get("pctS"))):
            if pct is None:
                continue
            if pct >= 90:
                R.append((2, "llevás el %.0f%% de %s" % (pct, etiqueta), "estás al límite: bajá el ritmo, cerrá lo pesado o esperá el reinicio", None))
            elif pct >= 70:
                R.append((1, "llevás el %.0f%% de %s" % (pct, etiqueta), "vas encaminado al límite", None))
        if lim.get("proyS") and lim["proyS"] >= 100 and (lim.get("pctS") or 0) < 90:
            R.append((1, "a este ritmo agotás la semana antes del reinicio (proyección %.0f%%)" % lim["proyS"], "si querés llegar, bajá el consumo (menos Opus o subagentes)", None))
    R.sort(key=lambda r: -r[0])
    return R


def panel_detalle(f):
    """Detalle de la sesión elegida: quién gastó qué modelo (últimas 24 h)."""
    L = [(" %s %s %s" % (c("Sesión elegida", "b", "cian"), c(f["titulo"][:50], "b"), c("· %s  (↑↓ para cambiar)" % corto_proyecto(f["proyecto"]), "gris")), "")]
    conv, sub = sum(f.get("mp", {}).values()), sum(f.get("ms", {}).values())
    L.append(("   %s %s %s" % (rel("Conversación", 13, "gris"), rel(fmt(conv), 7, "b", der=True), texto_modelos(f["mp"]) if f.get("mp") else c("—", "gris")), ""))
    L.append(("   %s %s %s" % (rel("Subagentes", 13, "gris"), rel(fmt(sub), 7, "b", der=True), texto_modelos(f["ms"]) if f.get("ms") else c("no usó", "gris")), ""))
    if f.get("ag"):
        top = sorted(f["ag"].items(), key=lambda x: -x[1])
        partes = ["%s %s %s" % (tipo, c("(%s)" % mod, est_modelo(mod)), c(fmt(v), "gris")) for (tipo, mod), v in top[:3]]
        L.append(("   %s %s %s%s" % (rel("Agentes", 13, "gris"), rel("", 7), (" · " if not ASCII else " | ").join(partes),
                                  c(" · +%d más" % (len(top) - 3), "gris") if len(top) > 3 else ""), ""))
    return L


def reporte_vivo(d, filas, alertas, extra=None, claude=None, lim=None, u5=3e6, ucpu=150.0, sel=0):
    gb = lambda b: "%.1f GB" % (b / 2**30)
    G = "   "                                             # separación entre columnas
    regla = c(("-" if ASCII else "─") * 100, "gris")
    carga = c("   carga %.1f/%d núcleos" % (d["carga"][0], d["ncpu"]), "gris") if d.get("carga") else ""
    pmem = 100 * d["mem_usada"] / max(1, d["mem_total"])
    pswap = 100 * d["swap_usado"] / max(1, d["swap_total"])
    estado = evaluar_estado(d, filas, claude, lim, u5, ucpu)
    n2, n1 = sum(1 for r in estado if r[0] == 2), sum(1 for r in estado if r[0] == 1)
    nivel_ses = {}
    for nv, _, _, ses in estado:
        if ses:
            nivel_ses[ses] = max(nivel_ses.get(ses, 0), nv)
    if n2:
        cartel = c(" %s ALERTA · %d " % ("!" if ASCII else "✖", n2), "fr") + (c(" %s ATENCIÓN · %d " % ("!" if ASCII else "▲", n1), "fa") if n1 else "")
    elif n1:
        cartel = c(" %s ATENCIÓN · %d " % ("!" if ASCII else "▲", n1), "fa")
    else:
        cartel = c(" %s TODO NORMAL " % ("OK" if ASCII else "●"), "fv")
    t5, t60, t24 = (sum(f[k] for f in filas) for k in ("w5", "w60", "w24"))
    calor = lambda v: "rojo" if v >= u5 else "amarillo" if v >= u5 / 3 else ""
    L = [(" %s   %s   %s" % (c(" claudemon ", "cab"), c(datetime.datetime.now().strftime("%H:%M:%S"), "gris"), cartel), ""), ("", "")]
    if estado:
        for nv, que, pista, _ in estado[:5]:
            tag = c(" ALERTA ", "fr") if nv == 2 else c(" ATENCIÓN ", "fa")
            L.append((" %s %s" % (tag, c(que, "b", "rojo" if nv == 2 else "amarillo")), ""))
            if pista:
                L.append(("            %s" % c("→ " + pista, "gris"), ""))
        if len(estado) > 5:
            L.append(("            %s" % c("… y %d más" % (len(estado) - 5), "gris"), ""))
    else:
        L.append((" %s" % c("Todo dentro de lo normal: el consumo, la máquina y tus límites están tranquilos.", "verde"), ""))
    L.append(("", ""))
    if lim:
        for k, (etiqueta, pct, usado, resto) in enumerate((("5 horas", lim["pct5"], lim["u5"], lim["rest5"]), ("Semana", lim["pctS"], lim["uS"], lim["rest_sem"]))):
            if pct is None:
                txt = "%s %s %s" % (rel(etiqueta, 8, "gris"), c(fmt(usado), "b"), c("(sin calibrar: «claudemon calibrar»)", "amarillo"))
            else:
                txt = "%s %s %s %s%s" % (rel(etiqueta, 8, "gris"), barra(pct, 24), c("%3.0f%%" % pct, color_pct(pct), "b"), c(fmt(usado), "gris"),
                                       c("  · quedan %s" % dur(resto), "gris") if resto and resto > 0 else "")
            L.append((" %s %s%s" % (rel("Límites" if k == 0 else "", 8, "gris"), txt, c("   plan " + lim["plan"], "gris") if k == 0 else ""), ""))
    else:
        L.append((" %s %s" % (rel("Límites", 8, "gris"), c("elegí tu plan con «claudemon plan max20» para ver cuánto te queda", "gris")), ""))
    if extra:
        L.append((" %s %s" % (rel("Período", 8, "gris"), c(extra, "cian")), ""))
    L.append(("", ""))
    L += [(" %s %s %s  %s%s" % (rel("CPU", 8, "gris"), c("%3.0f%%" % d["cpu"], color_pct(d["cpu"]), "b"), barra(d["cpu"], 24), "", carga), ""),
          (" %s %s %s  %s" % (rel("Memoria", 8, "gris"), c("%3.0f%%" % pmem, color_pct(pmem), "b"), barra(pmem, 24), c("%s de %s" % (gb(d["mem_usada"]), gb(d["mem_total"])), "gris")), ""),
          (" %s %s %s  %s" % (rel("Swap", 8, "gris"), c("%3.0f%%" % pswap, color_pct(pswap) if d["swap_total"] else "gris", "b"), barra(pswap, 24),
                              c("%.0f de %.0f MB" % (d["swap_usado"], d["swap_total"]), "gris")), ""),
          ("", ""),
          (" %s %s%s%s%s%s" % (c("Claude", "b", "cian"), c("5 min ", "gris"), c(fmt(t5), calor(t5), "b"), c(" (%s/min)" % fmt(t5 / 5), "gris") + G,
                               c("60 min ", "gris") + fmt(t60) + G, c("24 h ", "gris") + fmt(t24)), "")]
    L += [("", ""), (" " + regla, ""), ("", "")]
    L.append((c(" " + G.join(("%3s" % "#", "%-27s" % "PROYECTO", "%-11s" % "MODELO", "%7s" % "5 MIN", "%7s" % "60 MIN", "%7s" % "24 H",
                              "%5s" % "CACHÉ", "%6s" % "SUB60", "%5s" % "ÚLT.", "%-11s" % "PID", "SESIÓN")) + " ", "cab"), ""))
    for i, f in enumerate(filas[:12], 1):
        ed = "%.0fm" % (f["edad"] / 60) if f["edad"] < 7200 else "%.0fh" % (f["edad"] / 3600)
        L.append((" " + G.join((
            {2: c("✖" if not ASCII else "!", "rojo", "b"), 1: c("▲" if not ASCII else "!", "amarillo", "b")}.get(nivel_ses.get(f["sesion"], 0), " ") + c("%2d" % i, "gris"),
            rel(corto_proyecto(f["proyecto"]), 27, {2: "rojo", 1: "amarillo"}.get(nivel_ses.get(f["sesion"], 0), ""), "b"), rel(f["modelo"], 11, est_modelo(f["modelo"])),
            rel(fmt(f["w5"]), 7, calor(f["w5"]), "b" if f["w5"] else "", der=True), rel(fmt(f["w60"]), 7, der=True), rel(fmt(f["w24"]), 7, "gris", der=True),
            rel("%.0f%%" % f["cache"], 5, "gris", der=True), rel(fmt(f["sub60"]), 6, est_modelo(f.get("msub", "")) if f["sub60"] else "", "b" if f["sub60"] > f["w60"] / 2 and f["sub60"] else "", der=True),
            rel(ed, 5, "gris", der=True), rel(",".join(map(str, f["pids"])) or "-", 11, "gris"), f["titulo"][:34])), "sel%d" % i))
    if filas:
        L.append(("", ""))
        L += panel_detalle(filas[max(0, min(sel, min(len(filas), 12) - 1))])
    L += [("", ""), (" " + regla, ""), ("", ""), (" " + seccion("Procesos que más pesan en la máquina"), ""), ("", "")]
    L.append((c(" " + G.join(("%7s" % "PID", "%6s" % "CPU", "%8s" % "MEMORIA", "PROCESO")) + " ", "cab"), ""))
    for p in sorted(d["procs"], key=lambda p: -p["cpu"])[:6]:
        L.append((" " + G.join((c("%7d" % p["pid"], "gris"), rel("%.0f%%" % p["cpu"], 6, "rojo" if p["cpu"] >= 100 else "amarillo" if p["cpu"] >= 50 else "",
                                                               "b" if p["cpu"] >= 50 else "", der=True),
                                rel("%.0f MB" % (p["rss"] / 2**20), 8, der=True), p["cmd"][:70])), ""))
    return L


ESTILOS = {"b": "\x1b[1m", "r": "\x1b[31;1m", "y": "\x1b[33m", "inv": "\x1b[7m", "": ""}


class Terminal:
    """Teclado y pantalla sin curses (así funciona también en Windows)."""

    def __enter__(self):
        if ES_WIN:
            import msvcrt
            self.ms = msvcrt
            os.system("")                                # activa los códigos ANSI en la consola de Windows 10+
        else:
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
        sys.stdout.flush()
        return self

    def __exit__(self, *a):
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        if not ES_WIN:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def tecla(self, espera=0.15):
        """Devuelve 'ARRIBA', 'ABAJO', 'ESC', un caracter, o None si no se tocó nada."""
        if ES_WIN:
            fin = time.time() + espera
            while time.time() < fin:
                if self.ms.kbhit():
                    c = self.ms.getwch()
                    if c in ("\x00", "\xe0"):
                        return {"H": "ARRIBA", "P": "ABAJO"}.get(self.ms.getwch(), "")
                    return "ESC" if c == "\x1b" else c
                time.sleep(0.02)
            return None
        import select
        if not select.select([self.fd], [], [], espera)[0]:
            return None
        c = os.read(self.fd, 1).decode(errors="ignore")
        if c == "\x1b":
            if select.select([self.fd], [], [], 0.03)[0]:
                return {"[A": "ARRIBA", "[B": "ABAJO"}.get(os.read(self.fd, 2).decode(errors="ignore"), "")
            return "ESC"
        return c

    def pintar(self, lineas, sel, pie, pie_alerta):
        import shutil as _sh
        ancho, alto = _sh.get_terminal_size((110, 30))
        out = ["\x1b[H"]
        for i, (txt, est) in enumerate(lineas[:alto - 2]):
            if est.startswith("sel"):
                if sel == int(est[3:]) - 1:
                    est, txt = "inv", sin_color(txt)          # la fila elegida va en video inverso, sin otros colores encima
                else:
                    est = ""
            out.append("%s%s\x1b[0m\x1b[K\n" % (ESTILOS.get(est, ""), recortar(txt, ancho - 1)))
        out.append("\x1b[J\x1b[%d;1H%s%s\x1b[0m\x1b[K" % (alto, ESTILOS["y"] if pie_alerta else "", pie[:ancho - 1]))
        sys.stdout.write("".join(out))
        sys.stdout.flush()


def vivo(args):
    global COLOR
    COLOR = not SIN_COLOR                                # la pantalla en vivo siempre es una terminal
    psutil = cargar_psutil()
    if not psutil:
        print("La pantalla en vivo necesita la librería psutil. Instalala con:\n    pip install psutil\n(los informes —sesiones, modelos, uso, limites— funcionan sin ella)")
        return
    if not sys.stdout.isatty():
        print("La pantalla en vivo necesita una terminal. Para una foto en texto usá:  claudemon una-vez")
        return
    rast, av = Rastreador(), Avisos(args.umbral_5m, args.umbral_cpu, args.notificar)
    psutil.cpu_percent(None)
    E = {"d": None, "filas": [], "claude": [], "alertas": [], "extra": None, "lim": None, "error": ""}
    candado, parar = threading.Lock(), threading.Event()

    def recolectar():
        ult = 0.0
        while not parar.is_set():
            try:
                rast.refrescar()
                filas = rast.tabla()
                d = sistema(psutil)
                claude = mapear_pids(psutil, d["procs"], filas)
                alertas = av.evaluar(filas, claude)
                extra, lim = E["extra"], E["lim"]
                if time.time() - ult > 120:
                    ult, extra, lim = time.time(), texto_periodo(), datos_limites()
                with candado:
                    E.update(d=d, filas=filas, claude=claude, alertas=alertas, extra=extra, lim=lim, error="")
            except Exception as e:                       # una lectura fallida no tiene que cerrar el monitor
                with candado:
                    E["error"] = "error leyendo datos (%s: %s), sigo…" % (type(e).__name__, str(e)[:60])
            parar.wait(args.cada)

    hilo = threading.Thread(target=recolectar, daemon=True)
    hilo.start()
    sel, msg, msg_hasta, modo, ultimo_dibujo, firma = 0, "", 0.0, None, 0.0, None
    try:
        with Terminal() as tm:
            def preparar(accion, pid, nombre, procs):
                nonlocal msg, msg_hasta, modo
                if accion == "z":
                    est = next((p["estado"] for p in procs if p["pid"] == pid), "S")
                    msg, msg_hasta = "PID %d %s [%s]" % (pid, pausar_reanudar(psutil, pid, est), nombre), time.time() + 6
                else:
                    aviso = "  ¡ES LA SESIÓN DONDE CORRE ESTE MONITOR!" if pid in ancestros_propios(psutil) else ""
                    msg, msg_hasta = "¿Terminar PID %d [%s] y todo lo que cuelga de él?%s  s = sí · otra tecla = no" % (pid, nombre, aviso), time.time() + 30
                    modo = ("confirmar", pid, nombre)

            while True:
                with candado:
                    d, filas, claude, alertas, extra, lim, err = (E[k] for k in ("d", "filas", "claude", "alertas", "extra", "lim", "error"))
                if err:
                    msg, msg_hasta = err, time.time() + 4
                while av.pendientes:
                    notificar("claudemon", av.pendientes.pop(0))
                sel = max(0, min(sel, max(0, min(len(filas), 12) - 1)))
                if d is None:
                    lineas = [("leyendo datos de la máquina y de las sesiones…", "")]
                else:
                    lineas = reporte_vivo(d, filas, alertas, extra, claude, lim, args.umbral_5m, args.umbral_cpu, sel)
                pie_alerta = time.time() < msg_hasta
                pie = msg if pie_alerta else "↑↓ elegir · z pausar/reanudar · k terminar · x el más pesado · n avisos %s · q salir" % ("ON" if av.activos else "off")
                nueva = (tuple(lineas), sel, pie)
                if nueva != firma or time.time() - ultimo_dibujo > 1:
                    tm.pintar(lineas, sel, pie, pie_alerta)
                    firma, ultimo_dibujo = nueva, time.time()
                t = tm.tecla(0.15)
                if t is None:
                    continue
                procs = d["procs"] if d else []
                if modo:
                    if modo[0] == "elegir":              # varios procesos candidatos: se elige por número
                        _, accion, cand, nombre = modo
                        if t.isdigit() and 1 <= int(t) <= len(cand):
                            modo = None
                            preparar(accion, cand[int(t) - 1], nombre, procs)
                        else:
                            modo, msg, msg_hasta = None, "cancelado", time.time() + 4
                    else:
                        if t in ("s", "S"):
                            terminar(psutil, modo[1])
                            msg = "PID %d terminado [%s]" % (modo[1], modo[2])
                        else:
                            msg = "cancelado"
                        modo, msg_hasta = None, time.time() + 6
                    continue
                if t in ("q", "Q", "ESC"):
                    return
                elif t == "ARRIBA":
                    sel -= 1
                elif t == "ABAJO":
                    sel += 1
                elif t in ("n", "N"):
                    av.activos = not av.activos
                elif t in ("z", "k") and filas:
                    pids, nombre = filas[sel]["pids"], corto_proyecto(filas[sel]["proyecto"])
                    if not pids:
                        msg, msg_hasta = "esa sesión no tiene un proceso claude identificado (¿ya terminó?)", time.time() + 5
                        continue
                    if len(pids) == 1:
                        preparar(t, pids[0], nombre, procs)
                    else:                                # no hay forma exacta de saber cuál es: lo elegís mirando la CPU
                        info = {p["pid"]: p for p in claude}
                        caliente = max(pids, key=lambda x: info.get(x, {}).get("arbol_cpu", 0))
                        opc = "  ".join("%d) %d%s %.0f%%cpu %dhij %s" % (i, x, "*" if x == caliente else "", info.get(x, {}).get("arbol_cpu", 0),
                                                                        info.get(x, {}).get("hijos", 0), info.get(x, {}).get("etime", "?")) for i, x in enumerate(pids, 1))
                        msg, msg_hasta = "¿Cuál? (* = el más activo)  " + opc, time.time() + 30
                        modo = ("elegir", t, pids, nombre)
                elif t in ("x", "X") and procs:
                    top = sorted(procs, key=lambda p: -p["cpu"])[0]
                    msg, msg_hasta = "¿Terminar el más pesado, PID %d (%s)?  s = sí" % (top["pid"], top["cmd"][:36]), time.time() + 30
                    modo = ("confirmar", top["pid"], top["cmd"][:20])
    finally:
        parar.set()
        hilo.join(5)                                     # que termine el recorrido de /proc en curso: salir a la mitad cuelga el cierre en algunos kernels


def una_vez(args):
    psutil = cargar_psutil()
    r = Rastreador()
    r.refrescar()
    filas = r.tabla()
    if psutil:
        psutil.cpu_percent(None)
        time.sleep(0.5)
        d = sistema(psutil)
        claude = mapear_pids(psutil, d["procs"], filas)
    else:
        print("(sin psutil: se muestra solo el consumo de Claude. Para ver la máquina:  pip install psutil)\n")
        d, claude = {"carga": None, "ncpu": os.cpu_count() or 1, "cpu": 0.0, "mem_total": 1, "mem_usada": 0, "swap_total": 0.0, "swap_usado": 0.0, "procs": []}, []
    for txt, _ in reporte_vivo(d, filas, [], texto_periodo(), claude, datos_limites(), args.umbral_5m, args.umbral_cpu):
        print(txt)


# ================================================================ programa principal
ACCIONES = ["vivo", "una-vez", "comenzar", "uso", "reset", "periodos", "limite", "hoy", "historial", "sesiones", "modelos",
            "plan", "semana", "limites", "calibrar", "demo", "diagnostico", "ayuda"]


def main(argv=None):
    global ASCII
    ap = argparse.ArgumentParser(
        prog="claudemon", usage="claudemon [accion] [valor] [opciones]", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Controla cuánto gastás de Claude Code y qué sesión se lleva el cupo. Es de SOLO LECTURA y trabaja en tu compu.",
        epilog="Empezá con:  claudemon demo   ·   claudemon ayuda   ·   claudemon diagnostico\n\nAcciones: " + ", ".join(ACCIONES))
    ap.add_argument("accion", nargs="?", default="vivo", choices=ACCIONES, metavar="accion", help="qué hacer (por defecto: pantalla en vivo)")
    ap.add_argument("valor", nargs="*", help="nombre del período, tope, días, plan, «día hora» (semana) o «qué %%» (calibrar)")
    ap.add_argument("--cada", type=float, default=3.0, help="segundos entre actualizaciones en vivo (3)")
    ap.add_argument("--umbral-5m", type=int, default=3000000, help="alerta si una sesión supera estos tokens nuevos en 5 min (3000000)")
    ap.add_argument("--umbral-cpu", type=float, default=150.0, help="alerta si un proceso claude supera este %% de CPU (150)")
    ap.add_argument("--notificar", action="store_true", help="aviso del sistema cuando salta una alerta")
    ap.add_argument("--ascii", action="store_true", help="sin símbolos especiales (si tu terminal los muestra mal)")
    ap.add_argument("--sin-color", action="store_true", help="sin colores (también se apagan solos con NO_COLOR, o si la salida no es una terminal)")
    ap.add_argument("--version", action="version", version="claudemon " + VERSION)
    a = ap.parse_args(argv)
    ASCII = ASCII or a.ascii
    global SIN_COLOR, COLOR
    if a.sin_color:
        SIN_COLOR, COLOR = True, False
    if COLOR and ES_WIN:
        os.system("")                                    # activa los códigos ANSI en la consola de Windows 10+
    if ES_WIN or not (getattr(sys.stdout, "encoding", "") or "").lower().startswith("utf"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    v1 = " ".join(a.valor) if a.valor else None
    try:
        if a.accion == "comenzar":
            cmd_comenzar(v1)
        elif a.accion == "uso":
            cmd_uso()
        elif a.accion == "reset":
            cmd_reset(v1)
        elif a.accion == "periodos":
            cmd_periodos()
        elif a.accion == "limite":
            cmd_limite(v1)
        elif a.accion == "hoy":
            cmd_hoy()
        elif a.accion == "historial":
            cmd_historial(int(v1 or 35))
        elif a.accion == "sesiones":
            cmd_sesiones(v1)
        elif a.accion == "modelos":
            cmd_modelos(v1)
        elif a.accion == "plan":
            cmd_plan(v1)
        elif a.accion == "semana":
            cmd_semana(v1)
        elif a.accion == "limites":
            cmd_limites()
        elif a.accion == "calibrar":
            cmd_calibrar(a.valor[0] if a.valor else "", a.valor[1] if len(a.valor) > 1 else None)
        elif a.accion == "demo":
            cmd_demo()
        elif a.accion == "diagnostico":
            cmd_diagnostico()
        elif a.accion == "ayuda":
            cmd_ayuda(v1)
        elif a.accion == "una-vez":
            una_vez(a)
        else:
            vivo(a)
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    except ValueError as e:
        print("Error:", e)


if __name__ == "__main__":
    main()
