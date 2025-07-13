#!/usr/bin/env python3
"""
VS Code Extension Stats Ingestion Script

Processes JSON files from raw_json/ directory and inserts data into PostgreSQL.
Handles duplicate prevention and file archival.

Usage:
    python ingest.py
    
Environment variables:
    DATABASE_URL - PostgreSQL connection string
"""

import os
import json
import glob
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables (for standalone script usage)
load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://localhost/vscode_stats')
RAW_JSON_DIR = Path('data')
PROCESSED_JSON_DIR = Path('processed_json')
BATCH_SIZE = 500

# Pacific timezone (handles PST/PDT automatically)
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

def ensure_directories():
    """Create necessary directories if they don't exist."""
    RAW_JSON_DIR.mkdir(exist_ok=True)
    PROCESSED_JSON_DIR.mkdir(exist_ok=True)

def parse_timestamp_from_json(data):
    """
    Extract timestamp from JSON data's created_at field.
    Returns timezone-aware datetime object in Pacific time (PST/PDT).
    """
    try:
        created_at_str = data.get('created_at')
        if not created_at_str:
            print(f"Warning: No created_at field found in JSON data")
            return datetime.now(PACIFIC_TZ)

        # Parse ISO format timestamp with timezone
        # Example: "2025-07-12T12:06:24.275317-08:00"
        dt = datetime.fromisoformat(created_at_str)

        # Ensure we have a timezone-aware datetime in Pacific time
        if dt.tzinfo is not None:
            # Convert to Pacific time
            dt = dt.astimezone(PACIFIC_TZ)
        else:
            # If no timezone info, assume it's already in Pacific time
            dt = dt.replace(tzinfo=PACIFIC_TZ)

        return dt

    except (ValueError, TypeError) as e:
        print(f"Warning: Could not parse timestamp from created_at field: {e}")
        return datetime.now(PACIFIC_TZ)

def process_json_file(conn, json_file_path):
    """
    Process a single JSON file and insert data into database.
    Returns number of rows inserted.
    """
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)

        # Extract timestamp from JSON created_at field
        captured_at = parse_timestamp_from_json(json_data)

        # Get the extensions list from the data.items field
        if isinstance(json_data, dict) and 'data' in json_data and 'items' in json_data['data']:
            extensions = json_data['data']['items']
        elif isinstance(json_data, list):
            # Fallback: if it's directly a list of extensions
            extensions = json_data
        else:
            print(f"Warning: {json_file_path} does not contain expected data structure")
            return 0

        rows_inserted = 0
        
        # Process in batches
        for i in range(0, len(extensions), BATCH_SIZE):
            batch = extensions[i:i + BATCH_SIZE]
            
            with conn.cursor() as cur:
                for ext in batch:
                    try:
                        cur.execute("""
                            INSERT INTO extension_stats 
                            (extension_id, name, publisher, description, version, 
                             install_count, rating, rating_count, tags, categories, captured_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (extension_id, captured_at) DO NOTHING
                        """, (
                            ext.get('extension_id', ext.get('id', '')),  # Handle both field names
                            ext.get('name', ''),
                            ext.get('publisher', ''),
                            ext.get('description', ''),
                            ext.get('version', ''),
                            ext.get('install_count', ext.get('installs', 0)),  # Handle both field names
                            ext.get('rating', None),
                            ext.get('rating_count', 0),
                            ext.get('tags', []),
                            ext.get('categories', []),
                            captured_at
                        ))
                        rows_inserted += 1
                    except Exception as e:
                        print(f"Error inserting extension {ext.get('id', 'unknown')}: {e}")
                        continue
                
                conn.commit()
        
        return rows_inserted
        
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON file {json_file_path}: {e}")
        return 0
    except Exception as e:
        print(f"Error processing file {json_file_path}: {e}")
        return 0

def archive_processed_file(json_file_path):
    """Move processed file to processed_json directory."""
    try:
        dest_path = PROCESSED_JSON_DIR / Path(json_file_path).name
        shutil.move(json_file_path, dest_path)
        print(f"Archived: {json_file_path} -> {dest_path}")
    except Exception as e:
        print(f"Error archiving {json_file_path}: {e}")

def main():
    """Main ingestion process."""
    ensure_directories()
    
    # Find all JSON files to process
    json_files = sorted(glob.glob(str(RAW_JSON_DIR / "*.json")))
    
    if not json_files:
        print("No JSON files found in raw_json/ directory")
        return
    
    print(f"Found {len(json_files)} JSON files to process")
    
    # Connect to database
    try:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            total_rows = 0
            processed_files = 0
            
            for json_file in tqdm(json_files, desc="Processing files"):
                rows = process_json_file(conn, json_file)
                total_rows += rows
                processed_files += 1
                
                # Archive the processed file
                archive_processed_file(json_file)
            
            print(f"\nIngestion complete!")
            print(f"Files processed: {processed_files}")
            print(f"Total rows inserted: {total_rows}")
            
    except psycopg.Error as e:
        print(f"Database error: {e}")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
