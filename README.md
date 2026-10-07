# AceList

Catálogo local de enlaces Acestream. Valida el Content ID, comprueba si hay peers, intenta capturar una imagen del stream y permite abrir el canal en VLC. Guarda la fecha de cada verificación porque los enlaces mueren y se reemplazan.

> Versión **1.0.0**. Ver [CHANGELOG.md](CHANGELOG.md) y [plan.md](plan.md).

## Funcionalidades

- Alta de canales por Content ID o enlace `acestream://`, con verificación automática.
- Importación masiva: un enlace por línea o una lista M3U.
- Verificación con el engine de Ace Stream: estado, peers y una captura del stream con ffmpeg.
- Historial de verificaciones con fecha y captura de cada una.
- Re-verificación de un canal o de todos los del listado filtrado, en segundo plano y con progreso.
- Listado con orden (título, alta, última verificación, peers, estado) y filtros (texto, categoría, idioma, país, estado), guardables en marcadores.
- Edición y borrado con confirmación; categoría, idioma y país por canal.
- Botón para abrir el canal en VLC.
- Ajustes con autodetección de VLC, ffmpeg y el engine, y prueba de conexión.

## Requisitos

- Windows 10 u 11 (otras plataformas no se prueban).
- [Python](https://www.python.org/downloads/) 3.11 o superior.
- [Ace Stream Media](https://www.acestream.org/) instalado y abierto (su engine responde en `http://127.0.0.1:6878`).
- [VLC](https://www.videolan.org/vlc/) para reproducir.
- [ffmpeg](https://ffmpeg.org/download.html) para las capturas (opcional: sin ffmpeg los canales se verifican igual, sin imagen).

## Instalación y arranque

1. Descarga o clona el repositorio.
2. Haz doble clic en **`start.bat`**.

La primera vez crea el entorno virtual e instala las dependencias (tarda un minuto). Después aplica las migraciones de la base de datos, arranca el servidor y abre `http://127.0.0.1:8000/` en el navegador. Para detenerlo, pulsa Ctrl+C en la ventana de la consola o ciérrala.

Desde PowerShell se pueden pasar opciones:

```powershell
.\start.ps1 -Port 8080      # otro puerto
.\start.ps1 -NoBrowser      # no abrir el navegador
```

Si AceList ya está funcionando, el script solo abre el navegador.

## Uso

1. **Ajustes.** La primera vez, entra en *Ajustes*, pulsa **Autodetectar rutas** y luego **Guardar**. Con **Probar conexión** se comprueba que el engine de Ace Stream responde.
2. **Agregar un canal.** En *Canales → Agregar canal*, pega un Content ID (40 caracteres hexadecimales) o un enlace `acestream://`, ponle título y, si quieres, categoría, idioma y país. Al guardar se verifica con el engine: puede tardar unos segundos.
3. **Importar varios.** En *Importar*, pega una lista con un enlace por línea. El texto junto al enlace se usa como título (`Partido - acestream://…`), y en una lista M3U se usa el título de `#EXTINF`. El resumen indica qué se creó, qué estaba repetido y qué líneas no se entendieron. Los canales nuevos se verifican en segundo plano.
4. **Revisar el catálogo.** El listado muestra la miniatura, el estado y los peers de la **última** verificación. Haz clic en las cabeceras para ordenar y usa la barra de filtros; la URL guarda la vista. **Verificar los N canales** vuelve a comprobar lo que se ve, en segundo plano, con una barra de progreso.
5. **Detalle.** Al hacer clic en un título se ve la última captura, todos los datos y el historial de verificaciones. Desde allí se puede **verificar de nuevo**, **abrir en el reproductor**, editar o borrar.
6. **Reproducir.** **Reproducir** (en el listado) o **Abrir en reproductor** (en el detalle) inicia el stream en el engine y lo abre en VLC.

### Estados de un canal

| Estado | Significado |
|--------|-------------|
| Activo | El engine descargó datos con al menos los peers mínimos configurados. |
| Sin peers | El engine encontró el contenido pero no llegaron datos a tiempo. Puede revivir más tarde. |
| No encontrado | El engine no pudo cargar el Content ID: el enlace probablemente murió. |
| Error | No se pudo verificar (engine apagado, timeout, respuesta inesperada). Al pasar el ratón se ve el motivo. |
| Sin verificar | Todavía no tiene ninguna verificación. |

## Configuración

Los valores de *Ajustes* se guardan en la base de datos y tienen prioridad. Las variables de entorno sirven de valores por defecto:

| Variable | Por defecto | Uso |
|----------|-------------|-----|
| `ACELIST_DATA_DIR` | `data` | Carpeta de la base de datos (`acelist.db`) y las capturas (`screenshots/`). |
| `ACELIST_PORT` | `8000` | Puerto local del servidor. |
| `ACELIST_ENGINE_URL` | `http://127.0.0.1:6878` | URL del engine de Ace Stream. |
| `ACELIST_ENGINE_TIMEOUT` | `15` | Segundos de espera de cada petición al engine. |
| `ACELIST_VLC_PATH` | autodetección | Ruta de `vlc.exe`. |
| `ACELIST_FFMPEG_PATH` | `PATH` | Ruta de `ffmpeg.exe`. |
| `ACELIST_SCREENSHOT_TIMEOUT` | `30` | Segundos máximos para sacar una captura. |
| `ACELIST_CHECK_CONCURRENCY` | `2` | Verificaciones simultáneas en segundo plano. |

Para hacer una copia de seguridad basta con copiar la carpeta `data/`.

## Seguridad

AceList es para uso local:

- Escucha solo en `127.0.0.1` y rechaza peticiones dirigidas a otros nombres de host (protección contra DNS rebinding).
- Rechaza envíos de formularios que vengan de otros sitios web (protección CSRF).
- VLC y ffmpeg se ejecutan sin shell, con argumentos validados.

No hay usuarios ni contraseñas: no lo expongas a la red.

## Solución de problemas

| Síntoma | Qué revisar |
|---------|-------------|
| Todo sale en "Error" | Que Ace Stream esté abierto. En *Ajustes*, **Probar conexión**. |
| "No se encontró VLC" | Instala VLC o indica la ruta de `vlc.exe` en *Ajustes*. |
| Canales activos sin captura | ffmpeg no está instalado o no se encuentra: **Autodetectar rutas** en *Ajustes* o indica la ruta de `ffmpeg.exe`. |
| El navegador no abre la página | Otro programa usa el puerto 8000: `.\start.ps1 -Port 8080`. |
| "Hace falta Python 3.11 o superior" | Instala Python desde python.org marcando *Add python.exe to PATH*. |

## Desarrollo

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\ruff check .
.\.venv\Scripts\ruff format --check .
.\.venv\Scripts\pytest --cov        # falla por debajo del 95% de cobertura
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m app.main  # http://127.0.0.1:8000/
```

Los tests no necesitan el engine ni ffmpeg: el engine se simula con `respx` y nunca se contacta uno real.

Stack: Python, FastAPI, SQLite + SQLAlchemy (Alembic), Jinja2 + HTMX, httpx, ffmpeg. Detalle y justificación en [plan.md](plan.md).

## Hoja de ruta

El seguimiento se hace con [issues de GitHub](https://github.com/fabiomb/AceList/issues), etiquetados por fase (`phase:N`). Las siete fases de la versión 1.0 están completas.

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
