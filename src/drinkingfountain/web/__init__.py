"""Web interface for DrinkingFountain."""

import socket

from flask import Flask

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
PORT_SEARCH_LIMIT = 20


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB

    from .app import register_routes

    register_routes(app)

    return app


def find_available_port(
    host: str = DEFAULT_HOST,
    preferred_port: int = DEFAULT_PORT,
    search_limit: int = PORT_SEARCH_LIMIT,
) -> int:
    """Find a local port for the development server."""
    for port in range(preferred_port, preferred_port + search_limit):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"No available local port found from {preferred_port} "
        f"to {preferred_port + search_limit - 1}."
    )


def main() -> None:
    """Entry point for the drinkingfountain-web command."""
    port = find_available_port()
    if port != DEFAULT_PORT:
        print(
            f"Port {DEFAULT_PORT} is already in use; "
            f"starting DrinkingFountain on http://{DEFAULT_HOST}:{port}"
        )
    app = create_app()
    app.run(debug=True, host=DEFAULT_HOST, port=port)


if __name__ == "__main__":
    main()
