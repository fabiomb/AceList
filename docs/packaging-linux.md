# Empaquetado para Linux

AceList se distribuye para Linux x86-64 en modo carpeta de PyInstaller. El tarball contiene
`AceList/AceList`, `AceList/_internal/` y `AceList/LICENSE.txt`, incluyendo Python, dependencias,
plantillas, estáticos y migraciones. VLC, ffmpeg y Ace Stream Engine siguen siendo programas
externos.

## Compilar

En una distribución Linux x86-64 con Python 3.11 o posterior:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[build]'
.venv/bin/python linux/build.py
.venv/bin/python linux/smoke_test.py --expect-version 1.5.0
```

El resultado queda en `dist/AceList-<versión>-linux-x86_64.tar.gz`, acompañado por su SHA-256.
El binario debe construirse en Linux: PyInstaller no genera binarios de otra plataforma.

Los datos del ejecutable no se escriben en el paquete. Se guardan en
`$XDG_DATA_HOME/AceList` o, si esa variable no existe, en `~/.local/share/AceList`.

## Compatibilidad

El artefacto de release se construye y prueba en Ubuntu. PyInstaller incorpora el intérprete de
Python, pero no glibc; por eso un binario construido en una distribución reciente puede no correr
en otra mucho más antigua. `start.sh` es la alternativa portable para cualquier distribución con
Python 3.11 o posterior.

AceList busca el engine en `PATH` con el nombre `acestreamengine`, y también en `/usr/bin`,
`/usr/local/bin` y `/opt/acestream`. Al iniciarlo añade `--client-console`. También se puede dejar
el engine ejecutándose por separado o indicar otra ruta y URL en Ajustes.
