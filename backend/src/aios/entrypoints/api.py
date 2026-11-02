"""FastAPI application and composition root (the only place that wires adapters to ports)."""

from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aios import __version__
from aios.modules.pricing.adapters.settings_discount_limits import SettingsDiscountLimits
from aios.modules.pricing.api.router import build_router as build_pricing_router
from aios.modules.pricing.application.service import PricingService
from aios.shared.config import get_settings
from aios.shared.errors import AIOSError, InvalidInputError, NotFoundError
from aios.shared.logs import configure_logging

_STATUS_BY_ERROR: dict[type[AIOSError], int] = {InvalidInputError: 422, NotFoundError: 404}


@lru_cache(maxsize=1)
def get_pricing_service() -> PricingService:
    return PricingService(SettingsDiscountLimits(get_settings()))


async def _handle_aios_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AIOSError)  # noqa: S101 - narrowing for the type checker
    status = _STATUS_BY_ERROR.get(type(exc), 400)
    return JSONResponse(status_code=status, content={"code": exc.code, "detail": exc.message})


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="AI OS - CRM Copilot", version=__version__)
    app.add_exception_handler(AIOSError, _handle_aios_error)
    app.include_router(build_pricing_router(get_pricing_service))

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "env": settings.env.value}

    return app


app = create_app()
