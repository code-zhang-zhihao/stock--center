from typing import Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: dict | None = None

    @classmethod
    def ok(cls, data: T):
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, *, code: str, message: str, details: dict | None = None):
        return cls(success=False, error={"code": code, "message": message, "details": details or {}})
