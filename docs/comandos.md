# Todos los comandos

En todos los ejemplos, si no instalaste el comando, reemplazá `claudemon` por `python3 claudemon.py` (Windows: `python claudemon.py`).

## Ver el gasto

| Comando | Qué hace |
|---|---|
| `claudemon sesiones [días]` | Cada sesión con su **nombre**, tokens, USD, qué modelos usó (conversación y subagentes) y qué **tipo de agente** gastó cada modelo. Por defecto 7 días. Al final te da el `claude --resume …` para retomarla. |
| `claudemon modelos [días]` | Quién usó cada modelo, separando **tu conversación** de los **subagentes**, y qué tipo de agente. |
| `claudemon hoy` | Resumen de las últimas 24 h por proyecto. |
| `claudemon historial [N]` | Últimos N días, día por día. |
| `claudemon una-vez` | Una "foto" en texto de la pantalla en vivo (sirve para pegar en un chat o un script). |

**«Tokens nuevos»** = entrada + salida + escritura de caché. Las lecturas de caché se muestran aparte porque son baratas y muy numerosas.

## Llevar la cuenta de un período (una semana, un sprint…)

| Comando | Qué hace |
|---|---|
| `claudemon comenzar ["nombre"]` | Marca el inicio. |
| `claudemon uso` | Cuánto gastaste desde esa marca. |
| `claudemon reset ["nombre"]` | Cierra el período (queda en el historial) y abre otro. |
| `claudemon periodos` | Lista los períodos cerrados. |

## Plan y límites

| Comando | Qué hace |
|---|---|
| `claudemon plan max20` | Tu plan: `pro`, `max5` o `max20`. |
| `claudemon semana mar 09:00` | Día y hora en que se te reinicia la semana (lo ves en Ajustes → Uso de Claude). |
| `claudemon calibrar semana 48` | Le decís el % que muestra `/usage`. También `sesion` y `sonnet`. |
| `claudemon limite 600M` | Fijás un tope a mano (en vez de calibrar). |
| `claudemon limites` | Ventana de 5 horas + semana, con proyección de cuándo te quedás sin cupo. |

Detalle en [planes-y-limites.md](planes-y-limites.md).

## Pantalla en vivo

| Comando | Qué hace |
|---|---|
| `claudemon` | Pantalla en vivo (necesita `pip install psutil`). |
| `claudemon --cada 5` | Actualiza cada 5 s en vez de 3. |
| `claudemon --umbral-5m 2000000` | Alerta si una sesión gasta más de 2 M tokens en 5 min. |
| `claudemon --umbral-cpu 120` | Alerta si un proceso `claude` pasa de 120 % de CPU. |
| `claudemon --notificar` | Además del aviso en pantalla, manda un aviso del sistema. |
| `claudemon --ascii` | Sin símbolos especiales (si tu terminal los muestra mal). |
| `claudemon --sin-color` | Sin colores. También se apagan con la variable `NO_COLOR`. |

## Ayuda y diagnóstico

| Comando | Qué hace |
|---|---|
| `claudemon demo` | Muestra todo con **datos inventados**. No toca los tuyos. |
| `claudemon diagnostico` | Revisa tu instalación y dice qué falla (Python, carpeta de Claude, psutil, formato de registros). |
| `claudemon ayuda [tema]` | Ayuda en pantalla. Temas: sesiones, modelos, uso, limites, vivo, privacidad. |
| `claudemon --version` | Versión. |

## Variables opcionales

| Variable | Para qué |
|---|---|
| `CLAUDE_CONFIG_DIR` | Si tu Claude Code guarda sus datos en otra carpeta que `~/.claude`. |
| `NO_COLOR` | Si existe, no se usan colores (estándar [no-color.org](https://no-color.org)). |
| `CLAUDEMON_COLOR=1` | Fuerza los colores aunque la salida no sea una terminal (útil con `less -R`). |
| `CLAUDEMON_DIR` | Dónde guardar la configuración de claudemon (por defecto `~/.claude/monitor`). |
