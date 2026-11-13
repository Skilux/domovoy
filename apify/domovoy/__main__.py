"""Actor entry point: `python -m domovoy`."""

import asyncio

from apify import Actor

from domovoy.main import run


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        await run(actor_input, Actor, Actor.log)


if __name__ == "__main__":
    asyncio.run(main())
