# Changelog

Todos los cambios relevantes del proyecto se registran aquí. Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado [SemVer](https://semver.org/lang/es/).

## [Sin publicar]

### Agregado
- Plan de desarrollo en `plan.md`: alcance, arquitectura, modelo de datos, fases y riesgos.
- 22 issues de GitHub (#1 a #22) organizados en 7 fases con etiquetas `phase:0` a `phase:6`.
- `README.md` con funcionalidades previstas, requisitos y hoja de ruta.
- `CHANGELOG.md`.
- Project skeleton (#1): `pyproject.toml`, package `app/` with a `/health` endpoint bound to `127.0.0.1`, `.gitignore`, ruff and pytest configuration, and a first test suite.
- GitHub Actions workflow (#2) running ruff and pytest on Python 3.11 and 3.12 over `windows-latest`.
- `docs/engine-api.md` (#3): Acestream engine HTTP API observed against engine 3.1.74, including session states, error behavior, the Content ID vs infohash difference, and a validated ffmpeg frame capture.
- Database schema (#4): SQLAlchemy models for `channel`, `category`, `check_result` and `setting`, SQLite session factory with foreign keys enforced, and the initial Alembic migration in `migrations/`. Content ID format, check status values and category-in-use deletion are enforced by the database.
- Service layer (#5): `app/services` with create, read, update and delete for channels and categories, check history (newest first) and the latest check of every channel. Deleting a channel removes its history and screenshot files (never outside the data directory). Errors are typed (`NotFoundError`, `DuplicateError`, `CategoryInUseError`, `ValidationError`).
- Content ID parsing (#6): `parse_content_id()` accepts a bare Content ID or an `acestream://` link in any letter case and returns it as 40 lowercase hex characters; anything else raises `InvalidContentIdError`.
- Engine client (#7): `EngineClient` for the Acestream HTTP API (version, start stream, stats, stop, and a `stream()` context manager that always stops the session), typed engine errors, and configurable URL and timeout (`ACELIST_ENGINE_URL`, `ACELIST_ENGINE_TIMEOUT`). Engine-provided URLs are rebased onto the configured engine.
- Verification service (#8): `verify()`, `probe()` and `verify_async()` classify a channel as `alive`, `no_peers`, `not_found` or `error`. Alive means the engine reached `dl` with data and at least `min_peers` peers; `VerificationSettings` makes peers, timeout and poll interval configurable.
- Screenshot capture (#9): `capture_screenshot()` saves one frame of a live stream with ffmpeg under `data/screenshots/` and returns a path relative to the data directory. ffmpeg runs without a shell, only http(s) URLs are accepted, partial files are never left behind, and a missing ffmpeg raises a clear `FfmpegNotFoundError`. Configurable with `ACELIST_FFMPEG_PATH` and `ACELIST_SCREENSHOT_TIMEOUT`.
- Check history (#10): `record_verification()` stores a verification outcome (date, status, peers, speed, infohash, screenshot, error) as the newest entry of a channel's history. A channel's current state is always its latest check, never its best one.
- Channel catalog (#11): `add_channel()`, `edit_channel()` and `check_channel()` tie together link parsing, verification, screenshot and history. Duplicates are rejected naming the existing channel, a changed Content ID is verified again keeping the history, and an unreachable engine still saves the channel with an `error` check. `verify()` gained an `on_alive` hook that runs while the stream is still playing.
- Language and country (#12): channels now validate and normalize ISO 639-1 language codes (lowercase) and ISO 3166-1 alpha-2 country codes (uppercase) on add and edit, and `language_choices()` / `country_choices()` provide the value lists for forms. Adds the `pycountry` dependency.
- Channel list page (#13): the app now serves a web UI at `http://127.0.0.1:8000/` with a Jinja2 + HTMX base layout (htmx 2.0.4 vendored under `app/web/static/`, no internet needed) and a table of channels showing thumbnail, title, Content ID, category, language, country, current status, peers and the date of the last check, plus an empty state. Only the screenshots folder of the data directory is served, and requests naming any host other than `127.0.0.1` or `localhost` are rejected.
