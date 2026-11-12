# -*- coding: utf-8 -*-
"""轻沙箱（类虚拟机）自检脚本（临时，测完删除）"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import light_sandbox as ls

PASS = []
FAIL = []

def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [FAIL] ") + label + ("  | " + extra if extra else ""))

print("== 1. 权限 ==")
check("当前为管理员", ls.is_admin())

print("== 2. PsExec 下载 ==")
ok = ls.ensure_psexec(progress=lambda m: print("  ...", m))
check("PsExec 就绪", ok and os.path.exists(ls.PSEXEC_PATH),
      ls.PSEXEC_PATH if os.path.exists(ls.PSEXEC_PATH) else "")

print("== 3. 创建测试沙箱 sbtest ==")
cfg = ls.load_config()
if ls.get_sandbox(cfg, "sbtest"):
    ls.delete_sandbox("sbtest")
ok, msg = ls.create_sandbox("sbtest", as_admin=True)
check("创建沙箱", ok, msg)
sb = ls.get_sandbox(ls.load_config(), "sbtest")
check("账户已建", sb is not None and sb["account"] == "sb_sbtest")
check("数据目录已建", sb is not None and os.path.isdir(sb["dir"]),
      sb["dir"] if sb else "")
code, out = ls.run_cmd(["net", "localgroup", "administrators"])
check("账户在管理员组", sb is not None and sb["account"] in out)

print("== 4. 以沙箱账户启动记事本 ==")
ok, msg = ls.launch(sb, r"C:\Windows\System32\notepad.exe")
check("启动命令成功", ok, msg)
time.sleep(4)

code, out = ls.run_cmd(["tasklist", "/v", "/fo", "csv"])
notepad_lines = [ln for ln in out.splitlines() if "notepad.exe" in ln.lower()]
sb_lines = [ln for ln in notepad_lines if sb["account"] in ln]
print("  notepad 进程数:", len(notepad_lines), "| 归属沙箱账户的进程数:", len(sb_lines))
check("记事本以沙箱账户运行", len(sb_lines) >= 1, (sb_lines[0][:120] if sb_lines else ""))
check("沙箱账户用户资料已生成", os.path.isdir(r"C:\Users\sb_sbtest"))

# 只结束属于沙箱账户的记事本
for ln in sb_lines:
    try:
        pid = ln.split('","')[1]
        ls.run_cmd(["taskkill", "/pid", pid, "/f"])
    except Exception:
        pass
time.sleep(1)

print("== 5. 删除沙箱并验证清理 ==")
ok, msg = ls.delete_sandbox("sbtest")
check("删除沙箱", ok, msg)
code, _ = ls.run_cmd(["net", "user", "sb_sbtest"])
check("账户已删除", code != 0)
check("数据目录已删除", not os.path.exists(r"C:\Sandbox\sbtest"))
check("用户资料已删除", not os.path.exists(r"C:\Users\sb_sbtest"))

print()
print("通过 {} 项 / 失败 {} 项".format(len(PASS), len(FAIL)))
if FAIL:
    print("失败项：", FAIL)
    sys.exit(1)
print("ALL PASS")
