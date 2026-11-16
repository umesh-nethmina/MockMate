import pytest
from fastapi.testclient import TestClient

from app import db as database
from app.db import Base, configure_database
from app.llm import get_llm
from app.llm.fake import FakeLLM
from app.main import app


@pytest.fixture
def engine():
    eng = configure_database("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def db(engine):
    with database.SessionLocal() as session:
        yield session


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(engine, fake_llm):
    app.dependency_overrides[get_llm] = lambda: fake_llm
    yield TestClient(app)  # not used as a context manager, so start-up migrations do not run
    app.dependency_overrides.clear()
