import asyncio

async def main():
    server_ip = input("Enter Server IP (press Enter for 127.0.0.1): ").strip() or "127.0.0.1"
    port = 8888

    print(f"Connecting to server at {server_ip}:{port}...")
    try:
        reader, writer = await asyncio.open_connection(server_ip, port)
        print(" Connected successfully!\n")
    except Exception as e:
        print(f" Connection failed: {e}")
        return

    loop = asyncio.get_running_loop()

    while True:
        # Prompt user for input without blocking asyncio event loop
        user_msg = await loop.run_in_executor(None, input, "Type message (or 'exit' to quit): ")
        user_msg = user_msg.strip()

        if not user_msg:
            continue
        if user_msg.lower() == "exit":
            print("Disconnecting...")
            break

        # Send message with newline delimiter
        writer.write(f"{user_msg}\n".encode())
        await writer.drain()

        # Await response from server
        response = await reader.readline()
        if not response:
            print("Server closed connection.")
            break

        print(f"Server Response -> {response.decode().strip()}\n")

    writer.close()
    await writer.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nClient closed.")