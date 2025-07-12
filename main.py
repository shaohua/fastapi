from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fetch_endpoint import fetch_data, validate_client_key
import os
import logging

app = FastAPI()

# Set up logging
logger = logging.getLogger(__name__)

@app.get("/")
async def root():
    return {"greeting": "Hello, World!", "message": "Welcome to FastAPI!"}

@app.get("/download")
async def download_data_tar(
    key: str = Query(..., description="UUID key for client validation")
):
    """
    Download endpoint for data.tar file.

    Parameters:
    - key: UUID string to validate the client

    Returns:
    - File download of data.tar
    """

    # Validate client key
    if not validate_client_key(key):
        logger.warning(f"Unauthorized download attempt with key: {key}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or unauthorized client key"
        )

    # Check if data.tar file exists
    file_path = "./data.tar"
    if not os.path.exists(file_path):
        logger.error(f"data.tar file not found at {file_path}")
        raise HTTPException(
            status_code=404,
            detail="data.tar file not found"
        )

    logger.info(f"Serving data.tar download to authenticated client")

    # Return file for download
    return FileResponse(
        path=file_path,
        filename="data.tar",
        media_type="application/x-tar"
    )

# Include the fetch endpoint
app.get("/fetch")(fetch_data)