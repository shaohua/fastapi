from fastapi import FastAPI, HTTPException, Query
from datetime import datetime, timezone, timedelta
import json
import os
import glob
from pathlib import Path
from typing import Optional, List
import uuid
import logging
from config import VALID_CLIENT_KEYS, DATA_DIRECTORY
from marketplace_api import get_all_ai_extensions
from app.database import fetch_one

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
VALID_KEYS = VALID_CLIENT_KEYS
DATA_DIR = Path(DATA_DIRECTORY)

# PST timezone (UTC-8)
PST = timezone(timedelta(hours=-8))


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
    now = datetime.now(PST)
    timestamp_data = {
        "timestamp": now.isoformat(),
        "unix_timestamp": int(now.timestamp()),
        "human_readable": now.strftime("%Y-%m-%d %H:%M:%S PST")
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
            "created_at": datetime.now(PST).isoformat()
        }

        timestamp_filename = datetime.now(PST).strftime("%Y-%m-%d-%H-%M-%S.json")
        file_path = DATA_DIR / timestamp_filename
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
            "created_at": datetime.now(PST).isoformat()
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
        "timestamp": datetime.now(PST).isoformat(),
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
            # Check if last_fetched.json exists and read its timestamp
            last_fetched_path = DATA_DIR / "last_fetched.json"
            if last_fetched_path.exists():
                try:
                    with open(last_fetched_path, 'r') as f:
                        last_fetched = json.load(f)
                        time_diff = datetime.now(PST) - datetime.fromtimestamp(last_fetched['unix_timestamp'], tz=PST)

                        # If less than 6 hours have passed
                        if time_diff.total_seconds() < 21600:  # 6 hours = 21600 seconds
                            logger.info("Less than 6 hours since last update, skipping data.json creation")
                            response_data["message"] = "Using existing data (less than 6 hours old)"
                            response_data["last_fetched_data"] = last_fetched
                            return response_data
                except Exception as e:
                    logger.warning(f"Error reading last_fetched.json: {e}, will proceed with update")

            # Create files atomically - if one fails, we don't want partial state
            timestamp_data = None
            dummy_data = None

            try:
                # Create last_fetched.json
                timestamp_data = create_last_fetched_file()
                response_data["files_created"].append(str(DATA_DIR / "last_fetched.json"))
                response_data["last_fetched_data"] = timestamp_data

                # Create data.json
                dummy_data = create_dummy_data_file()
                response_data["files_created"].append(str(DATA_DIR / "data.json"))

                response_data["message"] = "Files created successfully"

            except Exception as file_error:
                # If data.json creation fails after last_fetched.json was created,
                # we should clean up the last_fetched.json to maintain consistency
                if timestamp_data is not None and dummy_data is None:
                    try:
                        last_fetched_path.unlink(missing_ok=True)
                        logger.info("Cleaned up last_fetched.json due to data.json creation failure")
                    except Exception as cleanup_error:
                        logger.error(f"Failed to cleanup last_fetched.json: {cleanup_error}")
                raise file_error
            
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error creating files: {str(e)}"
            )

    return response_data


async def get_latest_db_timestamp():
    """Get the latest captured_at timestamp from the database."""
    try:
        query = "SELECT MAX(captured_at) as latest_captured_at FROM extension_stats"
        result = await fetch_one(query)
        return result['latest_captured_at'] if result and result['latest_captured_at'] else None
    except Exception as e:
        logger.error(f"Error querying database for latest timestamp: {e}")
        raise


def parse_json_file_timestamp(file_path: Path) -> datetime:
    """Parse the created_at timestamp from a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        created_at_str = data.get('created_at')
        if not created_at_str:
            # Fallback: try to parse from filename if no created_at field
            # Expected format: YYYY-MM-DD-HH-MM-SS.json
            filename = file_path.stem
            try:
                return datetime.strptime(filename, "%Y-%m-%d-%H-%M-%S").replace(tzinfo=PST)
            except ValueError:
                logger.warning(f"Could not parse timestamp from filename: {filename}")
                return datetime.fromtimestamp(file_path.stat().st_mtime, tz=PST)

        # Parse ISO format timestamp
        dt = datetime.fromisoformat(created_at_str)
        return dt

    except Exception as e:
        logger.warning(f"Error parsing timestamp from {file_path}: {e}")
        # Fallback to file modification time
        return datetime.fromtimestamp(file_path.stat().st_mtime, tz=PST)


def get_unprocessed_json_files(latest_db_timestamp: datetime = None) -> List[str]:
    """
    Find JSON files in data directory that haven't been processed.

    Args:
        latest_db_timestamp: Latest captured_at from database

    Returns:
        List of unprocessed filenames
    """
    try:
        # Get all JSON files in data directory
        json_files = sorted(glob.glob(str(DATA_DIR / "*.json")))

        # Get processed files directory
        processed_dir = Path("processed_json")
        processed_files = set()
        if processed_dir.exists():
            processed_files = {Path(f).name for f in glob.glob(str(processed_dir / "*.json"))}

        unprocessed_files = []

        for json_file in json_files:
            file_path = Path(json_file)
            filename = file_path.name

            # Skip special files like last_fetched.json
            if filename in ['last_fetched.json']:
                continue

            # Check if file has been processed (moved to processed_json/)
            if filename in processed_files:
                continue

            # If we have a latest DB timestamp, check if file is newer
            if latest_db_timestamp:
                try:
                    file_timestamp = parse_json_file_timestamp(file_path)
                    # Only include files newer than the latest DB record
                    if file_timestamp <= latest_db_timestamp:
                        continue
                except Exception as e:
                    logger.warning(f"Could not parse timestamp for {filename}: {e}")
                    # Include file if we can't parse timestamp (safer to include)

            unprocessed_files.append(filename)

        return unprocessed_files

    except Exception as e:
        logger.error(f"Error scanning for unprocessed files: {e}")
        raise


async def sync_status_check(
    key: str = Query(..., description="UUID key for client validation"),
    dryrun: int = Query(0, description="Dry run mode: 1 for dry run, 0 for actual execution")
):
    """
    Sync status endpoint that compares database records with JSON files.

    Returns information about unprocessed JSON files in the data directory.

    Parameters:
    - key: UUID string to validate the client
    - dryrun: 1 for dry run (no side effects), 0 for actual execution

    Returns:
    - Status response with unprocessed file information
    """

    # Validate client key
    if not validate_client_key(key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or unauthorized client key"
        )

    try:
        # Get latest timestamp from database
        latest_db_timestamp = await get_latest_db_timestamp()

        # Get all JSON files in data directory
        all_json_files = glob.glob(str(DATA_DIR / "*.json"))
        # Filter out special files
        data_json_files = [f for f in all_json_files if not Path(f).name.startswith('last_fetched')]

        # Find unprocessed files
        unprocessed_files = get_unprocessed_json_files(latest_db_timestamp)

        # Prepare response
        response_data = {
            "status": "success",
            "timestamp": datetime.now(PST).isoformat(),
            "latest_db_record": latest_db_timestamp.isoformat() if latest_db_timestamp else None,
            "total_json_files": len(data_json_files),
            "unprocessed_files": unprocessed_files,
            "unprocessed_count": len(unprocessed_files),
            "dry_run": bool(dryrun)
        }

        if latest_db_timestamp is None:
            response_data["warning"] = "No records found in database - all files considered unprocessed"

        logger.info(f"Sync status check completed: {len(unprocessed_files)} unprocessed files found")
        return response_data

    except Exception as e:
        logger.error(f"Error in sync status check: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error checking sync status: {str(e)}"
        )
