import json
from flask import Flask

import pytest


@pytest.fixture
def app(monkeypatch):
    # Ensure environment values parsed by EnterpriseConfig are valid integers
    # to avoid pydantic parsing errors during import.
    monkeypatch.setenv('MAX_UPLOAD_SIZE', '104857600')
    monkeypatch.setenv('CHUNK_SIZE', '500')
    monkeypatch.setenv('MAX_BATCH_SIZE', '5000')

    from src.polling_api import polling_api

    app = Flask(__name__)
    app.register_blueprint(polling_api)
    return app


def test_get_batch_progress_normal(monkeypatch, app):
    # Simulate normal per-batch get_batch_status response
    batch_id = '11111111-1111-1111-1111-111111111111'

    normal_status = {
        'batch_info': {'status': 'processing', 'is_active': True},
        'progress': {
            'progress_percentage': 42.5,
            'processed_count': 425,
            'total_urls': 1000,
            'successful_count': 420,
            'failed_count': 5,
            'current_chunk': 3,
            'total_chunks': 10
        },
        'timing': {'estimated_completion': None},
        'performance': {'processing_rate_per_minute': 50}
    }

    import src.batch_manager as batch_manager_module

    # Patch the instance on the module (batch_manager_module.batch_manager)
    monkeypatch.setattr(batch_manager_module.batch_manager,
                        'get_batch_status', lambda bid: normal_status)

    client = app.test_client()
    resp = client.get(f'/api/v1/batches/{batch_id}/progress')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    payload = data['data']
    assert payload['total_urls'] == 1000
    assert payload['processed_count'] == 425


def test_get_batch_progress_parent_aggregated(monkeypatch, app):
    # Simulate get_batch_status returning no 'progress' and parent aggregated status available
    batch_id = '22222222-2222-2222-2222-222222222222'

    def fake_get_batch_status(bid):
        # Return a shape that does not include 'progress'
        return {'unexpected': True}

    parent_payload = {
        'parent_batch_id': batch_id,
        'total_batches': 2,
        'overall_status': 'processing',
        'total_urls': 1500,
        'processed_count': 500,
        'successful_count': 480,
        'failed_count': 20,
        'total_chunks': 25,
        'progress_percentage': 33.33
    }

    import src.batch_manager as batch_manager_module

    # Patch the instance methods directly
    monkeypatch.setattr(batch_manager_module.batch_manager,
                        'get_batch_status', fake_get_batch_status)
    monkeypatch.setattr(batch_manager_module.batch_manager,
                        'get_parent_batch_status', lambda bid: parent_payload)

    client = app.test_client()
    resp = client.get(f'/api/v1/batches/{batch_id}/progress')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    payload = data['data']
    assert payload['total_urls'] == 1500
    assert payload['processed_count'] == 500
    assert payload['progress_percentage'] == pytest.approx(33.33)
