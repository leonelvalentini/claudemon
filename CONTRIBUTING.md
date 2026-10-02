# Cómo contribuir a claudemon

¡Gracias por querer mejorarlo! Todo aporte suma: reportes de errores, ideas, pruebas en otros sistemas, documentación o código.

## Lo que más ayuda

- **Probar la pantalla en vivo en una consola de Windows.** Los informes y el instalador ya corren en Windows en el CI, pero el teclado interactivo (pausar y cerrar sesiones con `z`/`k`) nunca se probó en una consola real. Un reporte tuyo (de que anda o de que falla) vale mucho.
- **Reportar datos que no cierran:** una sesión sin nombre, un modelo mal detectado, USD que no coinciden, formatos de registro nuevos de Claude Code.
- **Terminales y sistemas distintos:** colores que no se ven bien, símbolos raros, otras distribuciones de Linux.

## Reportar un problema

Abrí un *issue* con la plantilla y pegá la salida de:

```bash
claudemon diagnostico
```

**Antes de pegar nada, revisá que no incluya datos sensibles.** Los nombres de tus sesiones pueden mencionar clientes o proyectos privados:
tachalos. Nunca pegues el contenido de tus conversaciones ni tus archivos de sesión.

## Proponer un cambio

1. Hacé un *fork* y creá una rama (`git checkout -b mi-mejora`).
2. Hacé el cambio, chico y enfocado. Un cambio por *pull request*.
3. Corré las pruebas:
   ```bash
   pip install psutil
   python tests/test_claudemon.py
   ```
   Tienen que pasar. Usan solo datos inventados y nunca tocan tus sesiones reales.
4. Si arreglás un error o agregás algo, **agregá una prueba** en `tests/test_claudemon.py`.
5. Abrí el *pull request* con la plantilla. Se corren las pruebas automáticamente en Linux, macOS y Windows.

## Reglas del proyecto

- **Un solo archivo.** `claudemon.py` se copia y se usa sin instalar nada: no agregues dependencias para los informes. `psutil` es opcional y solo para la pantalla en vivo.
- **Solo lectura, sin red.** claudemon nunca modifica las sesiones de Claude Code, no manda datos a ningún lado ni usa internet. Un cambio que rompa esto no se acepta.
- **Python 3.8 o más nuevo.** No uses sintaxis más moderna (`X | Y` en tipos, `match`, `str.removeprefix`…).
- **El color nunca cambia el texto.** Todo color pasa por la función `c()`, se aplica *después* de alinear (`rel()`), y se apaga solo si no hay terminal. Hay una prueba que lo verifica.
- **Funciona en las tres plataformas.** Si usás algo de un sistema (señales, `termios`…), pensá qué pasa en Windows.
- **Honestidad ante todo.** Si un dato es una estimación o depende de una calibración, el programa tiene que decirlo y no inventar precisión.
- **Idioma:** la interfaz y la documentación están en español rioplatense. Los nombres internos pueden seguir el estilo del archivo.

## Estructura

```
claudemon.py       el programa (un solo archivo)
tests/             pruebas con datos inventados
docs/              guías en español
instalar.sh/.ps1   instaladores
```

## Dudas

Abrí un *issue* con la etiqueta de pregunta. Cualquier tamaño de aporte es bienvenido.
