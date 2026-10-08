# Empaquetado para Windows

Resultado de la prueba de #75 (2026-10-08): AceList empaquetado con **PyInstaller 6.22.3** (hooks-contrib 2026.8) en **modo carpeta** (`--onedir`), desde Python 3.13 en Windows 11.

## Resumen

| Pregunta | Respuesta |
|----------|-----------|
| ¿Funciona sin Python instalado? | Sí. `AceList.exe` + `_internal\` con Python, dependencias, plantillas, estáticos y migraciones. |
| ¿Funciona todo? | Portada, galería, alta de canal, subida de un `.m3u` (python-multipart), exportación y los 442 idiomas y países de pycountry. |
| ¿Migraciones? | Se aplican desde código con `alembic.command.upgrade`, apuntando a `alembic.ini` y `migrations\` dentro del paquete (`sys._MEIPASS`). |
| ¿Tamaño? | 59 MB (zip de 29,5 MB). Sin las traducciones de pycountry: **38,5 MB** (zip de **22 MB**). |
| ¿Antivirus? | Windows Defender (escaneo personalizado de la carpeta): sin amenazas. |
| ¿Tiempo de build? | ~70 s. |

## Qué hay que incluir a mano

PyInstaller encuentra los módulos solo (tiene hooks para uvicorn, SQLAlchemy, Jinja2 y pycountry), pero no los archivos que la app lee del disco. Sin ellos, el arranque falla con `Directory '...\_internal\app\web\static' does not exist`.

| Origen | Destino en el paquete |
|--------|-----------------------|
| `app/web/templates` | `app/web/templates` |
| `app/web/static` | `app/web/static` |
| `migrations` | `migrations` |
| `alembic.ini` | `.` |

`migrations\` va como **código fuente**: Alembic carga `env.py` y las revisiones desde la carpeta.

## Qué cambia en la app

- **La base no existe hasta aplicar las migraciones.** Sin ellas, `/health` responde pero la portada da 500 (`unable to open database file`). El lanzador (#77) tiene que migrar antes de servir.
- **Los datos no pueden quedar en el paquete:** `config.py` los pone en `ROOT_DIR / "data"`, que empaquetado sería `_internal\data`. Se perderían al actualizar y fallaría en carpetas protegidas. Van a `%LOCALAPPDATA%\AceList` (#76).
- **Avisos que se pueden ignorar:** `Hidden import "pysqlite2" / "MySQLdb" / "psycopg2" / "tzdata" not found`. Son drivers y datos opcionales que AceList no usa.

## Tamaño

| Contenido de `_internal\` | Tamaño |
|---------------------------|--------|
| `pycountry` (de los cuales `locales\`: 20 MB) | 22 MB |
| `python313.dll` | 5,9 MB |
| `pydantic_core` | 5,0 MB |
| `libcrypto-3.dll` | 5,0 MB |
| resto | ~20 MB |

`pycountry\locales\` son traducciones de los nombres. AceList muestra los nombres en inglés y no las usa, así que se excluyen. El paquete recortado sigue listando los 442 idiomas y países.

## Pendiente

- **Firma de código:** sin firma, SmartScreen avisa la primera vez ("Windows protegió su PC" → "Más información" → "Ejecutar de todos modos"). Decidido no firmar por ahora.
- **Antivirus de terceros:** solo se probó Windows Defender. Los ejecutables de PyInstaller a veces dan falsos positivos en otros antivirus; el modo carpeta es el menos afectado.
- **Versión de Python del paquete:** la prueba usó 3.13. El build del CI fijará la versión (#79).
