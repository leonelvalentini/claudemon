# Publicar una versión en PyPI (para quien mantiene el proyecto)

El paquete se llama **`claudemon-cli`** en PyPI (el nombre `claudemon` ya lo usa otro proyecto distinto). El comando que se instala sigue siendo `claudemon`.

```bash
pipx install "claudemon-cli[vivo]"     # recomendado: aislado, con la pantalla en vivo
pip install claudemon-cli              # solo informes (sin psutil)
```

## Una sola vez: configurar "Trusted Publishing"

Así GitHub publica sin que guardes ninguna contraseña ni token.

1. Creá una cuenta en <https://pypi.org> y activá la verificación en dos pasos.
2. Entrá a <https://pypi.org/manage/account/publishing/> y agregá un **pending publisher**:
   - *PyPI project name:* `claudemon-cli`
   - *Owner:* `leonelvalentini` · *Repository name:* `claudemon`
   - *Workflow name:* `publicar.yml` · *Environment name:* `pypi`
3. En GitHub: **Settings → Environments → New environment** y creá uno llamado `pypi`. Conviene agregarte como *required reviewer*,
   así cada publicación te pide una confirmación.

## Cada versión nueva

1. Subí `VERSION` en `claudemon.py` (por ejemplo a `1.0.2`). Es la única fuente: el paquete la lee de ahí.
2. Corré las pruebas y esperá el verde del CI (`tests` y `paquete`).
3. Creá el release en GitHub con una etiqueta igual a la versión (`v1.0.2`) y sus notas. **Al publicarlo, `publicar.yml` sube el paquete a PyPI.**
4. Una versión publicada en PyPI **no se puede reemplazar ni borrar para reusar el número**: si te equivocás, publicá la siguiente.

## Probar el paquete a mano, sin publicar

```bash
python -m pip install build twine
python -m build            # genera dist/*.whl y dist/*.tar.gz
python -m twine check dist/*
python -m venv /tmp/prueba && /tmp/prueba/bin/pip install "dist/$(ls dist | grep whl)[vivo]" && /tmp/prueba/bin/claudemon demo
```

## Si querés publicar con otro nombre

Cambiá `name` en `pyproject.toml` (y el nombre del proyecto en el pending publisher). Antes verificá que esté libre:
`https://pypi.org/pypi/<nombre>/json` tiene que dar *404*.
