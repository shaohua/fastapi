# Configuration file for the FastAPI application

import os

# Valid client UUIDs for authentication
# Add your valid client UUIDs here
VALID_CLIENT_KEYS = {
    "550e8400-e29b-41d4-a716-446655440000",  # Example UUID - replace with actual client keys
    # Add more valid UUIDs as needed
    # "123e4567-e89b-12d3-a456-426614174000",
}

# Data directory configuration
# Use path relative to this config file's location for consistency
_config_dir = os.path.dirname(os.path.abspath(__file__))
if os.getenv('RAILWAY_ENVIRONMENT_NAME') == 'production':
    DATA_DIRECTORY = os.path.join(_config_dir, "..", "data")
else:
    DATA_DIRECTORY = os.path.join(_config_dir, "data")

# Other configuration options can be added here
DEBUG_MODE = False
