"""HTTP executor plumbing: SSRF allowlist, shared httpx client, mapper registry."""

from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

import httpx

ALLOWED_HOSTS: set[str] = {  # SSRF allowlist
    "hacker-news.firebaseio.com",
    "wttr.in",
    "openlibrary.org",
    "countries.trevorblades.com",
}


class SSRFBlockedError(Exception): ...


class MapperNotFoundError(Exception): ...


def assert_host_allowed(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise SSRFBlockedError(f"blocked non-allowlisted URL: {url}")


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def get_json(url: str) -> object:
    assert_host_allowed(url)
    resp = await get_client().get(url)
    resp.raise_for_status()
    return resp.json()


async def post_json(url: str, json_body: dict) -> object:
    assert_host_allowed(url)
    resp = await get_client().post(url, json=json_body)
    resp.raise_for_status()
    return resp.json()


MapperFn = Callable[[dict, dict], Awaitable[dict]]  # (contract_body, input) -> output data

_MAPPERS: dict[str, MapperFn] = {}


def register_mapper(name: str) -> Callable[[MapperFn], MapperFn]:
    def decorator(fn: MapperFn) -> MapperFn:
        _MAPPERS[name] = fn
        return fn

    return decorator


def get_mapper(name: str) -> MapperFn:
    try:
        return _MAPPERS[name]
    except KeyError:
        raise MapperNotFoundError(f"no mapper registered under {name!r}") from None


async def execute_http(contract_body: dict, input: dict) -> dict:
    http_cfg = contract_body.get("http") or {}
    if not http_cfg.get("enabled"):
        raise ValueError("http path not enabled for this contract")
    mapper_name = http_cfg.get("mapper")
    if not mapper_name:
        raise MapperNotFoundError("contract http block declares no mapper")
    mapper = get_mapper(mapper_name)
    return await mapper(contract_body, input)
