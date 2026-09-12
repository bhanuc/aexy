"""The compliance endpoints must take the actor from the token, not the query.

Every mutating `/compliance/*` endpoint records who performed the action —
the assignment's creator, the developer who acknowledged or completed a
training, the person who waived or verified a certification. Those identities
used to arrive as a plain `developer_id` / `actor_id` query parameter, which
the caller controls. Any authenticated member with compliance access could
therefore attribute an action to someone else: mark another developer's
mandatory training as completed, and have the audit log name that developer as
the one who did it. In a module whose entire value is a trustworthy training
record, that defeats the purpose.

The fix sources the actor from `get_current_developer_id` instead. This test
pins it: none of the compliance mutation endpoints may expose the actor as a
query parameter again. `developer_id` survives only where it names *whose data
to read* (a filter or a report subject), never *who is acting*.
"""

from aexy.main import app
from tests.support.routes import mounted_routes

# GET endpoints where a developer_id/actor_id query param is a subject/filter,
# not the actor — legitimately client-supplied.
_READ_SUBJECT_ROUTES = {
    "/api/v1/compliance/assignments",
    "/api/v1/compliance/developer-certifications",
    "/api/v1/compliance/reports/developer/{developer_id}",
    "/api/v1/compliance/audit-logs",
}

_ACTOR_PARAMS = {"developer_id", "actor_id"}


def _query_param_names(route) -> set[str]:
    names = set()
    for param in getattr(route.route, "dependant", None).query_params or []:
        names.add(param.name)
    return names


def test_no_compliance_mutation_takes_the_actor_from_the_query_string():
    offenders = []
    for route in mounted_routes(app):
        if not route.path.startswith("/api/v1/compliance/"):
            continue
        if route.is_websocket:
            continue
        # Read subjects/filters are allowed to carry a developer_id.
        is_write = bool(route.methods & {"POST", "PATCH", "PUT", "DELETE"})
        if not is_write and route.path in _READ_SUBJECT_ROUTES:
            continue
        leaked = _query_param_names(route) & _ACTOR_PARAMS
        if leaked:
            offenders.append((sorted(route.methods), route.path, sorted(leaked)))
    assert not offenders, (
        "these compliance endpoints still take the acting identity from the "
        f"query string, so the actor can be spoofed: {offenders}"
    )
