# Privacidad

**Qué hace:** lee los archivos de sesión que Claude Code guarda en `~/.claude/projects/` (o en `CLAUDE_CONFIG_DIR`) y suma números: tokens, modelo, hora, costo.

**Qué NO hace:**
- No envía nada por internet. No tiene código de red.
- No modifica ni borra tus sesiones (solo lectura).
- No muestra ni guarda el contenido de tus conversaciones. Para poner nombre a una sesión usa su título (el que le pusiste con `/rename`, el que genera Claude, o el comienzo del primer mensaje si no hay otro).

**Qué guarda:** solo su configuración en `~/.claude/monitor/` (plan, día de reinicio, topes calibrados, períodos). Se borra con `rm -r ~/.claude/monitor`.

**Pantalla en vivo:** lee la lista de procesos para mostrar CPU y memoria. Las únicas acciones sobre procesos (`z` pausar, `k` cerrar) son sobre procesos `claude`, a pedido tuyo y con confirmación.

**Datos sensibles:** los nombres de sesión pueden mencionar clientes o pacientes si así los nombraste. Antes de pegar la salida de `sesiones` en un chat o mail, revisá que no los incluya.

**Para compartir con el equipo:** el archivo `claudemon.py` no contiene datos de nadie, y `claudemon demo` muestra solo datos inventados.
