"""Abstract base for auth managers."""
from abc import ABC, abstractmethod


class AuthManager(ABC):
    @abstractmethod
    async def ensure_valid_token(self):
        ...

    @abstractmethod
    async def refresh(self) -> bool:
        ...
