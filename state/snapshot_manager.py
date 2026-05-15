"""GDS 备份管理器 — 保存/回滚 GDS 文件副本。

每次 run 前保存输入 GDS 的备份，用于 DRC/LVS 失败时回滚。
备份存放在 state/backups/ 目录下，按时间戳命名。
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GDSBackupManager:
    """GDS 备份管理器。"""

    def __init__(self, state_dir: str = "state"):
        self._backup_dir = Path(state_dir) / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def save_backup(self, gds_path: str) -> Optional[Path]:
        """保存 GDS 文件备份。

        Args:
            gds_path: 输入 GDS 文件路径

        Returns:
            备份文件路径，源文件不存在则返回 None
        """
        src = Path(gds_path)
        if not src.exists():
            logger.warning(f"GDS 文件不存在，跳过备份: {gds_path}")
            return None

        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_path = self._backup_dir / f"pre_update_{ts}.gds"
        shutil.copy2(src, backup_path)
        logger.info(f"GDS 备份已保存: {backup_path}")
        return backup_path

    def restore_backup(self, backup_path: Path, target_path: str) -> bool:
        """从备份恢复 GDS 文件。

        Args:
            backup_path: 备份文件路径
            target_path: 恢复目标路径

        Returns:
            是否恢复成功
        """
        if not backup_path.exists():
            logger.warning(f"备份文件不存在: {backup_path}")
            return False

        shutil.copy2(backup_path, target_path)
        logger.info(f"已从备份恢复: {backup_path} → {target_path}")
        return True
