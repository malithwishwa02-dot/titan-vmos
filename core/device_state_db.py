"""
Titan V11.3 — Device State Database
SQLite-backed persistent storage for device state with automatic recovery.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("titan.device-state-db")


class DeviceStateDB:
    """SQLite database for persistent device state."""
    
    def __init__(self, db_path: str = "/opt/titan/data/devices.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()
    
    def _init_schema(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    adb_target TEXT NOT NULL,
                    state TEXT NOT NULL,
                    device_type TEXT DEFAULT 'cuttlefish',
                    instance_num INTEGER,
                    adb_port INTEGER,
                    vnc_port INTEGER,
                    config TEXT,
                    patch_result TEXT,
                    stealth_score INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_devices_state ON devices(state)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_devices_created ON devices(created_at)
            """)
            conn.commit()
            logger.info(f"Device state database initialized: {self.db_path}")
    
    def save_device(self, device_dict: Dict[str, Any]) -> bool:
        """Save device state to database."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO devices (
                            id, adb_target, state, device_type, instance_num,
                            adb_port, vnc_port, config, patch_result, stealth_score,
                            created_at, updated_at, error
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
                    """, (
                        device_dict.get("id"),
                        device_dict.get("adb_target"),
                        device_dict.get("state"),
                        device_dict.get("device_type", "cuttlefish"),
                        device_dict.get("instance_num"),
                        device_dict.get("adb_port"),
                        device_dict.get("vnc_port"),
                        json.dumps(device_dict.get("config", {})),
                        json.dumps(device_dict.get("patch_result", {})),
                        device_dict.get("stealth_score", 0),
                        device_dict.get("created_at"),
                        device_dict.get("error", ""),
                    ))
                    conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save device {device_dict.get('id')}: {e}")
            return False
    
    def load_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Load device state from database."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM devices WHERE id = ?",
                        (device_id,)
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None
                    
                    return {
                        "id": row["id"],
                        "adb_target": row["adb_target"],
                        "state": row["state"],
                        "device_type": row["device_type"],
                        "instance_num": row["instance_num"],
                        "adb_port": row["adb_port"],
                        "vnc_port": row["vnc_port"],
                        "config": json.loads(row["config"] or "{}"),
                        "patch_result": json.loads(row["patch_result"] or "{}"),
                        "stealth_score": row["stealth_score"],
                        "created_at": row["created_at"],
                        "error": row["error"],
                    }
        except Exception as e:
            logger.error(f"Failed to load device {device_id}: {e}")
            return None
    
    def load_all_devices(self) -> List[Dict[str, Any]]:
        """Load all devices from database."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute("SELECT * FROM devices ORDER BY created_at DESC")
                    devices = []
                    for row in cursor.fetchall():
                        devices.append({
                            "id": row["id"],
                            "adb_target": row["adb_target"],
                            "state": row["state"],
                            "device_type": row["device_type"],
                            "instance_num": row["instance_num"],
                            "adb_port": row["adb_port"],
                            "vnc_port": row["vnc_port"],
                            "config": json.loads(row["config"] or "{}"),
                            "patch_result": json.loads(row["patch_result"] or "{}"),
                            "stealth_score": row["stealth_score"],
                            "created_at": row["created_at"],
                            "error": row["error"],
                        })
                    return devices
        except Exception as e:
            logger.error(f"Failed to load all devices: {e}")
            return []
    
    def delete_device(self, device_id: str) -> bool:
        """Delete device from database."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
                    conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete device {device_id}: {e}")
            return False
    
    def get_devices_by_state(self, state: str) -> List[Dict[str, Any]]:
        """Get all devices in a specific state."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM devices WHERE state = ? ORDER BY created_at DESC",
                        (state,)
                    )
                    devices = []
                    for row in cursor.fetchall():
                        devices.append({
                            "id": row["id"],
                            "adb_target": row["adb_target"],
                            "state": row["state"],
                            "device_type": row["device_type"],
                            "instance_num": row["instance_num"],
                            "adb_port": row["adb_port"],
                            "vnc_port": row["vnc_port"],
                            "config": json.loads(row["config"] or "{}"),
                            "patch_result": json.loads(row["patch_result"] or "{}"),
                            "stealth_score": row["stealth_score"],
                            "created_at": row["created_at"],
                            "error": row["error"],
                        })
                    return devices
        except Exception as e:
            logger.error(f"Failed to get devices by state {state}: {e}")
            return []
    
    def backup(self, backup_path: str) -> bool:
        """Create backup of database."""
        try:
            with self._lock:
                backup_file = Path(backup_path)
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(self.db_path) as conn:
                    with sqlite3.connect(backup_path) as backup_conn:
                        conn.backup(backup_conn)
            logger.info(f"Database backed up to {backup_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to backup database: {e}")
            return False
