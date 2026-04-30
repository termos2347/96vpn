import uvicorn
from config import settings

def main():
    print("Starting NeuroPrompt Premium web application...")
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )

if __name__ == "__main__":
    main()