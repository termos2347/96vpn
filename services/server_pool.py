# Заглушка для пула серверов
class ServerPool:
    async def get_least_loaded_server(self):
        return {"id": 1, "host": "server1.example.com", "load": 0}