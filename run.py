from app import create_app

app = create_app()

if __name__ == "__main__":
    from waitress import serve
    import socket

    host = "0.0.0.0"
    port = 4300

    local_ip = socket.gethostbyname(socket.gethostname())

    print("=" * 52)
    print("  AC EVO Server Panel")
    print("=" * 52)
    print(f"  Local   : http://127.0.0.1:{port}")
    print(f"  Réseau  : http://{local_ip}:{port}")
    print(f"  Threads : 8")
    print("=" * 52)
    print("  CTRL+C pour arrêter")
    print()

    serve(app, host=host, port=port, threads=8)
