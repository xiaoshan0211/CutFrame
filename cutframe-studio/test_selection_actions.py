"""使用真实前端处理函数复测手选、历史批次与任务进度显示。"""
from pathlib import Path
import subprocess
import unittest
import sys
import tempfile

class SelectionActionsTest(unittest.TestCase):
    def test_selection_actions(self):
        subprocess.run(['node', str(Path(__file__).with_name('test_selection_actions.cjs'))], check=True)

    def test_member_build(self):
        studio = Path(__file__).resolve().parent
        builder = studio.parent / '修订产出/镜序迁移暂存/portal-fix/install_member_ui.py'
        if not builder.is_file():
            self.skipTest('独立运行库未配置成员端部署工具')
        with tempfile.TemporaryDirectory(prefix='member-selection-') as folder:
            subprocess.run([sys.executable, str(builder), str(studio), folder], check=True)
            subprocess.run(['node', str(studio / 'test_selection_actions.cjs'), folder], check=True)
