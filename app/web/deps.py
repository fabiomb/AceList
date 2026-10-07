from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.acestream.client import EngineClient
from app.services.batch import CheckRunner
from app.services.settings import AppSettings, load_settings

EngineFactory = Callable[[], EngineClient]


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]


def get_session(factory: SessionFactoryDep) -> Iterator[Session]:
    with factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_settings(session: SessionDep) -> AppSettings:
    return load_settings(session)


SettingsDep = Annotated[AppSettings, Depends(get_settings)]


def get_engine_factory(settings: SettingsDep) -> EngineFactory:
    """Builds engine clients with the saved settings; background checks need their own."""
    return lambda: EngineClient(settings.engine_url, timeout=settings.engine_timeout)


EngineFactoryDep = Annotated[EngineFactory, Depends(get_engine_factory)]


def get_engine_client(factory: EngineFactoryDep) -> Iterator[EngineClient]:
    with factory() as client:
        yield client


EngineDep = Annotated[EngineClient, Depends(get_engine_client)]


def get_check_runner(request: Request) -> CheckRunner:
    return request.app.state.check_runner


CheckRunnerDep = Annotated[CheckRunner, Depends(get_check_runner)]
