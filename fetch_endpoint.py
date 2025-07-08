from fastapi import FastAPI, HTTPException, Query
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Optional
import uuid
import logging
from config import VALID_CLIENT_KEYS, DATA_DIRECTORY
from marketplace_api import get_all_ai_extensions

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
VALID_KEYS = VALID_CLIENT_KEYS
DATA_DIR = Path(DATA_DIRECTORY)


def validate_client_key(key: str) -> bool:
    """Validate if the provided key is from a known client."""
    try:
        # Validate UUID format
        uuid.UUID(key)
        # Check if key is in our valid keys set
        is_valid = key in VALID_KEYS
        logger.info(f"Client key validation: {'valid' if is_valid else 'invalid'}")
        return is_valid
    except ValueError as e:
        logger.warning(f"Invalid UUID format provided: {key}")
        return False


def ensure_data_directory() -> None:
    """Ensure the data directory exists."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Data directory ensured: {DATA_DIR}")
    except PermissionError as e:
        logger.error(f"Permission denied creating directory {DATA_DIR}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error creating directory {DATA_DIR}: {e}")
        raise


def create_last_fetched_file() -> dict:
    """Create the last_fetched.json file with current timestamp."""
    now = datetime.now()
    timestamp_data = {
        "timestamp": now.isoformat(),
        "unix_timestamp": int(now.timestamp()),
        "human_readable": now.strftime("%Y-%m-%d %H:%M:%S UTC")
    }

    file_path = DATA_DIR / "last_fetched.json"
    try:
        with open(file_path, 'w') as f:
            json.dump(timestamp_data, f, indent=2)
        logger.info(f"Created last_fetched.json at {file_path}")
        return timestamp_data
    except Exception as e:
        logger.error(f"Error creating last_fetched.json: {e}")
        raise


def create_dummy_data_file() -> dict:
    """Create a data.json file with VS Code marketplace AI extensions."""
    try:
        # Fetch AI extensions from VS Code marketplace
        logger.info("Fetching AI extensions from VS Code marketplace...")
        extensions = get_all_ai_extensions()

        # Create data structure compatible with existing format
        marketplace_data = {
            "status": "success",
            "data": {
                "message": f"VS Code AI extensions data - {len(extensions)} extensions found",
                "items": extensions,
                "count": len(extensions)
            },
            "metadata": {
                "version": "1.0",
                "source": "vscode_marketplace",
                "api_endpoint": "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery",
                "category": "AI"
            },
            "created_at": datetime.now().isoformat()
        }

        file_path = DATA_DIR / "data.json"
        try:
            with open(file_path, 'w') as f:
                json.dump(marketplace_data, f, indent=2)
            logger.info(f"Created data.json with {len(extensions)} AI extensions at {file_path}")
            return marketplace_data
        except Exception as e:
            logger.error(f"Error writing data.json: {e}")
            raise

    except Exception as e:
        logger.error(f"Error fetching marketplace data: {e}")
        # Fallback to dummy data if marketplace API fails
        logger.info("Falling back to dummy data due to marketplace API error")
        fallback_data = {
            "status": "success",
            "data": {
                "message": "Fallback dummy data (marketplace API failed)",
                "items": [
                    {"id": 1, "name": "Sample Item 1", "value": "example"},
                    {"id": 2, "name": "Sample Item 2", "value": "demo"}
                ],
                "count": 2,
                "error": str(e)
            },
            "metadata": {
                "version": "1.0",
                "source": "fetch_endpoint_fallback"
            },
            "created_at": datetime.now().isoformat()
        }

        file_path = DATA_DIR / "data.json"
        try:
            with open(file_path, 'w') as f:
                json.dump(fallback_data, f, indent=2)
            logger.info(f"Created fallback data.json at {file_path}")
            return fallback_data
        except Exception as write_error:
            logger.error(f"Error creating fallback data.json: {write_error}")
            raise


async def fetch_data(
    key: str = Query(..., description="UUID key for client validation"),
    dryrun: int = Query(0, description="Dry run mode: 1 for dry run, 0 for actual execution")
):
    """
    Fetch endpoint that creates data files based on client validation.
    
    Parameters:
    - key: UUID string to validate the client
    - dryrun: 1 for dry run (no files created), 0 for actual execution
    
    Returns:
    - Success response with file creation status
    """
    
    # Validate client key
    if not validate_client_key(key):
        raise HTTPException(
            status_code=401, 
            detail="Invalid or unauthorized client key"
        )
    
    # Prepare response data
    response_data = {
        "status": "success",
        "dry_run": bool(dryrun),
        "timestamp": datetime.now().isoformat(),
        "files_created": []
    }
    
    if dryrun == 1:
        # Dry run mode - don't create files, just return what would be done
        response_data["message"] = "Dry run mode - no files were created"
        response_data["would_create"] = [
            str(DATA_DIR / "last_fetched.json"),
            str(DATA_DIR / "data.json")
        ]
    else:
        # Actual execution - create the files
        try:
            ensure_data_directory()
            
            # Create last_fetched.json
            timestamp_data = create_last_fetched_file()
            response_data["files_created"].append(str(DATA_DIR / "last_fetched.json"))
            response_data["last_fetched_data"] = timestamp_data
            
            # Create data.json
            dummy_data = create_dummy_data_file()
            response_data["files_created"].append(str(DATA_DIR / "data.json"))
            response_data["data_file_preview"] = dummy_data
            
            response_data["message"] = "Files created successfully"
            
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error creating files: {str(e)}"
            )
    
    return response_data
