"""Ordered adapter registry: first adapter whose matches() is true wins.

Registration is by name, so re-registering an adapter replaces the previous
entry in place instead of adding a duplicate.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .base import Adapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: List[Adapter] = []

    def register(self, adapter: Adapter) -> None:
        self._adapters = [a for a in self._adapters if a.name != adapter.name]
        self._adapters.append(adapter)

    def resolve(self, url: str) -> Optional[Adapter]:
        for adapter in self._adapters:
            if adapter.matches(url):
                return adapter
        return None

    def clear(self) -> None:
        self._adapters.clear()

    @property
    def adapters(self) -> Tuple[Adapter, ...]:
        return tuple(self._adapters)


registry = AdapterRegistry()
