from datetime import datetime
from sqlalchemy import Column, BigInteger, String, DateTime
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False, comment="student/teacher/admin")
    grade = Column(String(32))
    major = Column(String(64))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
