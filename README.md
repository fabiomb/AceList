# AceList

Catálogo local de enlaces Acestream. Valida el Content ID, comprueba si hay peers, intenta capturar una imagen del stream y permite abrir el canal en un reproductor como VLC. Guarda la fecha de cada verificación porque los enlaces mueren y se reemplazan.

> Estado: **fase 0 en curso**. Existe el esqueleto del proyecto, aún sin funcionalidades; ver [plan.md](plan.md) y [CHANGELOG.md](CHANGELOG.md).

## Funcionalidades previstas

- Alta de canales por Content ID o enlace `acestream://`.
- Validación del hash, conteo de peers y captura de pantalla.
- Historial de verificaciones con fecha.
- Listar, editar (título, hash), borrar, ordenar y filtrar.
- Categoría, idioma y país por canal.
- Botón para abrir en VLC.

## Requisitos

- Windows (otras plataformas no son prioritarias).
- Python 3.11 o superior.
- [Ace Stream Media Center](https://www.acestream.org/) instalado (engine HTTP en `127.0.0.1:6878`).
- VLC instalado.
- ffmpeg en el `PATH` (para las capturas).

## Stack

Python, FastAPI, SQLite + SQLAlchemy, Jinja2 + HTMX, httpx, ffmpeg. Detalle y justificación en [plan.md](plan.md).

## Desarrollo

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\ruff check .
.\.venv\Scripts\pytest
.\.venv\Scripts\python -m app.main   # http://127.0.0.1:8000/health
```

## Uso

Pendiente. Se documentará al completar la fase 0 y se cerrará en la fase 6.

## Hoja de ruta

El seguimiento se hace con [issues de GitHub](https://github.com/fabiomb/AceList/issues), etiquetados por fase (`phase:N`).

| Fase | Objetivo | Issues |
|------|----------|--------|
| 0 | Base del proyecto y spike del engine | [#1](https://github.com/fabiomb/AceList/issues/1), [#2](https://github.com/fabiomb/AceList/issues/2), [#3](https://github.com/fabiomb/AceList/issues/3) |
| 1 | Persistencia | [#4](https://github.com/fabiomb/AceList/issues/4), [#5](https://github.com/fabiomb/AceList/issues/5) |
| 2 | Verificación | [#6](https://github.com/fabiomb/AceList/issues/6) a [#10](https://github.com/fabiomb/AceList/issues/10) |
| 3 | Gestión de canales | [#11](https://github.com/fabiomb/AceList/issues/11), [#12](https://github.com/fabiomb/AceList/issues/12) |
| 4 | Interfaz | [#13](https://github.com/fabiomb/AceList/issues/13) a [#16](https://github.com/fabiomb/AceList/issues/16) |
| 5 | Reproducción y ajustes | [#17](https://github.com/fabiomb/AceList/issues/17), [#18](https://github.com/fabiomb/AceList/issues/18) |
| 6 | Calidad y cierre | [#19](https://github.com/fabiomb/AceList/issues/19) a [#22](https://github.com/fabiomb/AceList/issues/22) |

## Documentos

- [idea.md](idea.md): idea original.
- [plan.md](plan.md): alcance, arquitectura, modelo de datos y fases.
- [docs/engine-api.md](docs/engine-api.md): API del engine de Acestream observada en la práctica.
- [CHANGELOG.md](CHANGELOG.md): registro de cambios.
