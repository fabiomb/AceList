from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.acestream.client import EngineClient


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_engine_client() -> Iterator[EngineClient]:
    with EngineClient() as client:
        yield client


SessionDep = Annotated[Session, Depends(get_session)]
EngineDep = Annotated[EngineClient, Depends(get_engine_client)]
