"""GDSBackupManager 单元测试。"""

import pytest
import tempfile
from pathlib import Path

from state.snapshot_manager import GDSBackupManager


class TestGDSBackupManager:
    """GDS 备份管理器。"""

    def test_save_backup_creates_file(self, tmp_path):
        """保存备份应在 backups/ 目录下创建文件。"""
        # 创建源 GDS 文件
        src_gds = tmp_path / "input.gds"
        src_gds.write_bytes(b"FAKE_GDS_DATA")

        mgr = GDSBackupManager(str(tmp_path / "state"))
        backup_path = mgr.save_backup(str(src_gds))

        assert backup_path is not None
        assert backup_path.exists()
        assert backup_path.read_bytes() == b"FAKE_GDS_DATA"

    def test_save_backup_nonexistent_source(self, tmp_path):
        """源文件不存在应返回 None。"""
        mgr = GDSBackupManager(str(tmp_path / "state"))
        result = mgr.save_backup("/nonexistent/path.gds")
        assert result is None

    def test_restore_backup(self, tmp_path):
        """恢复备份应覆盖目标文件。"""
        # 创建备份
        backup_dir = tmp_path / "state" / "backups"
        backup_dir.mkdir(parents=True)
        backup_file = backup_dir / "pre_update_test.gds"
        backup_file.write_bytes(b"BACKUP_DATA")

        # 创建一个将被覆盖的目标
        target = tmp_path / "output.gds"
        target.write_bytes(b"CURRENT_DATA")

        mgr = GDSBackupManager(str(tmp_path / "state"))
        success = mgr.restore_backup(backup_file, str(target))

        assert success
        assert target.read_bytes() == b"BACKUP_DATA"

    def test_restore_nonexistent_backup(self, tmp_path):
        """恢复不存在的备份应返回 False。"""
        mgr = GDSBackupManager(str(tmp_path / "state"))
        success = mgr.restore_backup(Path("/nonexistent/backup.gds"), str(tmp_path / "output.gds"))
        assert not success

    def test_backup_naming_convention(self, tmp_path):
        """备份文件名应包含时间戳。"""
        src_gds = tmp_path / "input.gds"
        src_gds.write_bytes(b"GDS")

        mgr = GDSBackupManager(str(tmp_path / "state"))
        backup_path = mgr.save_backup(str(src_gds))

        assert backup_path is not None
        assert backup_path.name.startswith("pre_update_")
        assert backup_path.suffix == ".gds"
