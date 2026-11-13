"""Actor entry point: `python -m domovoy`.

The extractor is opened here, inside the Actor run, because its cache is an Apify store. It is closed after the
run, also when the run fails.
"""

import asyncio
import os

from apify import Actor

from domovoy.main import run
from domovoy.pipeline import open_extractor


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        extractor = await open_extractor(actor_input, os.environ, Actor.log)
        try:
            await run(actor_input, Actor, Actor.log, extractor=extractor)
        finally:
            if extractor is not None:
                await extractor.aclose()


if __name__ == "__main__":
    asyncio.run(main())
