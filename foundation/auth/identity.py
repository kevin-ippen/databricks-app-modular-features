from pydantic import BaseModel, Field
from typing import Any, Protocol, Optional, Callable, Dict, Literal

class TokenSource(Protocol):
    def bearer_token(self) -> str: ...


class OboTokenSource(TokenSource):
    def __init__(self, headers_getter: Callable[[], Dict[str, str]]):
        self._headers_getter = headers_getter

    def bearer_token(self) -> str:
        h = self._headers_getter() or {}
        return h.get("x-forwarded-access-token")


class PatTokenSource(TokenSource):
    def __init__(self, pat: Optional[str]):
        self._pat = pat

    def bearer_token(self) -> str:
        return self._pat


class Identity(BaseModel):
    email: Optional[str] = None
    display_name: Optional[str] = None
    auth_type: Literal["obo", "pat"] = "pat"
    # The token source that provides the bearer token for authentication
    # Using Field(repr=False) to prevent the token from being exposed in string representations
    # Type Any is used since TokenSource is a Protocol and can't be used directly in Pydantic
    token_source: Any = Field(repr=False)
