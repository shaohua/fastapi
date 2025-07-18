"""
VS Code Extension Stats - FastAPI Application

Simple web app to display VS Code extension statistics with charts.
"""

import json
import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from app.database import init_db, close_db, fetch_all, fetch_one, check_timestamp_exists, execute_query
from app.fetch_endpoint import fetch_data, validate_client_key, sync_status_check
from config import DATA_DIRECTORY

# Load environment variables at application startup
load_dotenv()

# Pacific timezone (handles PST/PDT automatically)
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

# Pydantic models for request validation
class IngestRequest(BaseModel):
    filename: str
    key: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown."""
    # Startup
    await init_db()
    yield
    # Shutdown
    await close_db()

# Set up logging
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="VS Code Extension Stats",
    description="Track VS Code extension popularity over time with data API",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """
    Homepage showing top extensions by recent growth.
    """
    # Query for top 20 extensions by install count growth in last 7 days
    query = """
    WITH recent_stats AS (
        SELECT DISTINCT ON (extension_id)
            extension_id, name, publisher, install_count, rating, captured_at
        FROM extension_stats 
        WHERE captured_at >= NOW() - INTERVAL '7 days'
        ORDER BY extension_id, captured_at DESC
    ),
    older_stats AS (
        SELECT DISTINCT ON (extension_id)
            extension_id, install_count as old_install_count
        FROM extension_stats 
        WHERE captured_at >= NOW() - INTERVAL '14 days' 
          AND captured_at < NOW() - INTERVAL '7 days'
        ORDER BY extension_id, captured_at DESC
    )
    SELECT 
        r.extension_id,
        r.name,
        r.publisher,
        r.install_count,
        r.rating,
        COALESCE(r.install_count - o.old_install_count, 0) as growth_7d
    FROM recent_stats r
    LEFT JOIN older_stats o ON r.extension_id = o.extension_id
    WHERE r.install_count > 1000  -- Filter out very small extensions
    ORDER BY growth_7d DESC, r.install_count DESC
    LIMIT 20;
    """
    
    try:
        extensions = await fetch_all(query)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "extensions": extensions,
            "title": "VS Code Extension Stats - Top Growing Extensions"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/extension/{extension_id}", response_class=HTMLResponse)
async def extension_detail(request: Request, extension_id: str):
    """
    Extension detail page with 30-day chart data.
    """
    # Get extension metadata
    ext_query = """
    SELECT DISTINCT ON (extension_id)
        extension_id, name, publisher, description, install_count, rating, rating_count
    FROM extension_stats 
    WHERE extension_id = %s
    ORDER BY extension_id, captured_at DESC;
    """
    
    extension = await fetch_one(ext_query, extension_id)
    if not extension:
        raise HTTPException(status_code=404, detail="Extension not found")
    
    # Get 30-day time series data
    series_query = """
    SELECT
        DATE(captured_at AT TIME ZONE 'America/Los_Angeles') as day,
        MAX(install_count) as installs,
        MAX(rating) as rating,
        MAX(rating_count) as rating_count,
        MAX(version) as version
    FROM extension_stats
    WHERE extension_id = %s
      AND captured_at >= NOW() - INTERVAL '30 days'
    GROUP BY DATE(captured_at AT TIME ZONE 'America/Los_Angeles')
    ORDER BY day;
    """
    
    try:
        series_data = await fetch_all(series_query, extension_id)
        
        # Convert to JSON for Chart.js
        chart_data = {
            "labels": [row["day"].strftime("%Y-%m-%d") for row in series_data],
            "installs": [row["installs"] for row in series_data],
            "rating": [float(row["rating"]) if row["rating"] else None for row in series_data],
            "rating_count": [row["rating_count"] for row in series_data],
            "versions": [row["version"] for row in series_data]
        }
        
        return templates.TemplateResponse("extension.html", {
            "request": request,
            "extension": extension,
            "chart_data": json.dumps(chart_data),
            "title": f"{extension['name']} - VS Code Extension Stats"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/healthz")
async def health_check():
    """Health check endpoint for deployment monitoring."""
    try:
        # Simple query to verify database connectivity
        result = await fetch_one("SELECT 1 as status")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unhealthy: {str(e)}")

@app.get("/api/extensions")
async def api_extensions():
    """
    Optional API endpoint returning JSON data.
    Useful for external integrations or mobile apps.
    """
    query = """
    SELECT DISTINCT ON (extension_id)
        extension_id, name, publisher, install_count, rating, captured_at
    FROM extension_stats 
    ORDER BY extension_id, captured_at DESC
    LIMIT 100;
    """
    
    try:
        extensions = await fetch_all(query)
        return {"extensions": extensions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/api/search")
async def search_extensions(
    q: str = Query(..., description="Search query for extension name, publisher, or extension_id"),
    limit: int = Query(10, description="Maximum number of results to return", ge=1, le=50)
):
    """
    Search extensions by name, publisher, or extension_id for autocomplete functionality.

    Parameters:
    - q: Search query string (minimum 2 characters)
    - limit: Maximum number of results (default 10, max 50)

    Returns:
    - JSON with extensions array containing extension_id, name, publisher, install_count
    """
    # Validate search query length
    if len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Search query must be at least 2 characters")

    # Sanitize search query for ILIKE
    search_term = f"%{q.strip()}%"

    # Search across name, publisher, and extension_id with latest stats
    query = """
    SELECT DISTINCT ON (extension_id)
        extension_id,
        name,
        publisher,
        install_count
    FROM extension_stats
    WHERE (
        name ILIKE %s
        OR publisher ILIKE %s
        OR extension_id ILIKE %s
    )
    AND install_count > 100  -- Filter out very small extensions
    ORDER BY extension_id, captured_at DESC, install_count DESC
    LIMIT %s;
    """

    try:
        extensions = await fetch_all(query, search_term, search_term, search_term, limit)
        return {"extensions": extensions}
    except Exception as e:
        logger.error(f"Error in search endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/api/compare")
async def compare_extensions(
    extension_ids: str = Query(..., description="Comma-separated list of extension IDs to compare (max 10)"),
    days: int = Query(30, description="Number of days of historical data to include", ge=7, le=90)
):
    """
    Compare multiple extensions with time-series data for install counts.

    Parameters:
    - extension_ids: Comma-separated extension IDs (e.g., "ms-python.python,github.copilot")
    - days: Number of days of historical data (default 30, min 7, max 90)

    Returns:
    - JSON with extension metadata and time-series data for comparison charts
    """
    # Parse and validate extension IDs
    ext_ids = [ext_id.strip() for ext_id in extension_ids.split(",") if ext_id.strip()]

    if not ext_ids:
        raise HTTPException(status_code=400, detail="At least one extension ID is required")

    if len(ext_ids) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 extensions can be compared at once")

    # Create placeholders for the query
    placeholders = ",".join(["%s"] * len(ext_ids))

    try:
        # Get time-series data for all extensions
        time_series_query = f"""
        SELECT
            extension_id,
            name,
            publisher,
            DATE(captured_at AT TIME ZONE 'America/Los_Angeles') as day,
            MAX(install_count) as install_count
        FROM extension_stats
        WHERE extension_id IN ({placeholders})
          AND captured_at >= NOW() - INTERVAL '{days} days'
        GROUP BY extension_id, name, publisher, DATE(captured_at AT TIME ZONE 'America/Los_Angeles')
        ORDER BY extension_id, day;
        """

        series_data = await fetch_all(time_series_query, *ext_ids)

        # Organize data by extension
        extensions_data = {}
        for row in series_data:
            ext_id = row["extension_id"]
            if ext_id not in extensions_data:
                extensions_data[ext_id] = {
                    "extension_id": ext_id,
                    "name": row["name"],
                    "publisher": row["publisher"],
                    "time_series": []
                }

            extensions_data[ext_id]["time_series"].append({
                "day": row["day"].strftime("%Y-%m-%d"),
                "install_count": row["install_count"]
            })

        # Check for missing extensions
        found_ids = set(extensions_data.keys())
        missing_ids = set(ext_ids) - found_ids
        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Extensions not found: {', '.join(missing_ids)}"
            )

        return {
            "extensions": list(extensions_data.values()),
            "days": days,
            "total_extensions": len(extensions_data)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in compare endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/api/download")
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

def parse_timestamp_from_json(data):
    """Extract timestamp from JSON data's created_at field, returning timezone-aware datetime in Pacific time."""
    try:
        created_at_str = data.get('created_at')
        if not created_at_str:
            raise ValueError("No created_at field found in JSON data")

        # Parse ISO format timestamp with timezone
        dt = datetime.fromisoformat(created_at_str)

        # Ensure we have a timezone-aware datetime in Pacific time (PST/PDT)
        if dt.tzinfo is not None:
            # Convert to Pacific time
            dt = dt.astimezone(PACIFIC_TZ)
        else:
            # If no timezone info, assume it's already in Pacific time
            dt = dt.replace(tzinfo=PACIFIC_TZ)

        return dt
    except (ValueError, TypeError) as e:
        raise ValueError(f"Could not parse timestamp from created_at field: {e}")

