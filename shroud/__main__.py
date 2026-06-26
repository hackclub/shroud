import dotenv
import importlib
import threading
import uvicorn
from pathlib import Path
from shroud.slack.slack import start_app
from shroud import settings

dotenv.load_dotenv()

def import_modules_from_directory(directory):
    for path in directory.glob("*.py"):
        if path.name != "__init__.py":
            module_name = f"shroud.slack.handlers.{path.stem}"
            importlib.import_module(module_name)

def main():
    handlers_directory = Path(__file__).parent / 'slack' / 'handlers'
    import_modules_from_directory(handlers_directory)

    if settings.get("api_secret"):
        from shroud.api.app import api_app
        thread = threading.Thread(
            target=uvicorn.run,
            kwargs={"app": api_app, "host": "0.0.0.0", "port": settings.api_port},
            daemon=True,
        )
        thread.start()
        print(f"API server starting on port {settings.api_port}")

    start_app()

if __name__ == "__main__":
    main()