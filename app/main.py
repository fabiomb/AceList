import uvicorn
from fastapi import FastAPI

HOST = "127.0.0.1"
PORT = 8000

app = FastAPI(title="AceList")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    # Bound to loopback only: the app is for local use.
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    run()
