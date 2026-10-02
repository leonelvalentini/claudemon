# Preguntas frecuentes

**¿Me cobra algo o me gasta cupo usar claudemon?**
No. No habla con Claude ni con internet. Solo lee archivos de tu compu.

**¿Mi jefe/compañeros ven lo que hago con esto?**
No. Todo queda en tu máquina. Si querés compartir un dato, copiás vos la salida del comando.

**¿Por qué dice «tokens nuevos» y no el total?**
Porque la mayor parte del total son lecturas de caché (muy baratas y repetidas en cada turno) y distorsionan. «Nuevos» = entrada + salida + escritura de caché.

**¿Los USD son lo que me cobran?**
No. Son el equivalente a precio de API que calcula Claude Code. Con un plan Max pagás una tarifa fija; el USD sirve para **comparar** sesiones.

**¿Por qué no me muestra el porcentaje de mi límite?**
Porque falta calibrar. Mirá `/usage` en Claude Code y corré `claudemon calibrar semana <el %>`. Ver [planes-y-limites.md](planes-y-limites.md).

**¿Por qué el porcentaje no coincide exacto con `/usage`?**
Porque `claudemon` solo ve Claude Code (no claude.ai ni la app), y porque Opus y Sonnet no pesan igual en el cupo real. Es una estimación; recalibrá si cambia tu mezcla.

**Usé Sonnet casi todo el tiempo, pero sale mucho Opus. ¿Por qué?**
Casi seguro son **subagentes**. Corré `claudemon modelos`: separa tu conversación de los subagentes y dice qué tipo de agente. Si un agente del proyecto tiene `model: opus`, corre en Opus sin importar tu modelo.

**¿Puedo cerrar una sesión desde la pantalla en vivo?**
Sí, con `k`. Te pide confirmar. No se pierde nada: la retomás con `claude --resume`.

**¿Puede apagar algo importante por error?**
Solo actúa sobre procesos `claude` y siempre pide confirmación. No toca nada más.

**¿Anda con varias cuentas o carpetas de Claude distintas?**
Sí: apuntá `CLAUDE_CONFIG_DIR` a la carpeta que quieras mirar.

**¿Se actualiza solo si lo dejo abierto?**
La pantalla en vivo, sí (cada 3 s), pero solo mientras la terminal está abierta.

**¿Funciona en Windows?**
Sí. Los informes, los colores y el instalador se prueban automáticamente en Windows en cada cambio. Lo único sin probar en una consola real es la pantalla en vivo interactiva (teclas `z`, `k`, `x`). Si algo falla: `claudemon diagnostico`.
