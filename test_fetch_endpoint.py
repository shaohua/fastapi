import pytest
import json
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app
from config import VALID_CLIENT_KEYS, DATA_DIRECTORY

# Create test client
client = TestClient(app)

# Test configuration
VALID_TEST_KEY = list(VALID_CLIENT_KEYS)[0] if VALID_CLIENT_KEYS else "550e8400-e29b-41d4-a716-446655440000"
INVALID_KEY = "invalid-key"
MALFORMED_UUID = "not-a-uuid"
VALID_UUID_NOT_IN_CONFIG = "123e4567-e89b-12d3-a456-426614174000"


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test data files."""
    temp_dir = tempfile.mkdtemp()
    original_data_dir = DATA_DIRECTORY
    
    # Patch the DATA_DIRECTORY in the fetch_endpoint module
    with patch('fetch_endpoint.DATA_DIR', Path(temp_dir)):
        yield Path(temp_dir)
    
    # Clean up
    shutil.rmtree(temp_dir, ignore_errors=True)


def cleanup_test_files():
    """Clean up test files after tests."""
    data_dir = Path(DATA_DIRECTORY)
    files_to_remove = [
        data_dir / "last_fetched.json",
        data_dir / "data.json"
    ]
    for file_path in files_to_remove:
        if file_path.exists():
            file_path.unlink()


class TestFetchEndpointValidation:
    """Test client key validation functionality."""
    
    def test_valid_key_dry_run(self):
        """Test fetch endpoint with valid key in dry run mode."""
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "success"
        assert data["dry_run"] is True
        assert "would_create" in data
        assert len(data["would_create"]) == 2
        assert "message" in data
        assert "timestamp" in data
        assert data["message"] == "Dry run mode - no files were created"
        assert data["files_created"] == []

    def test_invalid_key_format(self):
        """Test fetch endpoint with malformed UUID."""
        response = client.get(f"/fetch?key={MALFORMED_UUID}&dryrun=1")
        
        assert response.status_code == 401
        data = response.json()
        assert "Invalid or unauthorized client key" in data["detail"]

    def test_valid_uuid_not_in_config(self):
        """Test fetch endpoint with valid UUID format but not in config."""
        response = client.get(f"/fetch?key={VALID_UUID_NOT_IN_CONFIG}&dryrun=1")
        
        assert response.status_code == 401
        data = response.json()
        assert "Invalid or unauthorized client key" in data["detail"]

    def test_missing_key_parameter(self):
        """Test fetch endpoint without key parameter."""
        response = client.get("/fetch?dryrun=1")
        
        assert response.status_code == 422  # Validation error
        data = response.json()
        assert "detail" in data
        # Check that the error mentions the missing 'key' field
        assert any("key" in str(error) for error in data["detail"])


class TestFetchEndpointDryRun:
    """Test dry run functionality."""
    
    def test_dry_run_mode_explicit_1(self):
        """Test dry run mode with dryrun=1."""
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["dry_run"] is True
        assert "would_create" in data
        assert "files_created" in data
        assert len(data["files_created"]) == 0
        assert len(data["would_create"]) == 2

    def test_dry_run_mode_default_0(self):
        """Test default dryrun value (should be 0)."""
        # Clean up before test to avoid interference
        cleanup_test_files()
        
        response = client.get(f"/fetch?key={VALID_TEST_KEY}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is False  # Default should be 0 (False)
        
        # Clean up after test
        cleanup_test_files()

    def test_dry_run_mode_explicit_0(self):
        """Test actual execution mode with dryrun=0."""
        # Clean up before test
        cleanup_test_files()
        
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=0")
        
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is False
        
        # Clean up after test
        cleanup_test_files()


class TestFetchEndpointFileCreation:
    """Test file creation functionality."""
    
    def test_actual_execution_creates_files(self):
        """Test that actual execution creates the expected files."""
        # Clean up before test
        cleanup_test_files()
        
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=0")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "success"
        assert data["dry_run"] is False
        assert "files_created" in data
        assert len(data["files_created"]) == 2
        assert "last_fetched_data" in data
        assert "data_file_preview" in data
        
        # Verify files were actually created
        data_dir = Path(DATA_DIRECTORY)
        assert (data_dir / "last_fetched.json").exists()
        assert (data_dir / "data.json").exists()
        
        # Clean up after test
        cleanup_test_files()

    def test_last_fetched_file_content(self):
        """Test the content of the last_fetched.json file."""
        # Clean up before test
        cleanup_test_files()
        
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=0")
        assert response.status_code == 200
        
        # Verify file contents
        data_dir = Path(DATA_DIRECTORY)
        with open(data_dir / "last_fetched.json", 'r') as f:
            last_fetched = json.load(f)
            
        assert "timestamp" in last_fetched
        assert "unix_timestamp" in last_fetched
        assert "human_readable" in last_fetched
        assert isinstance(last_fetched["unix_timestamp"], int)
        
        # Clean up after test
        cleanup_test_files()

    def test_data_file_content(self):
        """Test the content of the data.json file."""
        # Clean up before test
        cleanup_test_files()
        
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=0")
        assert response.status_code == 200
        
        # Verify file contents
        data_dir = Path(DATA_DIRECTORY)
        with open(data_dir / "data.json", 'r') as f:
            data_content = json.load(f)
            
        assert data_content["status"] == "success"
        assert "data" in data_content
        assert "metadata" in data_content
        assert "created_at" in data_content
        assert data_content["data"]["count"] == 2
        assert len(data_content["data"]["items"]) == 2
        
        # Clean up after test
        cleanup_test_files()


class TestFetchEndpointErrorHandling:
    """Test error handling scenarios."""
    
    @patch('fetch_endpoint.ensure_data_directory')
    def test_directory_creation_error(self, mock_ensure_dir):
        """Test handling of directory creation errors."""
        mock_ensure_dir.side_effect = PermissionError("Permission denied")
        
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=0")
        
        assert response.status_code == 500
        data = response.json()
        assert "Error creating files" in data["detail"]

    @patch('fetch_endpoint.create_last_fetched_file')
    def test_file_creation_error(self, mock_create_file):
        """Test handling of file creation errors."""
        mock_create_file.side_effect = IOError("Disk full")
        
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=0")
        
        assert response.status_code == 500
        data = response.json()
        assert "Error creating files" in data["detail"]


class TestFetchEndpointResponseStructure:
    """Test response structure and data types."""
    
    def test_dry_run_response_structure(self):
        """Test the structure of dry run response."""
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=1")
        
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        required_fields = ["status", "dry_run", "timestamp", "files_created"]
        for field in required_fields:
            assert field in data
        
        # Dry run specific fields
        assert "would_create" in data
        assert "message" in data
        
        # Data types
        assert isinstance(data["dry_run"], bool)
        assert isinstance(data["files_created"], list)
        assert isinstance(data["would_create"], list)

    def test_actual_run_response_structure(self):
        """Test the structure of actual execution response."""
        # Clean up before test
        cleanup_test_files()
        
        response = client.get(f"/fetch?key={VALID_TEST_KEY}&dryrun=0")
        
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        required_fields = ["status", "dry_run", "timestamp", "files_created"]
        for field in required_fields:
            assert field in data
        
        # Actual run specific fields
        assert "last_fetched_data" in data
        assert "data_file_preview" in data
        assert "message" in data
        
        # Data types
        assert isinstance(data["dry_run"], bool)
        assert isinstance(data["files_created"], list)
        assert isinstance(data["last_fetched_data"], dict)
        assert isinstance(data["data_file_preview"], dict)
        
        # Clean up after test
        cleanup_test_files()


if __name__ == "__main__":
    # Run basic tests manually
    print("Running basic tests...")
    
    test_instance = TestFetchEndpointValidation()
    
    print("1. Testing dry run with valid key...")
    test_instance.test_valid_key_dry_run()
    print("✓ Dry run test passed")
    
    print("2. Testing invalid key...")
    test_instance.test_invalid_key_format()
    print("✓ Invalid key test passed")
    
    print("3. Testing missing key...")
    test_instance.test_missing_key_parameter()
    print("✓ Missing key test passed")
    
    print("\nAll basic tests passed! Run 'pytest test_fetch_endpoint.py' for full test suite.")
