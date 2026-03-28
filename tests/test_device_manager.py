import pytest

from core.device_manager import DeviceManager


def test_instance_adb_port_default_free(monkeypatch):
    mgr = DeviceManager()

    # Force no port conflict behavior
    monkeypatch.setattr(mgr, '_is_adb_port_conflict', lambda port: False)

    port = mgr._instance_adb_port(1)
    assert port == 6520


def test_instance_adb_port1_conflict(monkeypatch):
    mgr = DeviceManager()

    # Simulate default 6520 in use, next free 6521
    def conflict(port):
        return port == 6520

    monkeypatch.setattr(mgr, '_is_adb_port_conflict', conflict)

    port = mgr._instance_adb_port(1)
    assert port == 6521


def test_resolve_system_image_dir_prefers_existing(monkeypatch, tmp_path):
    mgr = DeviceManager()
    test_dir = tmp_path / "images"
    test_dir.mkdir()
    (test_dir / "system.img").write_text("x")

    monkeypatch.setenv("CVD_IMAGES_DIR", str(test_dir))
    result = mgr._resolve_system_image_dir()

    assert result == test_dir
