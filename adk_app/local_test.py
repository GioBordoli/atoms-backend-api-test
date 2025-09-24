import asyncio
from adk_app.agent import app

async def main():
    # Create a session
    session = await app.async_create_session(user_id="u_local")

    print("-- Querying agent --")
    async for event in app.async_stream_query(
        user_id="u_local",
        session_id=session.id,
        message="What is the exchange rate from US dollars to SEK on 2025-04-03?",
    ):
        print(event)

if __name__ == "__main__":
    asyncio.run(main()) 