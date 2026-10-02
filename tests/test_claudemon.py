#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas de claudemon. Se corren con:   python tests/test_claudemon.py

Usan SOLO datos inventados en una carpeta temporal: nunca tocan tus sesiones reales ni tu configuración.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(AQUI), "claudemon.py")
ES_WIN = os.name == "nt"

spec = importlib.util.spec_from_file_location("claudemon", SCRIPT)
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)
sin_color = cm.sin_color


class Entorno(unittest.TestCase):
    """Cada prueba corre con su propia carpeta de Claude Code inventada (3 proyectos, 7 sesiones, subagentes)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="claudemon_test_")
        cls.claude = os.path.join(cls.tmp, ".claude")
        cls.n = cm.crear_datos_demo(os.path.join(cls.claude, "projects"))
        cls.env = dict(os.environ, CLAUDE_CONFIG_DIR=cls.claude, CLAUDEMON_DIR=os.path.join(cls.tmp, "monitor"), PYTHONIOENCODING="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(self.env["CLAUDEMON_DIR"], ignore_errors=True)       # configuración limpia en cada prueba

    def correr(self, *args):
        r = subprocess.run([sys.executable, SCRIPT] + list(args), env=self.env, capture_output=True, timeout=120)
        return r.returncode, r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")


class PruebasDeComandos(Entorno):
    def test_hay_sesiones_demo(self):
        self.assertEqual(self.n, 7)

    def test_diagnostico(self):
        code, out = self.correr("diagnostico")
        self.assertEqual(code, 0, out)
        self.assertIn("DIAGNÓSTICO", out)
        self.assertIn("archivos de sesión", out)
        self.assertIn("cost-state", out)

    def test_sesiones_muestra_nombres_y_modelos(self):
        code, out = self.correr("sesiones", "7")
        self.assertEqual(code, 0, out)
        for nombre in ("Rediseño de la home", "Migración a PostgreSQL 16", "Dudas de Docker"):
            self.assertIn(nombre, out)
        self.assertIn("conv:", out)
        self.assertIn("subag.:", out)
        self.assertIn("claude --resume", out)
        self.assertIn("agentes:", out)                        # el desglose por tipo de agente de cada sesión
        self.assertIn("implementer (Opus 5.5)", out)

    def test_modelos_separa_conversacion_y_subagentes(self):
        code, out = self.correr("modelos", "7")
        self.assertEqual(code, 0, out)
        self.assertIn("Opus 5.5", out)
        self.assertIn("implementer", out)
        self.assertIn("SUBAGENTES", out)
        self.assertIn("lo usaron SUBAGENTES", out)

    def test_ciclo_de_periodos(self):
        self.assertIn("No hay período abierto", self.correr("uso")[1])
        self.assertIn("iniciado ahora", self.correr("comenzar", "semana de prueba")[1])
        self.assertIn("Ya hay un período abierto", self.correr("comenzar")[1])
        code, out = self.correr("uso")
        self.assertEqual(code, 0, out)
        self.assertIn("semana de prueba", out)
        code, out = self.correr("reset", "semana dos")
        self.assertIn("CERRADO", out)
        self.assertIn("Guardado en el historial", out)
        self.assertIn("semana de prueba", self.correr("periodos")[1])
        self.assertIn("semana dos", self.correr("uso")[1])

    def test_plan_semana_calibrar_y_limites(self):
        self.assertIn("Max 20x", self.correr("plan", "Max 20x")[1])
        self.assertIn("Plan no reconocido", self.correr("plan", "banana")[1])
        self.assertIn("Reinicio semanal: mar 09:00", self.correr("semana", "mar", "09:00")[1])
        self.assertIn("Formato", self.correr("semana", "cuando sea")[1])
        out = self.correr("calibrar", "semana", "50")[1]
        self.assertIn("el 100 % ≈", out)
        out = self.correr("limites")[1]
        self.assertIn("plan Max 20x", out)
        self.assertIn("tope todos los modelos calibrado", out)

    def test_calibrar_valida_los_datos(self):
        self.correr("plan", "max20")
        self.assertIn("tiene que ser un número", self.correr("calibrar", "semana", "abc")[1])
        self.assertIn("va de 1 a 100", self.correr("calibrar", "semana", "150")[1])
        self.assertIn("Uso:", self.correr("calibrar", "mensual", "50")[1])

    def test_limite_propio(self):
        self.assertIn("600.0M", self.correr("limite", "600M")[1])
        self.assertIn("no entiendo", self.correr("limite", "5x")[1])

    def test_ayuda(self):
        self.assertIn("Empezá por acá", self.correr("ayuda")[1])
        self.assertIn("NOMBRE", self.correr("ayuda", "sesiones")[1])
        self.assertIn("No tengo ayuda", self.correr("ayuda", "inexistente")[1])

    def test_demo_no_toca_tus_datos(self):
        code, out = self.correr("demo")
        self.assertEqual(code, 0, out)
        self.assertIn("INVENTADAS", out)
        self.assertFalse(os.path.exists(self.env["CLAUDEMON_DIR"]), "la demo no debe dejar configuración en tu carpeta")

    def test_color_no_cambia_el_texto(self):
        """Con color forzado, quitando los códigos ANSI queda EXACTAMENTE el mismo texto que sin color."""
        import re
        quitar = lambda t: re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", t)
        for args in (["sesiones", "7"], ["modelos", "7"], ["limites"], ["diagnostico"], ["hoy"], ["--ascii", "modelos"]):
            code, plano = self.correr(*args)
            self.assertEqual(code, 0, plano)
            self.assertNotIn("\x1b", plano, "sin terminal no debe haber colores: %r" % args)
            env = dict(self.env, CLAUDEMON_COLOR="1")
            r = subprocess.run([sys.executable, SCRIPT] + args, env=env, capture_output=True, timeout=120)
            color = r.stdout.decode("utf-8", errors="replace")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("\x1b[", color, "con CLAUDEMON_COLOR=1 tiene que haber colores: %r" % args)
            self.assertEqual(quitar(color), plano, "el color cambió el texto de %r" % args)

    def test_sin_color_y_no_color(self):
        for extra_env, args in (({"NO_COLOR": "1"}, []), ({}, ["--sin-color"])):
            env = dict(self.env, **extra_env)
            r = subprocess.run([sys.executable, SCRIPT] + args + ["modelos", "7"], env=env, capture_output=True, timeout=120)
            self.assertNotIn(b"\x1b", r.stdout)

    def test_modo_ascii_sin_simbolos(self):
        out = self.correr("--ascii", "modelos", "7")[1]
        for simbolo in ("█", "░", "━", "▌"):
            self.assertNotIn(simbolo, out)

    def test_una_vez(self):
        code, out = self.correr("una-vez")
        self.assertEqual(code, 0, out)
        self.assertIn("60 min", out)
        self.assertIn("PROYECTO", out)

    def test_sin_sesiones_no_se_rompe(self):
        vacio = tempfile.mkdtemp(prefix="claudemon_vacio_")
        try:
            env = dict(self.env, CLAUDE_CONFIG_DIR=vacio, CLAUDEMON_DIR=os.path.join(vacio, "m"))
            r = subprocess.run([sys.executable, SCRIPT, "sesiones"], env=env, capture_output=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("No encontré sesiones", r.stdout.decode("utf-8", errors="replace"))
        finally:
            shutil.rmtree(vacio, ignore_errors=True)


class PruebasDeFunciones(unittest.TestCase):
    def test_nombres_de_modelos(self):
        casos = {"claude-sonnet-5-5": "Sonnet 5.5", "claude-opus-5-5[1m]": "Opus 5.5 1M", "claude-haiku-4-5-20251001": "Haiku 4.5",
                 "claude-opus-4-8": "Opus 4.8", "<synthetic>": "—", "": "—"}
        for entrada, esperado in casos.items():
            self.assertEqual(cm.abrev_modelo(entrada), esperado)

    def test_cantidades(self):
        self.assertEqual(cm.parsear_cantidad("600M"), 600e6)
        self.assertEqual(cm.parsear_cantidad("1,5G"), 1.5e9)
        self.assertEqual(cm.parsear_cantidad("800000k"), 800e6)
        with self.assertRaises(ValueError):
            cm.parsear_cantidad("mucho")

    def test_formato_de_numeros(self):
        self.assertEqual(cm.fmt(999), "999")
        self.assertEqual(cm.fmt(12500), "12k")
        self.assertEqual(cm.fmt(3400000), "3.4M")
        self.assertEqual(cm.fmt(2e9), "2.0G")

    def test_nombre_corto_de_proyecto(self):
        home = cm._enc(os.path.expanduser("~"))
        self.assertEqual(cm.corto_proyecto(home), "~")
        self.assertEqual(cm.corto_proyecto(home + "-Projects-mi-tienda"), "mi-tienda")
        self.assertEqual(cm.corto_proyecto("-demo-api"), "demo-api")
        self.assertIn("wt", cm.corto_proyecto(home + "-app--claude-worktrees-x").replace("⎇", "wt"))

    def test_nombre_de_sesion_prioriza_el_que_pusiste(self):
        self.assertEqual(cm.nombre_sesion({"custom": "Mío", "ai": "De Claude", "titulo": "primer mensaje"}), "Mío")
        self.assertEqual(cm.nombre_sesion({"ai": "De Claude", "titulo": "primer mensaje"}), "De Claude")
        self.assertEqual(cm.nombre_sesion({"titulo": "primer mensaje"}), "primer mensaje")
        self.assertEqual(cm.nombre_sesion({}), "(sin nombre)")

    def test_el_modelo_de_la_sesion_es_el_de_la_conversacion_no_el_de_los_subagentes(self):
        S = {"msgs": {}, "titulo": "x"}
        linea = b'{"type":"assistant","timestamp":"2026-10-01T10:00:00.000Z","message":{"id":"%s","model":"%s","usage":{"input_tokens":1,"output_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
        cm.leer_linea(S, linea % (b"c1", b"claude-sonnet-5-5"), False)
        cm.leer_linea(S, linea % (b"s1", b"claude-opus-5-5"), True, "implementer")      # un subagente en Opus, DESPUÉS de la conversación
        self.assertEqual(S["modelo"], "claude-sonnet-5-5")
        self.assertEqual({m["modelo"] for m in S["msgs"].values()}, {"claude-sonnet-5-5", "claude-opus-5-5"})   # igual se cuenta el gasto de ambos

    def test_mensaje_repetido_no_se_cuenta_dos_veces(self):
        S = {"msgs": {}, "titulo": "x"}
        base = b'{"type":"assistant","timestamp":"2026-10-01T10:00:00.000Z","message":{"id":"m1","model":"claude-sonnet-5-5","usage":{"input_tokens":1,"output_tokens":%d,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
        cm.leer_linea(S, base % 10, False)
        cm.leer_linea(S, base % 50, False)                 # el mismo mensaje con más salida (streaming): se queda con el último
        self.assertEqual(len(S["msgs"]), 1)
        self.assertEqual(S["msgs"]["m1"]["out"], 50)

    def test_bloque_de_5_horas(self):
        ahora = 1_000_000.0
        h = 3600
        self.assertEqual(cm.bloque_actual([(ahora - 2 * h, 1, "x")], ahora), (ahora - 2 * h, ahora + 3 * h))
        self.assertIsNone(cm.bloque_actual([(ahora - 6 * h, 1, "x")], ahora))                       # ya venció: no hay bloque activo
        self.assertEqual(cm.bloque_actual([(ahora - 7 * h, 1, "x"), (ahora - 1 * h, 1, "x")], ahora)[0], ahora - 1 * h)   # abre uno nuevo

    def test_reinicio_semanal(self):
        import datetime
        ahora = datetime.datetime(2026, 10, 2, 10, 0).timestamp()                                    # viernes
        ini, conf = cm.ultimo_reinicio_semanal({"semana": {"dia": 1, "hora": "09:00"}}, ahora)       # martes 09:00
        self.assertTrue(conf)
        self.assertEqual(datetime.datetime.fromtimestamp(ini), datetime.datetime(2026, 9, 29, 9, 0))
        ini, conf = cm.ultimo_reinicio_semanal({}, ahora)
        self.assertFalse(conf)
        self.assertAlmostEqual(ahora - ini, 7 * 86400, delta=1)

    def test_costo_del_periodo_resta_lo_anterior(self):
        S = {"costos": [{"t": 10, "inicio": "A", "total": 30.0, "modelos": {"claude-opus-5-5": 25.0, "claude-sonnet-5-5": 5.0}}],
             "costo_prev": {"inicio": "A", "total": 10.0, "modelos": {"claude-opus-5-5": 8.0, "claude-sonnet-5-5": 2.0}}}
        total, modelos = cm.costo_sesion(S)
        self.assertAlmostEqual(total, 20.0)
        self.assertAlmostEqual(modelos["claude-opus-5-5"], 17.0)
        S2 = {"costos": [{"t": 10, "inicio": "B", "total": 4.0, "modelos": {}}], "costo_prev": {"inicio": "A", "total": 10.0, "modelos": {}}}
        self.assertAlmostEqual(cm.costo_sesion(S2)[0], 4.0)                                          # otra corrida: no resta

    def test_deteccion_de_procesos_claude(self):
        self.assertTrue(cm.es_claude({"args": ["/usr/local/bin/claude", "--resume"], "nombre": "claude"}))
        self.assertTrue(cm.es_claude({"args": ["C:\\Users\\a\\AppData\\Local\\claude.exe"], "nombre": "claude.exe"}))
        self.assertTrue(cm.es_claude({"args": ["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"], "nombre": "node"}))
        self.assertFalse(cm.es_claude({"args": ["python", "claudemon.py"], "nombre": "python"}))
        self.assertFalse(cm.es_claude({"args": ["node", "server.js"], "nombre": "node"}))


class PruebasDelSemaforo(unittest.TestCase):
    """El semáforo de la pantalla en vivo: normal, atención o alerta, siempre con una pista de si puede ser normal."""

    def maquina(self, **kw):
        d = {"carga": None, "ncpu": 8, "cpu": 20.0, "mem_total": 16 * 2**30, "mem_usada": 6 * 2**30, "swap_total": 4096.0, "swap_usado": 100.0, "procs": []}
        d.update(kw)
        return d

    def fila(self, **kw):
        f = {"proyecto": "-demo-app", "sesion": "s1", "titulo": "Tarea de prueba", "modelo": "Sonnet 5.5", "w5": 0, "w60": 0, "w24": 0,
             "cache": 90.0, "sub60": 0, "edad": 60.0, "pids": []}
        f.update(kw)
        return f

    def texto(self, estado):
        return " ".join("%d %s %s" % (n, q, p) for n, q, p, _ in estado)

    def test_todo_normal(self):
        self.assertEqual(cm.evaluar_estado(self.maquina(), [self.fila(w5=50e3, w60=300e3, w24=2e6)], [], None), [])
        L = cm.reporte_vivo(self.maquina(), [self.fila(w5=50e3, w60=300e3, w24=2e6)], [], None, [], None)
        self.assertIn("TODO NORMAL", " ".join(sin_color(t) for t, _ in L))

    def test_sesion_que_gasta_mucho_es_alerta_y_dice_si_son_subagentes(self):
        e = cm.evaluar_estado(self.maquina(), [self.fila(w5=4e6, w60=4e6, sub60=3.5e6)], [], None)
        self.assertEqual(e[0][0], 2)
        self.assertIn("subagentes", e[0][2])
        self.assertEqual(e[0][3], "s1")
        e = cm.evaluar_estado(self.maquina(), [self.fila(w5=4e6, w60=4e6, sub60=0)], [], None)
        self.assertIn("contexto", e[0][2])

    def test_niveles_intermedios_son_atencion(self):
        self.assertEqual(cm.evaluar_estado(self.maquina(), [self.fila(w5=1.5e6, w60=1.5e6)], [], None)[0][0], 1)
        self.assertEqual(cm.evaluar_estado(self.maquina(), [self.fila(w24=25e6)], [], None)[0][0], 1)
        self.assertEqual(cm.evaluar_estado(self.maquina(), [self.fila(w60=2e6, sub60=1.8e6)], [], None)[0][0], 1)

    def test_proceso_claude_con_mucha_cpu(self):
        e = cm.evaluar_estado(self.maquina(), [], [{"pid": 7, "cpu": 190.0, "proyecto": "-demo-app"}], None)
        self.assertEqual((e[0][0], "PID 7" in e[0][1], "tests" in e[0][2]), (2, True, True))
        self.assertEqual(cm.evaluar_estado(self.maquina(), [], [{"pid": 7, "cpu": 100.0, "proyecto": "x"}], None)[0][0], 1)

    def test_memoria_y_swap(self):
        self.assertEqual(cm.evaluar_estado(self.maquina(mem_usada=int(15.5 * 2**30)), [], [], None)[0][0], 2)
        self.assertEqual(cm.evaluar_estado(self.maquina(mem_usada=int(13.5 * 2**30)), [], [], None)[0][0], 1)
        self.assertEqual(cm.evaluar_estado(self.maquina(swap_usado=3900.0), [], [], None)[0][0], 2)

    def test_limites_del_plan(self):
        lim = {"pct5": 95.0, "pctS": 40.0, "proyS": 60.0}
        e = cm.evaluar_estado(self.maquina(), [], [], lim)
        self.assertEqual((e[0][0], "5 h" in e[0][1]), (2, True))
        e = cm.evaluar_estado(self.maquina(), [], [], {"pct5": 10.0, "pctS": 75.0, "proyS": 130.0})
        self.assertEqual([x[0] for x in e], [1, 1])                       # 75 % y «te quedás sin cupo antes del reinicio»
        self.assertEqual(cm.evaluar_estado(self.maquina(), [], [], {"pct5": None, "pctS": None, "proyS": None}), [])   # sin calibrar: no inventa

    def test_panel_de_detalle_de_la_sesion_elegida(self):
        f1 = self.fila(titulo="Primera", mp={"Sonnet 5.5": 2e6}, ms={"Opus 5.5": 8e6}, ag={("implementer", "Opus 5.5"): 6e6, ("reviewer", "Opus 5.5"): 2e6})
        f2 = self.fila(sesion="s2", titulo="Segunda", mp={"Sonnet 5.5": 1e6}, ms={}, ag={})
        txt = lambda sel: " ".join(sin_color(t) for t, _ in cm.reporte_vivo(self.maquina(), [f1, f2], [], None, [], None, sel=sel))
        self.assertIn("Sesión elegida Primera", txt(0))
        self.assertIn("implementer (Opus 5.5) 6.0M", txt(0))
        self.assertIn("reviewer (Opus 5.5)", txt(0))
        self.assertIn("Sesión elegida Segunda", txt(1))                    # al mover la selección cambia el detalle
        self.assertIn("no usó", txt(1))
        self.assertNotIn("implementer", txt(1))

    def proc(self, pid, cpu, nombre="node", cmd="node x.js", ppid=1, rss=100 * 2**20):
        return {"pid": pid, "ppid": ppid, "cpu": cpu, "rss": rss, "nombre": nombre, "cmd": cmd, "args": cmd.split(), "estado": "S", "etime": "1 h 0 min"}

    def test_agrupa_los_procesos_iguales_y_reconoce_la_herramienta(self):
        procs = [self.proc(i, 40.0, cmd="/usr/bin/node --require x/node_modules/vitest/suppress.cjs worker.js") for i in range(16)]
        procs += [self.proc(99, 5.0, nombre="chrome", cmd="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
        g = cm.agrupar_procesos(procs)
        self.assertEqual((g[0]["nombre"], g[0]["n"], round(g[0]["cpu"])), ("node · vitest", 16, 640))      # 16 filas sueltas = una sola
        self.assertEqual(g[1]["n"], 1)
        self.assertEqual(cm.etiqueta_proceso(self.proc(1, 1.0, nombre="python", cmd="python -m pytest tests")), "python · pytest")
        self.assertEqual(cm.etiqueta_proceso(self.proc(1, 1.0, nombre="node", cmd="node server.js")), "node")

    def test_la_cpu_alta_se_atribuye_a_la_sesion_de_claude_que_la_causa(self):
        procs = [self.proc(i, 40.0) for i in range(10)] + [self.proc(500, 5.0, nombre="claude", cmd="claude")]
        claude = [{"pid": 500, "cpu": 5.0, "arbol_cpu": 405.0, "hijos": 10, "proyecto": "-demo-app"}]
        d = self.maquina(cpu=100.0, procs=procs)
        cul = cm.culpable_cpu(d, claude)
        self.assertEqual((cul["pid"], cul["hijos"], round(cul["pct"])), (500, 10, 100))
        e = cm.evaluar_estado(d, [], claude, None)
        self.assertEqual(e[0][0], 1)
        self.assertIn("claude PID 500", e[0][1])
        self.assertIn("tests", e[0][2])
        txt = " ".join(sin_color(t) for t, _ in cm.reporte_vivo(d, [], [], None, claude, None))
        self.assertIn("de claude PID 500", txt)                      # también junto a la barra de CPU
        self.assertIn("10×", txt)

    def test_cpu_alta_sin_culpable_claro(self):
        d = self.maquina(cpu=100.0, procs=[self.proc(i, 30.0, nombre="n%d" % i, cmd="n%d" % i) for i in range(5)])
        claude = [{"pid": 500, "cpu": 1.0, "arbol_cpu": 1.0, "hijos": 0, "proyecto": "-demo-app"}]
        self.assertIsNone(cm.culpable_cpu(d, claude))
        self.assertNotIn("claude PID", cm.evaluar_estado(d, [], claude, None)[0][1])

    def test_alerta_primero_y_cartel(self):
        e = cm.evaluar_estado(self.maquina(), [self.fila(w24=25e6), self.fila(sesion="s2", w5=5e6, w60=5e6)], [], None)
        self.assertEqual([x[0] for x in e], [2, 1])
        L = " ".join(sin_color(t) for t, _ in cm.reporte_vivo(self.maquina(), [self.fila(w24=25e6), self.fila(sesion="s2", w5=5e6, w60=5e6)], [], None, [], None))
        self.assertIn("ALERTA", L)
        self.assertIn("→", L)


@unittest.skipIf(ES_WIN, "la prueba con pseudo-terminal es solo para Mac y Linux")
class PantallaEnVivo(Entorno):
    def test_pantalla_en_vivo_dibuja_responde_y_sale(self):
        try:
            import psutil  # noqa: F401
            import pty
            import select
            import signal
        except ImportError:
            self.skipTest("falta psutil (pip install psutil)")
        import re
        pid, fd = pty.fork()
        if pid == 0:
            os.environ.update(self.env)
            os.environ.update(TERM="xterm-256color", COLUMNS="150", LINES="40")
            os.execvp(sys.executable, [sys.executable, SCRIPT, "--cada", "1"])
        try:
            def leer(seg):
                buf, fin = b"", time.time() + seg
                while time.time() < fin:
                    if select.select([fd], [], [], 0.1)[0]:
                        try:
                            buf += os.read(fd, 65536)
                        except OSError:
                            break
                return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][A-Z0-9]", "", buf.decode("utf-8", errors="ignore"))
            pantalla = leer(6)
            self.assertIn("PROYECTO", pantalla)
            self.assertIn("Procesos que más pesan", pantalla)
            for tecla in (b"z", b"x"):                       # acciones seguras: se CANCELAN. Nunca se manda «s» (terminar).
                os.write(fd, tecla)
                resp = leer(1.2)
                self.assertTrue("identificado" in resp or "Terminar" in resp or "Cuál" in resp, "sin respuesta a la tecla %r: %r" % (tecla, resp[-200:]))
                os.write(fd, b"n")
                leer(0.6)
            os.write(fd, b"q")
            salio = False
            for _ in range(300):                             # hasta 15 s
                leer(0.05)                                   # sigue vaciando la salida mientras espera
                r, _ = os.waitpid(pid, os.WNOHANG)
                if r == pid:
                    salio = True
                    break
            if not salio:
                # Pasa a veces, solo en Docker/OrbStack con terminal simulada: el programa ya terminó su trabajo (quedó «defunct»)
                # pero el kernel tarda en liberar un hilo. En Mac y en uso normal cierra al instante. Se avisa, no se oculta.
                estado = ""
                try:
                    estado = [l for l in open("/proc/%d/status" % pid) if l.startswith("State")][0]
                except (OSError, IndexError):
                    pass
                if "zombie" in estado:
                    print("\n  AVISO: cierre lento tras la q (proceso zombi); ver docs/PENDIENTES.md", file=sys.stderr)
                else:
                    self.fail("no salió al apretar q (%s)" % estado.strip())
        finally:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


if __name__ == "__main__":
    print("claudemon · pruebas con datos inventados · Python %s · %s\n" % (sys.version.split()[0], sys.platform))
    unittest.main(verbosity=2)
