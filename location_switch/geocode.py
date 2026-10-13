import asyncio
import os
import time
from collections import OrderedDict

import httpx


class Geocoder:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.last_request = 0
        self.cache = OrderedDict()
        self.url = os.getenv("PHOTON_URL", "https://photon.komoot.io/api/")

    async def search(self, query):
        key = query.strip().casefold()
        async with self.lock:
            if key in self.cache:
                return self.cache[key]
            await asyncio.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "LocationSwitch/0.1 (local iPhone developer utility)"}) as client:
                response = await client.get(self.url, params={"q": query, "limit": 5})
                response.raise_for_status()
                features = response.json()["features"]
            results = []
            for item in features:
                lon, lat = item["geometry"]["coordinates"][:2]
                props = item["properties"]
                street = " ".join(str(props[k]) for k in ("housenumber", "street") if props.get(k))
                parts = [props.get("name"), street, props.get("city"), props.get("state"), props.get("country")]
                label = ", ".join(dict.fromkeys(str(p) for p in parts if p)) or f"{lat}, {lon}"
                results.append({"label": label, "latitude": lat, "longitude": lon})
            self.cache[key] = results
            if len(self.cache) > 100:
                self.cache.popitem(last=False)
            return results
