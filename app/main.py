"""
VS Code Extension Stats - FastAPI Application

Simple web app to display VS Code extension statistics with charts.
"""

import json
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import init_db, close_db, fetch_all, fetch_one
from app.fetch_endpoint import fetch_data, validate_client_key

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

# Include the fetch endpoint with /api prefix
app.get("/api/fetch")(fetch_data)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
