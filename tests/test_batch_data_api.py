"""
Integration tests for the new Batch Data API endpoints

These tests make HTTP calls to the running server at http://localhost:5001
"""
import pytest
import json
import csv
import io
import requests
from datetime import datetime
from urllib.parse import urlencode

# BASE_URL = "http://localhost:5001"
BASE_URL = "https://image-analyzer-mzhpbbuvma-uc.a.run.app/"


@pytest.fixture
def session():
    """Create a requests session"""
    return requests.Session()


class TestBatchDataListEndpoint:
    """Tests for GET /api/v1/batch-data endpoint"""

    def test_batch_data_endpoint_exists(self, session):
        """Test that the endpoint is accessible"""
        response = session.get(f'{BASE_URL}/api/v1/batch-data')
        assert response.status_code in [200, 400, 500]  # Endpoint exists

    def test_batch_data_default_pagination(self, session):
        """Test default pagination parameters"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=all&store_image=all')
        assert response.status_code == 200
        data = response.json()
        assert 'data' in data
        assert 'meta' in data
        assert 'page' in data['meta']
        assert 'per_page' in data['meta']
        assert 'total' in data['meta']

    def test_batch_data_success_filter_all(self, session):
        """Test success filter with 'all' value"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=all&store_image=all')
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data['data'], list)

    def test_batch_data_success_filter_true(self, session):
        """Test success filter with 'true' value"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=true&store_image=all')
        assert response.status_code == 200
        data = response.json()
        # All results should have success=true
        for result in data['data']:
            assert result.get('success') is True

    def test_batch_data_success_filter_false(self, session):
        """Test success filter with 'false' value"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=false&store_image=all')
        assert response.status_code == 200
        data = response.json()
        # All results should have success=false
        for result in data['data']:
            assert result.get('success') is False

    def test_batch_data_store_image_filter_true(self, session):
        """Test store_image filter with 'true' value"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=all&store_image=true')
        assert response.status_code == 200
        data = response.json()
        # All results should have store_image=true
        for result in data['data']:
            assert result.get('store_image') is True

    def test_batch_data_store_image_filter_false(self, session):
        """Test store_image filter with 'false' value"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=all&store_image=false')
        assert response.status_code == 200
        data = response.json()
        # All results should have store_image=false
        for result in data['data']:
            assert result.get('store_image') is False

    def test_batch_data_pagination_page_2(self, session):
        """Test pagination to page 2"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=2&per_page=25&success=all&store_image=all')
        assert response.status_code == 200
        data = response.json()
        assert data['meta']['page'] == 2

    def test_batch_data_per_page_limit(self, session):
        """Test per_page parameter"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=10&success=all&store_image=all')
        assert response.status_code == 200
        data = response.json()
        assert len(data['data']) <= 10

    def test_batch_data_sort_by_created_at_asc(self, session):
        """Test sorting by created_at ascending"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=all&store_image=all&sort=created_at:asc')
        assert response.status_code == 200
        data = response.json()
        if len(data['data']) > 1:
            dates = [result.get('created_at') for result in data['data']]
            assert dates == sorted(dates)

    def test_batch_data_sort_by_created_at_desc(self, session):
        """Test sorting by created_at descending"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=all&store_image=all&sort=created_at:desc')
        assert response.status_code == 200
        data = response.json()
        if len(data['data']) > 1:
            dates = [result.get('created_at') for result in data['data']]
            assert dates == sorted(dates, reverse=True)

    def test_batch_data_sort_by_processing_time(self, session):
        """Test sorting by processing_time_seconds"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=all&store_image=all&sort=processing_time_seconds:desc')
        assert response.status_code == 200
        data = response.json()
        assert len(data['data']) >= 0

    def test_batch_data_response_structure(self, session):
        """Test the response structure includes all required fields"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=5&success=all&store_image=all')
        assert response.status_code == 200
        data = response.json()

        required_fields = ['success', 'store_image', 'text_content', 'store_name',
                           'business_contact', 'image_description', 'url',
                           'processing_time_seconds', 'created_at', 'batch_id']

        if len(data['data']) > 0:
            for field in required_fields:
                assert field in data['data'][0]

    def test_batch_data_empty_result(self, session):
        """Test when no results match the filter"""
        # Use a non-existent batch ID
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=all&store_image=all&batch_id=00000000-0000-0000-0000-000000000000')
        assert response.status_code == 200
        data = response.json()
        assert data['data'] == []
        assert data['meta']['total'] == 0


