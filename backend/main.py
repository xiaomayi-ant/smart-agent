"""
Main entry point for the financial expert backend
"""
import uvicorn
from src.core.config import settings
from src.api.server import app


def main():
    """Main function to start the server"""
    print("🚀 Starting Financial Expert Python Backend...")
    print(f"📍 Server will run on {settings.host}:{settings.port}")
    print(f"🔧 Debug mode: {settings.debug}")
    
    uvicorn.run(
        "src.api.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )


if __name__ == "__main__":
    main() 