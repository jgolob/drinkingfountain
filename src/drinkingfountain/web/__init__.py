"""Web interface for DrinkingFountain."""

from flask import Flask


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB

    from .app import register_routes

    register_routes(app)

    return app


def main() -> None:
    """Entry point for the drinkingfountain-web command."""
    app = create_app()
    app.run(debug=True, host="127.0.0.1", port=5000)


if __name__ == "__main__":
    main()
