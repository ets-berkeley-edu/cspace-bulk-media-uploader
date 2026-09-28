"""ASGI entry point: uvicorn bmu.main:app"""
from .app import create_app

app = create_app()
