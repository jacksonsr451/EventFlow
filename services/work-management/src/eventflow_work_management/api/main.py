"""Uvicorn entry point; runtime configuration is validated at startup."""

from eventflow_work_management.api.app import create_app

app = create_app()
