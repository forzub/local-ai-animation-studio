"""Запуск: python -m studio [--no-browser]"""
import sys
import threading
import webbrowser

import uvicorn

from . import config


def main():
    url = f"http://{config.STUDIO_HOST}:{config.STUDIO_PORT}"
    print(f"Local AI Studio: {url}")
    if "--no-browser" not in sys.argv:
        threading.Timer(2.0, webbrowser.open, (url,)).start()
    uvicorn.run("studio.app:app", host=config.STUDIO_HOST, port=config.STUDIO_PORT, log_level="warning")


if __name__ == "__main__":
    main()
