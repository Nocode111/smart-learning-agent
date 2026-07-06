from datetime import datetime
from sqlalchemy.orm import Session

from app.models.user import User
from app.security import hash_password, verify_password, create_access_token


class AuthService:
    def register(self, db: Session, username: str, password: str, name: str, role: str = "student", grade: str | None = None, major: str | None = None) -> User:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError("用户名已存在")

        user = User(
            username=username,
            password_hash=hash_password(password),
            name=name,
            role=role,
            grade=grade,
            major=major,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def login(self, db: Session, username: str, password: str) -> dict:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise ValueError("用户名或密码错误")
        if not verify_password(password, user.password_hash):
            raise ValueError("用户名或密码错误")

        token = create_access_token(data={"user_id": user.id, "role": user.role})
        return {
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "name": user.name,
                "role": user.role,
                "grade": user.grade,
                "major": user.major,
            },
        }

    def get_me(self, db: Session, user: User) -> dict:
        return {
            "id": user.id,
            "username": user.username,
            "name": user.name,
            "role": user.role,
            "grade": user.grade,
            "major": user.major,
        }


auth_service = AuthService()
