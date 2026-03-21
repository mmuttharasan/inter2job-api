import os

from flask import Flask
from flask_cors import CORS
from .routes import register_routes


def create_app(config=None):
    app = Flask(__name__)

    if config:
        app.config.update(config)

    # Local dev origins + production frontend URL from env
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
    ]
    frontend_url = os.environ.get("FRONTEND_URL")
    if frontend_url:
        allowed_origins.append(frontend_url.rstrip("/"))

    CORS(
        app,
        origins=allowed_origins,
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization", "X-Company-ID"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    register_routes(app)

    return app
