from unittest.mock import patch
import db_service

@patch('db_service.fetch_user_record', return_value={'id': 1, 'name': 'Alice'})
def test_fetch_user_record(mock_fetch):
    result = db_service.fetch_user_record(1)
    assert result['name'] == 'Alice'