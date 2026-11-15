# -*- coding: utf-8 -*-
"""验证：JSONL 半行损坏后追加，是否粘行丢数据。"""
import os
os.environ.setdefault("ER_TESTING", "1")

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
tmp = Path(tempfile.gettempdir()) / "half_line_test.jsonl"
if tmp.exists():
    tmp.unlink()

WRITER = f'''
import sys
sys.path.insert(0, r"{HERE}")
from weakness import WeaknessTracker
t = WeaknessTracker(persist_path=r"{tmp}")
t.record("S1", "R02", "error", "m", "e1", now=1.0)
t.record("S1", "R02", "error", "m", "e2", now=2.0)
t.flush()
# 模拟崩溃：写一半就死（无换行符）
with open(r"{tmp}", "a", encoding="utf-8") as f:
    f.write("{{" + '"user_id":"S1"')
'''

READER = f'''
import sys
sys.path.insert(0, r"{HERE}")
from weakness import WeaknessTracker
t = WeaknessTracker(persist_path=r"{tmp}")
print("REPLAY", t.record_count("S1"))
t.record("S1", "R02", "error", "m", "e3", now=3.0)
t.flush()
'''

FINAL = f'''
import sys
sys.path.insert(0, r"{HERE}")
from weakness import WeaknessTracker
t = WeaknessTracker(persist_path=r"{tmp}")
print("FINAL", t.record_count("S1"), "failures=", t.persist_failures)
'''

print("=== 进程1：写 2 条 + 半行崩溃 ===")
r1 = subprocess.run([sys.executable, "-c", WRITER], capture_output=True, text=True)
print("  退出码:", r1.returncode)

lines = [l for l in tmp.read_text(encoding="utf-8").split("\n") if l != ""]
# 注意：半行后面没有换行，split("\n") 时它就在最后一行
print(f"  文件共 {len(lines)} 段:")
for i, line in enumerate(lines):
    try:
        json.loads(line)
        ok = "可解析"
    except Exception:
        ok = "半行/损坏"
    print(f"    段{i+1}: [{ok}] {line[:55]}")

print()
print("=== 进程2：重启回放 + 继续追加 ===")
r2 = subprocess.run([sys.executable, "-c", READER], capture_output=True, text=True)
print(" ", (r2.stdout or "").strip(), (r2.stderr or "")[:100])

print()
print("=== 进程3：最终回放（检查粘行后果）===")
r3 = subprocess.run([sys.executable, "-c", FINAL], capture_output=True, text=True)
print(" ", (r3.stdout or "").strip(), (r3.stderr or "")[:100])

lines = [l for l in tmp.read_text(encoding="utf-8").split("\n") if l != ""]
print(f"  最终文件 {len(lines)} 段:")
lost = 0
bad_tail = False
for i, line in enumerate(lines):
    try:
        d = json.loads(line)
        ok = f"OK user={d.get('user_id')}"
        if d.get("element_id") == "e3":
            ok += " (e3 已保留)"
    except Exception:
        ok = "损坏(不可解析)"
        lost += 1
        # 半行（模拟崩溃残段）应独立且不含新数据
        if "user_id\":\"S1\"{" in line or '"user_id":"S1"{' in line:
            bad_tail = True
    print(f"    段{i+1}: [{ok}] {line[:55]}")
print()
print(f"结论：崩溃半行已隔离；损坏段数={lost}（应为 1，即半行本身）")
print(f"关键断言：e3 保留 = {r3.stdout and 'FINAL 3' in r3.stdout}"
      f"；新数据与半行粘连 = {bad_tail}（应为 False）")

tmp.unlink()
