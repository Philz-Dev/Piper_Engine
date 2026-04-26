from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import docker
import uvicorn
import os

app = FastAPI(title="Piper Control API")
client = docker.from_env()

# Agency-grade security: Only allow your UI to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with your UI URL
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/workers")
async def get_workers():
    """Returns a high-level status of all client engines."""
    containers = client.containers.list(all=True, filters={"label": "com.piper.engine=v1"})
    return [
        {
            "id": c.short_id,
            "name": c.name,
            "status": c.status,
            "cpu": c.stats(stream=False)['cpu_stats']['cpu_usage']['total_usage'],
            "memory": c.stats(stream=False)['memory_stats']['usage']
        } for c in containers
    ]

@app.post("/workers/{client_name}/start")
async def start_worker(client_name: str):
    try:
        # This triggers the same logic as 'piper start'
        container = client.containers.get(f"{client_name}_engine")
        container.start()
        return {"message": f"{client_name} started successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
def start_server(port: int=3000):
    print(f"🚀 Booting server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    start_server()