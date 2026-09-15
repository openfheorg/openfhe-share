from unittest.mock import Mock

import pytest

from app.core.mysql.managers.ThresholdManager import (
    Threshold,
    ThresholdManager,
    ThresholdMethod,
)


def _manager(cursor=None, connection=None):
    value = object.__new__(ThresholdManager)
    value.cursor = cursor or Mock()
    value.connection = connection or Mock()
    return value


def test_threshold_normalized_casts_method_and_value():
    value = Threshold(" exposed ", "7", id=3).normalized()
    assert value == Threshold(ThresholdMethod.EXPOSED, 7, id=3)


def test_threshold_normalized_rejects_unknown_method():
    with pytest.raises(ValueError):
        Threshold("hidden", 4).normalized()


def test_get_or_create_returns_existing_row_without_commit():
    cursor = Mock()
    cursor.fetchone.return_value = {"id": 12}
    connection = Mock()
    manager = _manager(cursor, connection)

    result = manager.get_or_create(Threshold("protected", 5))

    assert result == Threshold(ThresholdMethod.PROTECTED, 5, id=12)
    connection.commit.assert_not_called()


def test_get_or_create_inserts_and_commits():
    cursor = Mock()
    cursor.fetchone.return_value = None
    cursor.lastrowid = 22
    connection = Mock()
    manager = _manager(cursor, connection)

    result = manager.get_or_create(Threshold(ThresholdMethod.EXPOSED, 10))

    assert result.id == 22
    connection.commit.assert_called_once()


def test_get_or_create_rolls_back_on_failure():
    cursor = Mock()
    cursor.execute.side_effect = RuntimeError("db")
    connection = Mock()
    manager = _manager(cursor, connection)

    with pytest.raises(RuntimeError):
        manager.get_or_create(Threshold("protected", 5))
    connection.rollback.assert_called_once()
