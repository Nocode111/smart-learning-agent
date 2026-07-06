from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey
from app.database import Base


class Course(Base):
    __tablename__ = "courses"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text)
    teacher_id = Column(BigInteger, ForeignKey("users.id"))
    course_type = Column(String(32), nullable=False, default="teacher")
    owner_id = Column(BigInteger, ForeignKey("users.id"))
    visibility = Column(String(32), nullable=False, default="public")
    source = Column(String(32), nullable=False, default="manual")
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
