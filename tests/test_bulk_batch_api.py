import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure test environment is set before imports
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['REDIS_URL'] = 'redis://localhost:6379/0'


@pytest.fixture
def app():
    """Create a test Flask app with mocked dependencies."""
    # Mock DatabaseManager before importing modules that use it
    mock_db_manager = MagicMock()
    mock_db_manager.get_session.return_value = MagicMock()

    with patch.dict('sys.modules', {
        'src.database_models': MagicMock(db_manager=mock_db_manager, BatchStatus=MagicMock(), ChunkStatus=MagicMock()),
    }):
        with patch('src.job_queue.job_queue', MagicMock()):
            # Now import polling_api with mocked dependencies
            from src.polling_api import polling_api
            from src.batch_manager import batch_manager

            app = Flask(__name__)
            app.register_blueprint(polling_api)

            # Attach batch_manager to app for test access
            app.batch_manager = batch_manager

            yield app


def test_bulk_delete_success(monkeypatch, app):
    batch_ids = ['a1', 'b2', 'c3']

    def fake_delete_batches(batch_ids_arg, force=False):
        assert batch_ids_arg == batch_ids
        return {'success': True, 'details': {bid: {'success': True} for bid in batch_ids}, 'total': 3, 'deleted': 3}

    import src.batch_manager as bm
    monkeypatch.setattr(bm.batch_manager, 'delete_batches',
                        fake_delete_batches)

    client = app.test_client()
    resp = client.post('/api/v1/batch/bulk/delete',
                       json={'batch_ids': batch_ids})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['data']['deleted'] == 3


def test_bulk_reset_partial_failure(monkeypatch, app):
    batch_ids = ['x1', 'y2']

    def fake_reset_batches(batch_ids_arg, force=False):
        # Simulate one success and one failure
        return {
            'success': False,
            'details': {
                'x1': {'success': True, 'data': {'reset_chunks': 5}},
                'y2': {'success': False, 'error': 'Batch not found'}
            },
            'total': 2,
            'reset': 1
        }

    import src.batch_manager as bm
    monkeypatch.setattr(bm.batch_manager, 'reset_batches', fake_reset_batches)

    client = app.test_client()
    resp = client.post('/api/v1/batch/bulk/reset',
                       json={'batch_ids': batch_ids})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is False
    assert body['data']['reset'] == 1
    assert body['data']['details']['y2']['success'] is False


def test_bulk_force_start_success(monkeypatch, app):
    batch_ids = ['z1']

    def fake_force_start_batches(batch_ids_arg, skip_validation=False):
        return {'success': True, 'details': {"z1": {'success': True}}, 'total': 1, 'started': 1}

    import src.batch_manager as bm
    monkeypatch.setattr(
        bm.batch_manager, 'force_start_batches', fake_force_start_batches)

    client = app.test_client()
    resp = client.post('/api/v1/batches/bulk',
                       json={'action': 'force-start', 'batch_ids': batch_ids})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['data']['started'] == 1
