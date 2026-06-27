"""Точка входа dev-сервера «Коридор» (этап 3): python app.py.

На этапе 5 запуск переедет на Flask-SocketIO. Прод — gunicorn (этап 7).
"""
from server.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
