"""HTTP executor package — importing it registers all built-in mappers."""

from app.services.http_executors import (  # noqa: F401  (self-register mappers)
    graphql_countries,
    hn_firebase,
    openlibrary,
    wttr,
)
from app.services.http_executors.base import (  # noqa: F401
    ALLOWED_HOSTS,
    MapperFn,
    MapperNotFoundError,
    SSRFBlockedError,
    assert_host_allowed,
    execute_http,
    get_client,
    get_json,
    get_mapper,
    register_mapper,
)
