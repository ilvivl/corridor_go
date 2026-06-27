"""Точка входа dev-сервера «Коридор» (этап 5): python app.py.

Запуск через Flask-SocketIO (WebSocket-транспорт ходов). Прод — gunicorn (этап 7).
"""
from server.app import create_app
from server.realtime import socketio

app = create_app()

if __name__ == "__main__":
    # allow_unsafe_werkzeug — dev-сервер Werkzeug в режиме threading; прод — этап 7.
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
