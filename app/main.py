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
        DATE(captured_at) as day,
        MAX(install_count) as installs,
        MAX(rating) as rating,
        MAX(rating_count) as rating_count,
        MAX(version) as version
    FROM extension_stats 
    WHERE extension_id = %s 
      AND captured_at >= NOW() - INTERVAL '30 days'
    GROUP BY DATE(captured_at)
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
