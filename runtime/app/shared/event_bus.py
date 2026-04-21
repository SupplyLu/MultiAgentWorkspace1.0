from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any, Callable
import logging

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Event:
    event_type: str
    payload: Any = None
    source: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


class EventBus:
    """Minimal in-process event bus for runtime components."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}
        self._lock = RLock()

    def subscribe(self, event_type: str, callback: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, [])
            if callback not in self._subscribers[event_type]:
                self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable[[Event], None]) -> None:
        with self._lock:
            callbacks = self._subscribers.get(event_type, [])
            if callback in callbacks:
                callbacks.remove(callback)
            if not callbacks and event_type in self._subscribers:
                self._subscribers.pop(event_type, None)

    def publish(self, event_type: str, payload: Any = None, source: str | None = None) -> Event:
        event = Event(event_type=event_type, payload=payload, source=source)
        with self._lock:
            callbacks = list(self._subscribers.get(event_type, []))
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                logger.exception("Event handler failed for %s", event_type)
        return event

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()
