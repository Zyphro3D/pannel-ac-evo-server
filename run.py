from app import create_app

app = create_app()

if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=4300, threads=8)
