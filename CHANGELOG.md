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
