import asyncio

async def send_to_vault(key, value):
    # Use the Docker Alias 'piper-vault'
    reader, writer = await asyncio.open_connection('piper-vault', 6379)

    print(f"Sending: SET {key} {value}")
    writer.write(f"SET {key} {value}\n".encode())
    await writer.drain()

    response = await reader.read(100)
    print(f"Received: {response.decode().strip()}")

    writer.close()
    await writer.wait_closed()

asyncio.run(send_to_vault("api_token", "12345"))