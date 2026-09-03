from dataclasses import dataclass
from typing import List, Optional
import numpy as np

@dataclass
class DiskTrendPoint:
    timestamp_epoch: float  # seconds
    free_bytes: float

class HealthAnalyzer:
    @staticmethod
    def predict_disk_full_days(history: List[DiskTrendPoint]) -> Optional[float]:
        """
        Calculates projected days until disk free bytes reaching <= 0 using linear regression (numpy.polyfit).
        Returns None if history has fewer than 2 points or if usage is stable/decreasing.
        """
        if len(history) < 2:
            return None
        
        times = np.array([p.timestamp_epoch for p in history], dtype=float)
        frees = np.array([p.free_bytes for p in history], dtype=float)
        
        slope, intercept = np.polyfit(times, frees, 1)
        
        if slope >= 0:
            return None
        
        t_zero = -intercept / slope
        current_time = times[-1]
        
        if t_zero <= current_time:
            return 0.0
            
        seconds_remaining = t_zero - current_time
        days_remaining = seconds_remaining / (24 * 3600)
        return float(days_remaining)

    @classmethod
    def check_disk_alert(cls, history: List[DiskTrendPoint], threshold_days: float = 14.0) -> Optional[dict]:
        days_remaining = cls.predict_disk_full_days(history)
        if days_remaining is not None and days_remaining <= threshold_days:
            latest_free_gb = history[-1].free_bytes / (1024 ** 3)
            return {
                "alert_type": "DISK_FULL_PREDICTION",
                "days_remaining": round(days_remaining, 1),
                "current_free_gb": round(latest_free_gb, 2),
                "severity": "CRITICAL" if days_remaining <= 3.0 else "WARNING",
                "message": f"Disk predicted to run full in {round(days_remaining, 1)} days! (Current free: {round(latest_free_gb, 2)} GB)"
            }
        return None
