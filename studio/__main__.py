"""Запуск: python -m studio [--no-browser]"""
import json
import socket
import sys
import threading
import urllib.request
import webbrowser

import uvicorn

from . import config


def already_running(url):
    """True — на порту уже наша студия; False — порт свободен; None — порт занят чем-то другим."""
    with socket.socket() as s:
        s.settimeout(1)
        if s.connect_ex((config.STUDIO_HOST, config.STUDIO_PORT)) != 0:
            return False
    try:
        with urllib.request.urlopen(url + "/api/status", timeout=3) as r:
            return "engine" in json.load(r)
    except (OSError, ValueError):
        return None


def main():
    url = f"http://{config.STUDIO_HOST}:{config.STUDIO_PORT}"
    open_browser = "--no-browser" not in sys.argv
    state = already_running(url)
    if state:
        print(f"Студия уже запущена: {url}")
        if open_browser:
            webbrowser.open(url)
        return
    if state is None:
        print(f"Порт {config.STUDIO_PORT} занят другой программой. Задайте другой порт: set STUDIO_PORT=8801")
        sys.exit(1)
    print(f"Local AI Studio: {url}")
    if open_browser:
        threading.Timer(2.0, webbrowser.open, (url,)).start()
    uvicorn.run("studio.app:app", host=config.STUDIO_HOST, port=config.STUDIO_PORT, log_level="warning")


if __name__ == "__main__":
    main()
