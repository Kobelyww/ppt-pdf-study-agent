from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def get_engine(database_url: str = "sqlite:///study_agent.db", **kwargs) -> Engine:
    """Create a SQLAlchemy engine for local persistence."""
    return create_engine(database_url, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
