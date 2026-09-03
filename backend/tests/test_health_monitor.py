import pytest
import time
from app.health_monitor.analyzer import HealthAnalyzer, DiskTrendPoint

def test_linear_regression_disk_full_alert():
    now = time.time()
    history = [
        DiskTrendPoint(timestamp_epoch=now, free_bytes=10 * (1024**3)),
        DiskTrendPoint(timestamp_epoch=now + 86400, free_bytes=9 * (1024**3)),
        DiskTrendPoint(timestamp_epoch=now + 2 * 86400, free_bytes=8 * (1024**3)),
    ]
    
    days_left = HealthAnalyzer.predict_disk_full_days(history)
    assert days_left is not None
    assert 7.9 <= days_left <= 8.1

    alert = HealthAnalyzer.check_disk_alert(history, threshold_days=14.0)
    assert alert is not None
    assert alert["alert_type"] == "DISK_FULL_PREDICTION"
    assert alert["days_remaining"] == 8.0
    assert alert["severity"] == "WARNING"

def test_linear_regression_no_alert_when_stable_or_increasing():
    now = time.time()
    history = [
        DiskTrendPoint(timestamp_epoch=now, free_bytes=10 * (1024**3)),
        DiskTrendPoint(timestamp_epoch=now + 86400, free_bytes=11 * (1024**3)),
    ]
    days_left = HealthAnalyzer.predict_disk_full_days(history)
    assert days_left is None
    
    alert = HealthAnalyzer.check_disk_alert(history, threshold_days=14.0)
    assert alert is None
