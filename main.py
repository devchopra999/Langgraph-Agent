"""Entrypoint: `python main.py` starts the FastAPI server hosting the Praxis Lens agent."""
import uvicorn

from praxis_agent.config import settings

if __name__ == "__main__":
    uvicorn.run("praxis_agent.api.server:app", host=settings.host, port=settings.port, reload=False)
