"""Custom exceptions for the AEGIS SDK."""

from __future__ import annotations

from typing import Any


class AegisAPIError(RuntimeError):
    """Raised when the AEGIS API returns a structured HTTP error response."""

    def __init__(
        self,
        status_code: int,
        message: str,
        payload: Any = None,
        error_code: str | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(f"AEGIS API HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload
        self.error_code = error_code
        self.detail = detail

    @classmethod
    def from_response(cls, status_code: int, raw_payload: Any) -> AegisAPIError:
        """Parse structured FastAPI / Starlette error payloads (str, dict, or list of dicts)."""
        error_code: str | None = None
        detail: Any = None
        message: str = f"Request failed with HTTP {status_code}"

        if isinstance(raw_payload, dict):
            detail = raw_payload.get("detail")
            error_code = raw_payload.get("error_code") or raw_payload.get("error")

            if isinstance(detail, str):
                message = detail
            elif isinstance(detail, dict):
                error_code = detail.get("error_code") or detail.get("error") or error_code
                message = detail.get("message") or str(detail)
            elif isinstance(detail, list):
                # FastAPI validation error array: [{'loc': ['body', 'x'], 'msg': '...', 'type': '...'}]
                error_code = error_code or "VALIDATION_ERROR"
                parts: list[str] = []
                for item in detail:
                    if isinstance(item, dict):
                        loc_list = item.get("loc", [])
                        loc = ".".join(str(p) for p in loc_list if str(p) != "body") if loc_list else ""
                        msg = item.get("msg", "")
                        parts.append(f"{loc}: {msg}" if loc else msg)
                    else:
                        parts.append(str(item))
                message = "; ".join(parts) if parts else "Request validation failed."
            elif "message" in raw_payload:
                message = str(raw_payload["message"])
            elif "msg" in raw_payload:
                message = str(raw_payload["msg"])
            else:
                message = str(raw_payload)

        elif isinstance(raw_payload, list):
            detail = raw_payload
            error_code = "VALIDATION_ERROR"
            parts = [str(x) for x in raw_payload]
            message = "; ".join(parts)
        elif isinstance(raw_payload, str):
            detail = raw_payload
            message = raw_payload.strip() or message

        return cls(
            status_code=status_code,
            message=message,
            payload=raw_payload,
            error_code=error_code,
            detail=detail,
        )
