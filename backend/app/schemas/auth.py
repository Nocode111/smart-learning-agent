from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    name: str
    role: str = "student"
    grade: str | None = None
    major: str | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    grade: str | None = None
    major: str | None = None

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    token: str
    user: UserResponse