async def process_json_file_async(json_file_path):
    """Process a single JSON file and insert data into database (async version)."""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)

        # Extract timestamp from JSON created_at field
        captured_at = parse_timestamp_from_json(json_data)

        # Get the extensions list from the data.items field
        if isinstance(json_data, dict) and 'data' in json_data and 'items' in json_data['data']:
            extensions = json_data['data']['items']
        elif isinstance(json_data, list):
            extensions = json_data
        else:
            raise ValueError("JSON does not contain expected data structure")

        rows_inserted = 0
        batch_size = 500

        # Process in batches
        for i in range(0, len(extensions), batch_size):
            batch = extensions[i:i + batch_size]

            for ext in batch:
                try:
                    query = """
                        INSERT INTO extension_stats
                        (extension_id, name, publisher, description, version,
                         install_count, rating, rating_count, tags, categories, captured_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (extension_id, captured_at) DO NOTHING
                    """
                    params = (
                        ext.get('extension_id', ext.get('id', '')),
                        ext.get('name', ''),
                        ext.get('publisher', ''),
                        ext.get('description', ''),
                        ext.get('version', ''),
                        ext.get('install_count', ext.get('installs', 0)),
                        ext.get('rating', None),
                        ext.get('rating_count', 0),
                        ext.get('tags', []),
                        ext.get('categories', []),
                        captured_at
                    )

                    affected_rows = await execute_query(query, *params)
                    rows_inserted += affected_rows

                except Exception as e:
                    logger.warning(f"Error inserting extension {ext.get('id', 'unknown')}: {e}")
                    continue

        return rows_inserted, captured_at

    except json.JSONDecodeError as e:
        raise ValueError(f"Error parsing JSON file: {e}")
    except Exception as e:
        raise ValueError(f"Error processing file: {e}")

