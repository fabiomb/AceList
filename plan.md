# Plan de desarrollo — AceList

Aplicación local para catalogar enlaces Acestream (Content ID), verificar si siguen vivos y abrirlos en un reproductor. Ver [idea.md](idea.md) para el origen del proyecto.

## 1. Alcance

**Incluye (v1.0)**

- Alta de canales a partir de un Content ID o enlace `acestream://`.
- Validación del hash, conteo de peers y captura de pantalla del stream.
- Historial de verificaciones con fecha (los enlaces mueren y se reemplazan).
- Listado, edición, borrado, orden y filtros.
- Categoría, idioma y país por canal.
- Botón para abrir el canal en un reproductor externo (VLC).
- Funcionamiento en Windows con Ace Stream Media Center instalado.

**Fuera de alcance (por ahora)**

- Acceso remoto, multiusuario, autenticación.
- Empaquetado para macOS/Linux (se evita código específico de Windows donde sea posible).
- Descubrimiento automático de canales.

## 2. Decisiones de arquitectura

| Tema | Decisión | Motivo / alternativa |
|------|----------|----------------------|
| Lenguaje | Python 3.11+ | Portabilidad futura. |
| Backend | FastAPI + Uvicorn, escuchando solo en `127.0.0.1` | Uso local exclusivo; sin exposición a la red. |
| UI | Web local (Jinja2 + HTMX, sin build de frontend) | Un solo proceso, sin toolchain JS. Alternativa: GUI de escritorio (PySide6), más pesada y menos portable. |
| Persistencia | SQLite + SQLAlchemy 2.x (migraciones con Alembic) | Archivo único, sin servidor. |
| Cliente Acestream | `httpx` contra la API HTTP del engine (`127.0.0.1:6878`) | Es la interfaz oficial del engine. |
| Capturas | `ffmpeg` sobre la `playback_url` del engine | Un solo frame, sin abrir ventana de reproductor. |
| Reproductor | Subproceso a VLC con la `playback_url` / `acestream://` | VLC ya instalado en el sistema. |
| Tests | `pytest`, engine simulado con `respx` | Verificar sin depender de streams reales. |
| Calidad | `ruff` + `pytest` en GitHub Actions | |

> Supuestos a validar en la fase 0 (spike): endpoints exactos del engine (`/ace/getstream?format=json`, `stat_url`, `command_url`), tiempos de arranque del stream y comportamiento con hashes inexistentes.

## 3. Modelo de datos (borrador)

- **channel**: `id`, `title`, `content_id` (40 hex, único), `category_id`, `language` (ISO 639-1), `country` (ISO 3166-1 alpha-2), `created_at`, `updated_at`.
- **category**: `id`, `name` (único).
- **check** (verificación): `id`, `channel_id`, `checked_at`, `status` (`alive` / `no_peers` / `not_found` / `error`), `peers`, `speed_down`, `screenshot_path`, `error_message`.
- **setting**: `key`, `value` (URL del engine, ruta de VLC, ruta de ffmpeg).

El estado "actual" de un canal se deriva de su última verificación; el historial completo se conserva.

## 4. Estructura propuesta

```
aceList/
  app/
    main.py            # FastAPI, arranque
    config.py          # ajustes y rutas
    db/                # modelos, sesión, migraciones
    acestream/         # cliente del engine, validación de hash
    services/          # verificación, capturas, reproductor
    web/               # rutas, templates, estáticos
  data/                # SQLite y capturas (ignorado por git)
  tests/
```

## 5. Fases

Cada fase tiene su(s) issue(s) en GitHub (etiqueta `phase:N`).

| Fase | Objetivo | Entregable |
|------|----------|------------|
| 0 | Base del proyecto y spike del engine | Esqueleto ejecutable, CI, API del engine documentada |
| 1 | Persistencia | Modelos, migraciones, repositorios |
| 2 | Verificación | Validación de hash, peers/estado, captura, historial |
| 3 | Gestión de canales | CRUD + categorías, idioma y país |
| 4 | Interfaz | Listado, formularios, orden y filtros |
| 5 | Reproducción y ajustes | Abrir en VLC, configuración de rutas |
| 6 | Calidad y cierre | Re-verificación, importación masiva, tests, documentación |

### Fase 0 — Base
1. Esqueleto del proyecto (pyproject, estructura, ruff, pytest).
2. CI en GitHub Actions.
3. Spike: documentar la API del engine con los hashes de referencia.

### Fase 1 — Persistencia
4. Modelos SQLAlchemy y migración inicial.
5. Capa de repositorio/servicio para canales, categorías y verificaciones.

### Fase 2 — Verificación
6. Parseo y validación de Content ID / enlace `acestream://`.
7. Cliente del engine (detección, estado, parada de sesión).
8. Servicio de verificación de peers y disponibilidad.
9. Captura de pantalla con ffmpeg.
10. Historial de verificaciones con fecha.

### Fase 3 — Gestión
11. CRUD de canales (alta con verificación automática).
12. Categorías, idioma y país.

### Fase 4 — Interfaz
13. Layout base y listado de canales.
14. Formularios de alta y edición, borrado con confirmación.
15. Orden y filtros.
16. Vista de detalle con historial y capturas.

### Fase 5 — Reproducción y ajustes
17. Abrir en VLC.
18. Pantalla de ajustes y autodetección de rutas.

### Fase 6 — Cierre
19. Re-verificación individual y masiva (en segundo plano).
20. Importación masiva de enlaces.
21. Tests de integración y manejo de errores del engine.
22. Documentación de uso y script de arranque para Windows.

## 6. Riesgos

| Riesgo | Mitigación |
|--------|------------|
| El engine tarda o no responde con hashes muertos | Timeouts configurables, estados explícitos, verificación asíncrona. |
| Sin peers no hay frames para la captura | La captura es opcional; se registra `screenshot_path = null`. |
| Engine no instalado o apagado | Detección al inicio y mensaje claro; intento de arranque opcional. |
| API del engine sin documentación estable | Spike en fase 0 y capa de cliente aislada. |
| Inyección de comandos al lanzar VLC/ffmpeg | Content ID validado (40 hex), subprocesos sin shell y con lista de argumentos. |

## 7. Seguimiento

- Tareas: issues de GitHub con etiquetas `phase:N`.
- Cambios: [CHANGELOG.md](CHANGELOG.md) (formato Keep a Changelog).
- Estado general: [README.md](README.md).
