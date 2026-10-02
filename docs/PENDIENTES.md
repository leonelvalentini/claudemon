# Pendientes y límites conocidos

## Sin probar
- **Pantalla en vivo en una consola de Windows:** el teclado (`msvcrt`) y las acciones sobre procesos (`z` pausar, `k` cerrar, `x`) nunca se
  probaron en una consola real. Las pruebas automáticas no pueden simularla (no hay pseudo-terminal en Windows).
- **El instalador en un Windows con varias versiones de Python:** el CI lo prueba con la que trae el entorno; en máquinas reales puede elegir otra.

## Probado
- **Linux, macOS y Windows** con Python 3.8 y 3.12 (macOS solo 3.12) en GitHub Actions, en cada cambio: 35 pruebas con datos inventados,
  más ambos instaladores (`instalar.sh` e `instalar.ps1`) y `claudemon demo`. En Windows se saltea una prueba (la de la terminal simulada).
- **Mac (Python 3.14)** y **Linux en Docker (Python 3.8 y 3.12)**: además, la pantalla en vivo con terminal simulada.
- El CI de Windows encontró dos errores reales en `instalar.ps1` (acentos rotos por falta de BOM y un corte por el modo `Stop` de PowerShell), ya corregidos.

## Comportamiento raro sin resolver
- En Docker/OrbStack, con una terminal simulada (pty) y a veces (~1 de cada 4), el proceso tarda en liberarse tras apretar `q`: queda «defunct»
  con un hilo del kernel colgado. No se reprodujo en Mac, ni con un programa mínimo equivalente, ni midiendo el cierre real (16 de 16 instantáneos), ni en los Linux de GitHub Actions.
  Descartado: el hilo lector, `os._exit`, la forma de salir (también pasa con `SIGKILL`). La prueba lo avisa en vez de fallar.
  Si alguien en Linux real nota que la terminal queda colgada tras `q`, que lo avise con la salida de `claudemon diagnostico`.

## Ideas
- Servicio en segundo plano (launchd/systemd) que avise aunque no haya una terminal abierta.
- Alinear el «período» con el reinicio semanal automáticamente.
- Ver el cupo de claude.ai (hoy solo se ve Claude Code).
