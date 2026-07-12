"""wttr_v0 mapper — wttr.in JSON weather API (format=j1)."""

import re
from urllib.parse import quote

from app.services.http_executors.base import get_json, register_mapper

_CITY_RE = re.compile(r"^[A-Za-z .-]{1,40}$")


@register_mapper("wttr_v0")
async def run(contract_body: dict, input: dict) -> dict:
    city = input.get("city", "London")
    if not isinstance(city, str) or not _CITY_RE.match(city):
        raise ValueError(f"invalid city {city!r}; expected ^[A-Za-z .-]{{1,40}}$")

    data = await get_json(f"https://wttr.in/{quote(city)}?format=j1")
    if not isinstance(data, dict):
        raise ValueError("wttr.in did not return a JSON object")
    cc = data["current_condition"][0]
    return {
        "temp_C": cc["temp_C"],
        "humidity": cc["humidity"],
        "weather_desc": cc["weatherDesc"][0]["value"],
    }
