from fastapi import FastAPI
from fetch_endpoint import fetch_data

app = FastAPI()

@app.get("/")
async def root():
    return {"greeting": "Hello, World!", "message": "Welcome to FastAPI!"}

# Include the fetch endpoint
app.get("/fetch")(fetch_data)