@app.get("/api/auto-sync")
async def auto_sync_files(
    key: str = Query(..., description="Client authentication key"),
    dryrun: int = Query(0, description="Dry run mode: 1 for dry run, 0 for actual processing")
):
    """
    Automatically sync unprocessed JSON files to database.

    Combines the functionality of sync-status and ingest endpoints:
    1. Finds unprocessed files in data directory
    2. Ingests each file to database
    3. Returns summary of processing results

    Parameters:
    - key: UUID string to validate the client
    - dryrun: If true, only report what would be done without ingesting

    Returns:
    - Summary of files found, processed, and any errors
    """

    # Validate client key
    if not validate_client_key(key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or unauthorized client key"
        )

    try:
        # Import the functions we need from fetch_endpoint
        from app.fetch_endpoint import get_latest_db_timestamp, get_unprocessed_json_files

        # Discovery phase: find unprocessed files
        latest_db_timestamp = await get_latest_db_timestamp()
        unprocessed_files = get_unprocessed_json_files(latest_db_timestamp)

        # Initialize response data
        response_data = {
            "status": "success",
            "timestamp": datetime.now(PACIFIC_TZ).isoformat(),
            "files_found": len(unprocessed_files),
            "files_processed": 0,
            "files_failed": 0,
            "total_records": 0,
            "dry_run": bool(dryrun),
            "latest_db_record": latest_db_timestamp.isoformat() if latest_db_timestamp else None
        }

        # If no files to process, return early
        if not unprocessed_files:
            response_data["message"] = "No unprocessed files found"
            return response_data

        # If dry run, just report what would be done
        if dryrun == 1:
            response_data["message"] = f"Would process {len(unprocessed_files)} files"
            response_data["files_to_process"] = unprocessed_files
            return response_data

        # Processing phase: ingest each file
        data_dir = Path(DATA_DIRECTORY)
        failed_files = []

        for filename in unprocessed_files:
            file_path = data_dir / filename

            if not file_path.exists():
                logger.warning(f"File not found: {filename}")
                failed_files.append({"filename": filename, "error": "File not found"})
                response_data["files_failed"] += 1
                continue

            try:
                # Load JSON to get timestamp
                with open(file_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)

                captured_at = parse_timestamp_from_json(json_data)

                # Check if data already exists in database
                if await check_timestamp_exists(captured_at):
                    logger.info(f"Data from {filename} already exists, skipping")
                    continue

                # Process the file
                records_inserted, parsed_timestamp = await process_json_file_async(file_path)

                response_data["files_processed"] += 1
                response_data["total_records"] += records_inserted

                logger.info(f"Successfully processed {filename}: {records_inserted} records")

            except Exception as e:
                logger.error(f"Error processing file {filename}: {e}")
                failed_files.append({"filename": filename, "error": str(e)})
                response_data["files_failed"] += 1
                continue

        # Update status based on results
        if response_data["files_failed"] > 0:
            if response_data["files_processed"] > 0:
                response_data["status"] = "partial"
                response_data["message"] = f"Processed {response_data['files_processed']} files, {response_data['files_failed']} failed"
            else:
                response_data["status"] = "error"
                response_data["message"] = f"All {response_data['files_failed']} files failed to process"
        else:
            response_data["message"] = f"Successfully processed {response_data['files_processed']} files"

        # Add failed files details if any
        if failed_files:
            response_data["failed_files"] = failed_files

        return response_data

    except Exception as e:
        logger.error(f"Error in auto-sync: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/api/ingest")
