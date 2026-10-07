from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.acestream.client import EngineClient
from app.services.settings import AppSettings, load_settings


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_settings(session: SessionDep) -> AppSettings:
    return load_settings(session)


SettingsDep = Annotated[AppSettings, Depends(get_settings)]


def get_engine_client(settings: SettingsDep) -> Iterator[EngineClient]:
    with EngineClient(settings.engine_url, timeout=settings.engine_timeout) as client:
        yield client


EngineDep = Annotated[EngineClient, Depends(get_engine_client)]
