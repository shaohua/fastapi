# Fetch Endpoint Documentation

## Overview

The `/fetch` endpoint is designed to create data files based on client validation. It supports both dry run and actual execution modes.

## Endpoint Details

- **URL**: `/fetch`
- **Method**: `GET`
- **Parameters**:
  - `key` (required): UUID string for client validation
  - `dryrun` (optional): Integer (0 or 1) to control execution mode
    - `0` (default): Actual execution - creates files
    - `1`: Dry run - simulates execution without creating files

## Usage Examples

### Dry Run Mode
```bash
curl "http://localhost:8000/fetch?key=550e8400-e29b-41d4-a716-446655440000&dryrun=1"
```

### Actual Execution
```bash
curl "http://localhost:8000/fetch?key=550e8400-e29b-41d4-a716-446655440000&dryrun=0"
```

### Using Default dryrun (0)
```bash
curl "http://localhost:8000/fetch?key=550e8400-e29b-41d4-a716-446655440000"
```

## Response Format

### Successful Dry Run Response
```json
{
  "status": "success",
  "dry_run": true,
  "timestamp": "2025-07-08T10:30:00.123456",
  "files_created": [],
  "message": "Dry run mode - no files were created",
  "would_create": [
    "../data/last_fetched.json",
    "../data/data.json"
  ]
}
```

### Successful Actual Execution Response
```json
{
  "status": "success",
  "dry_run": false,
  "timestamp": "2025-07-08T10:30:00.123456",
  "files_created": [
    "../data/last_fetched.json",
    "../data/data.json"
  ],
  "message": "Files created successfully",
  "last_fetched_data": {
    "timestamp": "2025-07-08T10:30:00.123456",
    "unix_timestamp": 1720435800,
    "human_readable": "2025-07-08 10:30:00 UTC"
  },
  "data_file_preview": {
    "status": "success",
    "data": {
      "message": "This is dummy data",
      "items": [...],
      "count": 2
    },
    "metadata": {
      "version": "1.0",
      "source": "fetch_endpoint"
    },
    "created_at": "2025-07-08T10:30:00.123456"
  }
}
```

## Error Responses

### Invalid/Unauthorized Key (401)
```json
{
  "detail": "Invalid or unauthorized client key"
}
```

### Missing Required Parameter (422)
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["query", "key"],
      "msg": "Field required"
    }
  ]
}
```

### Server Error (500)
```json
{
  "detail": "Error creating files: [error message]"
}
```

## Files Created

When executed in actual mode (dryrun=0), the endpoint creates two files in the `../data` directory:

### 1. last_fetched.json
Contains timestamp information:
```json
{
  "timestamp": "2025-07-08T10:30:00.123456",
  "unix_timestamp": 1720435800,
  "human_readable": "2025-07-08 10:30:00 UTC"
}
```

### 2. data.json
Contains dummy data structure:
```json
{
  "status": "success",
  "data": {
    "message": "This is dummy data",
    "items": [
      {"id": 1, "name": "Sample Item 1", "value": "example"},
      {"id": 2, "name": "Sample Item 2", "value": "demo"}
    ],
    "count": 2
  },
  "metadata": {
    "version": "1.0",
    "source": "fetch_endpoint"
  },
  "created_at": "2025-07-08T10:30:00.123456"
}
```

## Configuration

### Adding Valid Client Keys

Edit the `config.py` file to add valid client UUIDs:

```python
VALID_CLIENT_KEYS = {
    "550e8400-e29b-41d4-a716-446655440000",
    "123e4567-e89b-12d3-a456-426614174000",
    # Add more valid UUIDs as needed
}
```

### Data Directory

The default data directory is `../data` relative to the application root. This can be changed in `config.py`:

```python
DATA_DIRECTORY = "../data"  # Change this path as needed
```

## Testing

Run the test suite:

```bash
# Install test dependencies
pip install pytest httpx

# Run tests
pytest test_fetch_endpoint.py

# Run tests with verbose output
pytest test_fetch_endpoint.py -v
```

## Security Notes

1. **Client Key Validation**: Only UUIDs listed in `VALID_CLIENT_KEYS` are accepted
2. **UUID Format Validation**: Keys must be valid UUID format
3. **File Path Security**: Files are created only in the configured data directory
4. **Error Handling**: Detailed error logging without exposing sensitive information

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run with uvicorn (development)
uvicorn main:app --reload

# Run with hypercorn (production)
hypercorn main:app --bind "0.0.0.0:8000"
```
