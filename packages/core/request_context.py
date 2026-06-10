from __future__ import annotations

from contextvars import ContextVar
from typing import Optional


_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def set_correlation_id(value: Optional[str]) -> None:
	_correlation_id.set(value)


def get_correlation_id() -> Optional[str]:
	return _correlation_id.get()


def set_request_id(value: Optional[str]) -> None:
	_request_id.set(value)


def get_request_id() -> Optional[str]:
	return _request_id.get()


def clear_request_context() -> None:
	_correlation_id.set(None)
	_request_id.set(None)
