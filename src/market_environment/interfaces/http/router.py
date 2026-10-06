"""Aggregate the independently owned HTTP route groups."""

from fastapi import APIRouter

from .routers.collection import router as collection_router
from .routers.health import router as health_router
from .routers.market_environment import router as market_environment_router
from .routers.timezone_preferences import router as timezone_preferences_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(market_environment_router)
api_router.include_router(collection_router)
api_router.include_router(timezone_preferences_router)


__all__ = ["api_router"]
