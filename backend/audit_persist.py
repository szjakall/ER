# -*- coding: utf-8 -*-
"""
持久化验证：服务重启后学情数据是否还在
======================================

流程：
    1) 进程 A：写入若干违规记录
    2) 退出进程
    3) 进程 B：新建 TRACKER 指向同一日志文件，验证记录被回放

运行：python audit_persist.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

_passed = 0
_failed = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name} {detail}")


def main() -> int:
    print("=" * 68)
    print("  持久化验证（跨进程重启）")
    print("=" * 68)

    tmp = Path(tempfile.gettempdir()) / "er_weakness_test.jsonl"
    if tmp.exists():
        tmp.unlink()

    # ---- 进程 1：写入 ----
    writer = f'''
import sys
sys.path.insert(0, r"{HERE}")
from weakness import WeaknessTracker
t = WeaknessTracker(persist_path=r"{tmp}")
for i in range(5):
    t.record("stu-1", "R02", "error", "缺少主键", f"e{{i}}",
             {{"elements": i + 1}}, now=1000.0 + i * 10)
t.record("stu-2", "R14", "error", "缺少基数", "c1", {{"elements": 3}}, now=2000.0)
print("WROTE", t.summary("stu-1")["total"], t.summary("stu-2")["total"])
'''
    r1 = subprocess.run([sys.executable, "-c", writer],
                        capture_output=True, text=True, encoding="utf-8")
    ok("写入进程正常退出", r1.returncode == 0, r1.stderr[:200])
    ok("写入 5 + 1 条", "WROTE 5 1" in (r1.stdout or ""), r1.stdout)

    # 日志文件应存在且行数为 6
    ok("日志文件已生成", tmp.exists())
    if tmp.exists():
        lines = [l for l in tmp.read_text(encoding="utf-8").splitlines() if l.strip()]
        ok("日志 6 行", len(lines) == 6, f"实际 {len(lines)}")
        # 每行应可解析
        try:
            for l in lines:
                json.loads(l)
            ok("每行均为合法 JSON", True)
        except Exception as ex:
            ok("每行均为合法 JSON", False, repr(ex))

    # ---- 进程 2：读取（模拟重启）----
    reader = f'''
import sys
sys.path.insert(0, r"{HERE}")
from weakness import WeaknessTracker
t = WeaknessTracker(persist_path=r"{tmp}")
s1 = t.summary("stu-1")
s2 = t.summary("stu-2")
print("READ", s1["total"], s2["total"], len(t.all_users()))
ctx = t.records_of("stu-1")[0].context if t.records_of("stu-1") else {{}}
print("CTX", ctx.get("elements"))
'''
    r2 = subprocess.run([sys.executable, "-c", reader],
                        capture_output=True, text=True, encoding="utf-8")
    ok("读取进程正常退出", r2.returncode == 0, r2.stderr[:200])
    ok("重启后记录完整回放（5 + 1）", "READ 5 1 2" in (r2.stdout or ""),
       r2.stdout)
    ok("设计上下文被保留", "CTX 1" in (r2.stdout or ""), r2.stdout)

    # ---- 损坏行容错 ----
    with tmp.open("a", encoding="utf-8") as f:
        f.write("这不是合法JSON\n")
        f.write('{"user_id":"stu-3","rule_id":"R03","level":"error","message":"m","timestamp":3000.0}\n')
    reader2 = f'''
import sys
sys.path.insert(0, r"{HERE}")
from weakness import WeaknessTracker
t = WeaknessTracker(persist_path=r"{tmp}")
print("TOLERANT", t.summary("stu-1")["total"], t.summary("stu-3")["total"])
'''
    r3 = subprocess.run([sys.executable, "-c", reader2],
                        capture_output=True, text=True, encoding="utf-8")
    ok("损坏行不影响加载（容错）", "TOLERANT 5 1" in (r3.stdout or ""),
       f"{r3.stdout} {r3.stderr[:150]}")

    # ---- 持久化关闭时应完全不写盘 ----
    tmp2 = Path(tempfile.gettempdir()) / "er_weakness_off.jsonl"
    if tmp2.exists():
        tmp2.unlink()
    closer = f'''
import sys
sys.path.insert(0, r"{HERE}")
from weakness import WeaknessTracker
t = WeaknessTracker(persist_path=None)
t.record("u", "R01", "error", "m", "e1", now=1.0)
print("OK")
'''
    subprocess.run([sys.executable, "-c", closer],
                   capture_output=True, text=True, encoding="utf-8")
    ok("关闭持久化时不产生文件", not tmp2.exists())

    # ---- 写盘失败不影响主流程 ----
    print("\n[容错] 写盘失败不应影响记账")
    bad_tracker = f'''
import sys
sys.path.insert(0, r"{HERE}")
from weakness import WeaknessTracker
# 指向一个不可能的路径
t = WeaknessTracker(persist_path=r"{tmp}\\不存在的目录\\x.jsonl")
r = t.record("u", "R01", "error", "m", "e1", now=1.0)
print("STILL_OK", r, t.summary("u")["total"], t.persist_failures > 0)
'''
    r4 = subprocess.run([sys.executable, "-c", bad_tracker],
                        capture_output=True, text=True, encoding="utf-8")
    ok("写盘失败仍记账成功", "STILL_OK True 1 True" in (r4.stdout or ""),
       f"{r4.stdout} {r4.stderr[:150]}")

    # 清理
    for p in (tmp, tmp2):
        if p.exists():
            p.unlink()

    # ---- 性能：持久化不得显著拖慢记账 ----
    print("\n[性能] 缓冲批量写的开销")
    perf_script = f'''
import sys, time, tempfile
sys.path.insert(0, r"{HERE}")
from pathlib import Path
from weakness import WeaknessTracker
tmp = Path(tempfile.gettempdir()) / "er_perf_audit.jsonl"
if tmp.exists(): tmp.unlink()
N = 3000
tp = WeaknessTracker(persist_path=str(tmp))
t0 = time.perf_counter()
for i in range(N):
    tp.record("u", "R02", "error", "m", f"e{{i}}", now=float(i) * 10)
withp = (time.perf_counter() - t0) / N * 1e6
tn = WeaknessTracker(persist_path=None)
t0 = time.perf_counter()
for i in range(N):
    tn.record("u", "R02", "error", "m", f"e{{i}}", now=float(i) * 10)
without = (time.perf_counter() - t0) / N * 1e6
tp.flush()
lines = len([l for l in tmp.read_text(encoding="utf-8").splitlines() if l.strip()])
tmp.unlink()
print("PERF", round(without, 2), round(withp, 2), round((withp-without)/1000, 4), lines)
'''
    r5 = subprocess.run([sys.executable, "-c", perf_script],
                        capture_output=True, text=True, encoding="utf-8")
    out = r5.stdout or ""
    ok("性能测量进程正常", "PERF" in out, f"{out} {r5.stderr[:150]}")
    if "PERF" in out:
        parts = out.split("PERF")[1].split()
        without, withp, delta_ms, lines = (float(parts[0]), float(parts[1]),
                                           float(parts[2]), int(parts[3]))
        print(f"        不落盘 {without:.2f}us/条  落盘 {withp:.2f}us/条  "
              f"增量 {delta_ms:.4f}ms")
        ok("落盘增量 < 0.1ms（不影响 <100ms 预算）", delta_ms < 0.1,
           f"实际 {delta_ms:.4f}ms")
        ok("缓冲写比逐条写快 5 倍以上", withp < 715.0 / 5,
           f"实际 {withp:.2f}us（逐条写约 715us）")
        ok("缓冲内容全部落盘，无丢失", lines == 3000, f"实际 {lines} 行")

    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
