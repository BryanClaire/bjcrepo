import uvicorn

from comic_inventory.api import app


if __name__ == "__main__":
    uvicorn.run("comic_inventory.api:app", host="127.0.0.1", port=8000, reload=True)
