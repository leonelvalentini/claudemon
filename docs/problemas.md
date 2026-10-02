# Si algo no anda

Primero, siempre:

```bash
claudemon diagnostico
```
Revisa Python, la carpeta de Claude Code, tus registros y psutil, y te dice qué falla. Si tenés que pedir ayuda, pegá ese resultado.

| Síntoma | Causa y solución |
|---|---|
| `claudemon: command not found` (o «no se reconoce») | Abrí una terminal nueva (el instalador agrega la carpeta al PATH). Mientras tanto: `python3 claudemon.py …`. |
| «No encontré sesiones» | Todavía no usaste Claude Code, o guarda los datos en otro lado. Probá `CLAUDE_CONFIG_DIR=/ruta/a/.claude claudemon sesiones`. |
| «La pantalla en vivo necesita psutil» | `pip install psutil` (o `python3 -m pip install psutil`). Los informes andan sin eso. |
| Veo códigos raros tipo `[1;36m` | Tu terminal no entiende colores. Usá `claudemon --sin-color` (en Windows, Windows Terminal). |
| Veo cuadraditos o signos raros | Corré `claudemon --ascii …`. En Windows, usá Windows Terminal en vez de la consola vieja. |
| La pantalla en vivo no responde a las teclas | Tiene que correr en una terminal real (no dentro de un editor que no sea terminal). Para texto plano: `claudemon una-vez`. |
| Los números parecen bajos | Solo cuenta Claude Code; claude.ai y la app gastan del mismo cupo y no se ven. |
| El % no coincide con `/usage` | Recalibrá: `claudemon calibrar semana <%>`. Mejor con 20 % o más. |
| `No such file`/`Permission denied` en Linux | Ejecutalo con tu usuario normal, no con `sudo`. |
| Error «SyntaxError» al correrlo | Python demasiado viejo: hace falta 3.8 o más (`python3 --version`). |

## Desinstalar

- Mac/Linux: `rm ~/.local/bin/claudemon` y, si querés, `rm -r ~/.claude/monitor` (tu configuración).
- Windows: borrá la carpeta `%USERPROFILE%\claudemon` y `~\.claude\monitor`.
