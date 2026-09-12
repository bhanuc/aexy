"""Walking the mounted route tree.

`app.routes` used to be a flat list of `APIRoute`s, and several tests read
`route.path` and `route.dependencies` straight off it. FastAPI 0.141 made
`include_router` lazy: `app.routes` now holds `_IncludedRouter` objects that
expand on demand and carry no `.path` of their own.

That broke the checks in two different ways. One raised `AttributeError` and
failed loudly. The other used `getattr(route, "path", "")`, matched nothing,
counted zero and **passed** — a ledger of ungated routes that had quietly
stopped counting anything.

So the walk lives here, once, and yields what those tests actually need: the
full mounted path, and every dependency that applies to it — the route's own
plus the ones added at each `include_router(dependencies=[...])` on the way
down, which is where a mounting mistake is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute, _IncludedRouter


@dataclass(frozen=True)
class MountedRoute:
    #: The path as mounted, including every prefix.
    path: str
    #: HTTP methods; empty for a websocket.
    methods: frozenset[str]
    #: Names of every dependency that applies, mount-time ones included.
    dependency_names: tuple[str, ...]
    route: Any

    @property
    def is_websocket(self) -> bool:
        return not self.methods


def _names(dependencies: Any) -> tuple[str, ...]:
    return tuple(
        getattr(d.dependency, "__name__", type(d.dependency).__name__)
        for d in (dependencies or ())
    )


def walk_routes(
    routes: Any, prefix: str = "", inherited: tuple[str, ...] = ()
) -> Iterator[MountedRoute]:
    for route in routes:
        if isinstance(route, _IncludedRouter):
            context = route.include_context
            yield from walk_routes(
                route.original_router.routes,
                prefix + (context.prefix or ""),
                inherited + _names(context.dependencies),
            )
        elif isinstance(route, (APIRoute, APIWebSocketRoute)):
            yield MountedRoute(
                path=prefix + route.path,
                methods=frozenset(getattr(route, "methods", None) or ()),
                dependency_names=inherited + _names(route.dependencies),
                route=route,
            )
        elif hasattr(route, "routes"):
            # A sub-application mounted with `app.mount`.
            yield from walk_routes(
                route.routes, prefix + getattr(route, "path", ""), inherited
            )


def mounted_routes(app: FastAPI) -> list[MountedRoute]:
    """Every route the app actually serves, with its effective dependencies."""
    found = list(walk_routes(app.routes))
    # A walk that finds nothing is the failure mode this module exists to
    # prevent: it reads as "no route breaks the rule" instead of "the rule
    # was never checked".
    assert found, "route walk found nothing — FastAPI's routing shape changed again"
    return found