async def ingest_json_file(request: IngestRequest):
    """
    Ingest a specific JSON file by filename with duplicate checking.

    Parameters:
    - filename: JSON filename in format YYYY-MM-DD-HH-MM-SS.json
    - key: UUID string to validate the client

    Returns:
    - Success response with ingestion details
    """

    # Validate client key
    if not validate_client_key(request.key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or unauthorized client key"
        )

    # Validate filename format
    if not request.filename.endswith('.json'):
        raise HTTPException(
            status_code=400,
            detail="Filename must end with .json"
        )

    # Check if file exists in data directory
    data_dir = Path(DATA_DIRECTORY)
    file_path = data_dir / request.filename

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File {request.filename} not found in data directory"
        )

    try:
        # Load JSON to get timestamp
        with open(file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)

        captured_at = parse_timestamp_from_json(json_data)

        # Check if data already exists in database
        if await check_timestamp_exists(captured_at):
            return {
                "status": "already_exists",
                "message": f"Data from {captured_at} already exists in database",
                "filename": request.filename,
                "timestamp": captured_at.isoformat(),
                "records_inserted": 0
            }

        # Process the file
        records_inserted, parsed_timestamp = await process_json_file_async(file_path)

        logger.info(f"Successfully ingested {request.filename}: {records_inserted} records")

        return {
            "status": "success",
            "message": f"File ingested successfully",
            "filename": request.filename,
            "timestamp": parsed_timestamp.isoformat(),
            "records_inserted": records_inserted
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error ingesting file {request.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Include the fetch endpoint with /api prefix
app.get("/api/fetch")(fetch_data)

# Include the sync status endpoint with /api prefix
app.get("/api/sync-status")(sync_status_check)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
