from app.models.db import db
from app.models.scan import Scan, ScanStatus
from app.models.setting import Setting

__all__ = ["Scan", "ScanStatus", "Setting", "db"]
