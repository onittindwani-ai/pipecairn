import json

import pytest
from sqlalchemy.orm import Session

from support import DATA, NOW, Adapters, RecordingEmail, make_settings
from pipecairn.seeding import load_seed, read_seed
from sendora_core.db import Base, make_engine, make_session_factory


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def factory(settings):
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def session(factory):
    with factory() as s:
        yield s


@pytest.fixture
def adapters(settings):
    a = Adapters(settings)
    a.email = RecordingEmail(settings)
    return a


@pytest.fixture
def seeded(session: Session):
    seed = read_seed(DATA)
    info = load_seed(session, seed, NOW)
    session.commit()
    return {"seed": seed, "info": info, "key": json.loads((DATA / "answer_key.json").read_text())}
