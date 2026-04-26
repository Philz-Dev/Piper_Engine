import asyncio

# This is a simple in-memory store
storage = {}

async def handle_client(reader, writer):
    while True:
        data = await reader.read(100) # Read raw bytes from the network
        if not data: break
        
        command = data.decode().strip().split()
        # Basic logic: SET key value
        if command[0] == "SET":
            storage[command[1]] = command[2]
            writer.write(b"OK\n")
        elif command[0] == "GET":
            val = storage.get(command[1], "NIL")
            writer.write(f"{val}\n".encode())
            
        await writer.drain()

async def main():
    # Listening on Port 6379 just like the real Redis
    server = await asyncio.start_server(handle_client, '0.0.0.0', 6379)
    async with server:
        await server.serve_forever()

asyncio.run(main())