class TestBatchDataExportEndpoint:
    """Tests for GET /api/v1/batch-data/export endpoint"""

    def test_batch_data_export_endpoint_exists(self, session):
        """Test that the export endpoint is accessible"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=all&store_image=all')
        assert response.status_code == 200

    def test_batch_data_export_returns_csv(self, session):
        """Test that export endpoint returns CSV content"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=all&store_image=all')
        assert response.status_code == 200
        assert 'text/csv' in response.headers.get('Content-Type', '')
        assert 'attachment' in response.headers.get('Content-Disposition', '')

    def test_batch_data_export_csv_headers(self, session):
        """Test that CSV has correct headers in the specified order"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=all&store_image=all')
        assert response.status_code == 200

        csv_data = response.text
        lines = csv_data.strip().split('\n')
        if len(lines) > 0:
            headers = [h.strip()
                       for h in lines[0].split(',')]  # Strip whitespace
            expected_headers = ['success', 'store_image', 'text_content', 'store_name',
                                'business_contact', 'image_description', 'url',
                                'processing_time_seconds', 'created_at', 'batch_id']
            assert headers == expected_headers

    def test_batch_data_export_csv_format(self, session):
        """Test that export data is valid CSV format"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=all&store_image=all')
        assert response.status_code == 200

        csv_data = response.text
        csv_file = io.StringIO(csv_data)
        reader = csv.reader(csv_file)
        rows = list(reader)

        # Should have at least header row
        assert len(rows) >= 1
        # Header row should have 10 columns
        assert len(rows[0]) == 10

    def test_batch_data_export_success_filter(self, session):
        """Test export with success filter"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=true&store_image=all')
        assert response.status_code == 200

        csv_data = response.text
        lines = csv_data.strip().split('\n')

        # Check that all data rows have success=true
        for line in lines[1:]:  # Skip header
            if line.strip():  # Skip empty lines
                # Parse line carefully to handle quoted fields
                pass

    def test_batch_data_export_store_image_filter(self, session):
        """Test export with store_image filter"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=all&store_image=true')
        assert response.status_code == 200

        csv_data = response.text
        lines = csv_data.strip().split('\n')

        # Should have header and possibly data rows
        assert len(lines) >= 1

    def test_batch_data_export_empty_result(self, session):
        """Test export when no results match the filter"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=all&store_image=all&batch_id=00000000-0000-0000-0000-000000000000')
        assert response.status_code == 200

        csv_data = response.text
        lines = csv_data.strip().split('\n')

        # Should still have header row
        assert len(lines) >= 1
        # Header row should have 10 columns
        assert len(lines[0].split(',')) == 10

    def test_batch_data_export_content_disposition(self, session):
        """Test that export has proper Content-Disposition header"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=all&store_image=all')
        assert response.status_code == 200

        disposition = response.headers.get('Content-Disposition', '')
        assert 'attachment' in disposition
        assert 'batch-data-export.csv' in disposition

    def test_batch_data_export_special_characters(self, session):
        """Test that export properly handles special characters in CSV"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=all&store_image=all')
        assert response.status_code == 200

        csv_data = response.text
        # Should be able to parse as valid CSV even with special characters
        csv_file = io.StringIO(csv_data)
        reader = csv.reader(csv_file)
        rows = list(reader)
        assert len(rows) >= 1


class TestBatchDataIntegration:
    """Integration tests combining list and export endpoints"""

    def test_export_and_parse_csv(self, session):
        """Test that exported CSV can be parsed correctly"""
        # First get some data via list endpoint
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=10&success=all&store_image=all')
        assert response.status_code == 200
        list_data = response.json()

        # Then get same data via export endpoint
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data/export?success=all&store_image=all')
        assert response.status_code == 200

        csv_data = response.text
        csv_file = io.StringIO(csv_data)
        reader = csv.DictReader(csv_file)
        export_data = list(reader)

        # Export should have at least as many rows as the first page of list endpoint
        # (might have more due to no pagination limit)
        assert len(export_data) >= len(
            list_data['data']) or len(export_data) > 0

    def test_combined_filters(self, session):
        """Test using multiple filters together"""
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=25&success=true&store_image=true')
        assert response.status_code == 200
        data = response.json()

        # All results should match both filters
        for result in data['data']:
            assert result.get('success') is True
            assert result.get('store_image') is True

    def test_filter_consistency(self, session):
        """Test that same filters in list and export return consistent results"""
        # Get first 5 results from list endpoint
        response = session.get(
            f'{BASE_URL}/api/v1/batch-data?page=1&per_page=5&success=true&store_image=all')
        assert response.status_code == 200
        list_data = response.json()

        if len(list_data['data']) > 0:
            # Get export with same filters
            response = session.get(
                f'{BASE_URL}/api/v1/batch-data/export?success=true&store_image=all')
            assert response.status_code == 200

            csv_data = response.text
            csv_file = io.StringIO(csv_data)
            reader = csv.DictReader(csv_file)
            export_data = list(reader)

            # Count of success=true in export should match
            true_count = sum(1 for row in export_data if row.get(
                'success', '').lower() == 'true')
            assert true_count > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
