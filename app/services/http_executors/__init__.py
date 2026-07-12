"""HTTP executor package — importing it registers all built-in mappers."""

from app.services.http_executors import hn_firebase  # noqa: F401  (self-registers mapper)
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
