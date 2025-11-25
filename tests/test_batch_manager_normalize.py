import uuid

from src.batch_manager import BatchManager


class _DummyQuery:
    def __init__(self):
        self.last_filter_kwargs = None

    def filter_by(self, **kwargs):
        self.last_filter_kwargs = kwargs
        return self

    def first(self):
        return None


class _DummySession:
    def __init__(self, q):
        self._q = q

    def query(self, *args, **kwargs):
        return self._q


def test_get_batch_by_id_normalizes_uuid_strings():
    dummy_q = _DummyQuery()
    session = _DummySession(dummy_q)

    # Input with surrounding whitespace should be parsed as uuid.UUID
    raw = ' 73f3a247-d2a1-420e-be48-e67baaf500ef '
    result = BatchManager._get_batch_by_id(session, raw)

    # No DB row (first() returns None) but filter_by should have been called
    # with a uuid.UUID instance
    assert isinstance(dummy_q.last_filter_kwargs.get('batch_id'), uuid.UUID)


def test_get_batch_by_id_leaves_non_uuid_strings_alone():
    dummy_q = _DummyQuery()
    session = _DummySession(dummy_q)

    raw = 'not-a-uuid'
    result = BatchManager._get_batch_by_id(session, raw)

    assert dummy_q.last_filter_kwargs.get('batch_id') == 'not-a-uuid'
