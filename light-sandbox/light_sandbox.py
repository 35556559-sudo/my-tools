# -*- coding: utf-8 -*-
"""
轻沙箱 LightSandbox v1.0
========================
Windows 应用隔离沙箱管理器（比虚拟机更轻量）

原理：不装虚拟机、不装驱动。每个沙箱 = 一个独立的 Windows 账户 + 一个独立的数据目录。
沙箱内的应用以该账户运行，其「文档 / AppData / 用户注册表(HKCU)」全部落在沙箱账户自己的
配置里，与主系统账户完全分开 → 同一软件（微信、豆包等）可以装多套、登不同账号。

配套文件：
  - PsExec64.exe   （微软官方工具，首次使用时自动下载，用于"以沙箱账户在当前桌面运行程序"）
  - light_sandbox_config.json （沙箱配置，自动生成）

用法：
  双击「启动沙箱.bat」或运行  python light_sandbox.py
  需要管理员权限（首次会弹 UAC 授权）。
"""
import os
import sys
import json
import re
import time
import secrets
import shutil
import shlex
import subprocess
import ctypes
import urllib.request
import threading

def _bootstrap_dirs():
    """区分两个目录：
    RESOURCE_DIR —— 程序自带的只读资源（ps1、图标等），打包后位于 PyInstaller 临时解压目录；
    APP_DIR      —— 可写、需持久化的工作目录（config、data、PsExec），打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        resource_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        app_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        resource_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir = resource_dir
    return app_dir, resource_dir


APP_DIR, RESOURCE_DIR = _bootstrap_dirs()
CONFIG_PATH = os.path.join(APP_DIR, "light_sandbox_config.json")
PSEXEC_PATH = os.path.join(APP_DIR, "PsExec64.exe")
PSEXEC_URL = "https://live.sysinternals.com/PsExec64.exe"
DEFAULT_ROOT = os.path.join(APP_DIR, "data")   # 沙箱数据总目录（默认在程序目录下的 data，可在配置文件中修改）
DEFAULT_PROFILE_ROOT = r"C:\Users"   # 沙箱账户配置目录：新账户首次登录由 Windows 自动在 C:\Users 下生成
PASSWORD_CHARS = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# ============================================================
# 一、基础工具
# ============================================================

def is_admin():
    """当前进程是否有管理员权限"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_elevated():
    """如果不是管理员，自动以管理员身份重启自己（弹 UAC）"""
    if is_admin():
        return True
    try:
        if getattr(sys, "frozen", False):
            # 打包后 sys.executable 就是 exe 本身，直接带参数重启
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable,
                " ".join(sys.argv[1:]), APP_DIR, 1)
        else:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable,
                '"{}" {}'.format(__file__, " ".join(sys.argv[1:])), APP_DIR, 1)
    except Exception:
        pass
    return False


def run_cmd(args, timeout=60):
    """运行命令并返回 (退出码, 输出文本)。args 用列表传参，不做 shell 解析，路径带空格也安全。
    统一加 CREATE_NO_WINDOW，避免 powershell/cmd/net 等弹出黑色/蓝色控制台窗口。"""
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           encoding="gbk", errors="replace", timeout=timeout,
                           creationflags=no_window)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return -1, "找不到命令: " + str(args[0])
    except subprocess.TimeoutExpired:
        return -2, "命令执行超时"


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("sandbox_root", DEFAULT_ROOT)
            cfg.setdefault("profile_root", DEFAULT_PROFILE_ROOT)
            cfg.setdefault("sandboxes", [])
            return cfg
        except Exception:
            pass
    return {"sandbox_root": DEFAULT_ROOT, "profile_root": DEFAULT_PROFILE_ROOT, "sandboxes": []}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_sandbox(cfg, name):
    for sb in cfg["sandboxes"]:
        if sb["name"] == name:
            return sb
    return None


def sandbox_dir(root, name):
    return os.path.join(root, name)


# ============================================================
# 二、PsExec 获取（微软官方工具，用于"以沙箱账户在当前桌面运行程序"）
# ============================================================

def ensure_psexec(progress=None):
    """确保 PsExec64.exe 存在，不存在则从微软官方源自动下载"""
    if os.path.exists(PSEXEC_PATH):
        return True
    if progress:
        progress("首次使用，正在下载微软官方 PsExec 工具…")
    try:
        req = urllib.request.Request(
            PSEXEC_URL, headers={"User-Agent": "Mozilla/5.0 LightSandbox/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if len(data) < 100_000:
            if progress:
                progress("PsExec 下载不完整，请检查网络后重试。")
            return False
        with open(PSEXEC_PATH, "wb") as f:
            f.write(data)
        if progress:
            progress("PsExec 下载完成。")
        return True
    except Exception as e:
        if progress:
            progress("PsExec 下载失败：{}".format(e))
        return False


def build_psexec_base(sb):
    """构造 psexec 基础参数：以沙箱账户、在当桌桌面、以管理员令牌(如适用)运行"""
    cmd = [PSEXEC_PATH, "-accepteula"]
    if sb.get("as_admin", True):
        cmd.append("-h")          # 以该账户的管理员令牌运行（沙箱账户默认是管理员成员）
    cmd += ["-i", "-d",            # 交互式桌面 + 不等待
            "-u", sb["account"],
            "-p", sb["password"],
            "-w", sb["dir"]]
    return cmd


# ============================================================
# 三、沙箱管理（账户隔离核心）
# ============================================================

NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
RESERVED = {"administrator", "admin", "guest", "defaultuser0", "sb", "system", "localservice", "networkservice"}


def validate_name(name):
    """沙箱名：1-16 位字母/数字/下划线（账户名规则限制，中文暂不支持做账户名）"""
    if not name:
        return "沙箱名不能为空"
    if not NAME_RE.match(name):
        return "沙箱名只能由 1-16 位字母、数字、下划线组成"
    if name.lower() in RESERVED:
        return "该名称被系统保留，请换一个"
    if name.lower().startswith("sb_"):
        return "沙箱名不要以 sb_ 开头（会自动加前缀）"
    return None


def gen_password(n=12):
    return "".join(secrets.choice(PASSWORD_CHARS) for _ in range(n))


def kill_account_processes(account):
    """结束某沙箱账户名下的所有进程。用 taskkill 按用户名过滤，比 CIM 遍历快得多。"""
    run_cmd(["taskkill", "/F", "/IM", "*", "/FI", "USERNAME eq {}".format(account)], timeout=15)


def setup_profile_on_drive(account, profile_root):
    """建账户后，直接在注册表把 profile 路径指向 <profile_root>\\<account>。
    关键：目标目录要创建出来但必须是空的（不要建 Desktop 等子目录），
    Windows 首次登录时会自己往里初始化 profile；如果目录里已有任何内容，
    Winlogon 会认为"不干净"而回退到 C 盘。
    返回 (ok, 目标目录或错误消息)。"""
    os.makedirs(profile_root, exist_ok=True)
    target = os.path.join(profile_root, account)
    # 创建空目录（如果已存在但非空，先清空，避免 Windows 回退）
    os.makedirs(target, exist_ok=True)

    # 1) 拿账户 SID
    code, out = run_cmd([
        "powershell", "-NoProfile", "-Command",
        "(New-Object System.Security.Principal.NTAccount('{}')).Translate([System.Security.Principal.SecurityIdentifier]).Value".format(account)
    ], timeout=30)
    sid = ""
    if out:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("S-1-"):
                sid = line
                break
    if not sid:
        return False, "无法获取账户 SID：{}".format((out or "").strip()[:120])

    # 2) 写注册表 ProfileList\<SID>\ProfileImagePath = target（REG_EXPAND_SZ）
    import winreg
    plist = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\{}".format(sid)
    try:
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, plist) as k:
            winreg.SetValueEx(k, "ProfileImagePath", 0, winreg.REG_EXPAND_SZ, target)
    except Exception as e:
        return False, "写注册表 ProfileImagePath 失败：{}".format(e)

    # 3) 给账户授权该目录完全控制（Windows 初始化 profile 时需要写权限）
    run_cmd(["icacls", target, "/grant", "{}:(OI)(CI)F".format(account)], timeout=30)

    return True, target


def relocate_profile(account, password, profile_root):
    """把 C:\\Users\\<账户> 整体迁到 <profile_root>\\<账户> 并在原地建目录联接。
    效果：程序看路径仍在 C 盘，实际数据物理在 <profile_root>，省 C 盘空间。
    返回 (ok, 提示消息, 目标目录)。流程：触发首次登录 → robocopy /MOVE → mklink /J。"""
    src = os.path.join("C:\\Users", account)
    try:
        os.makedirs(profile_root, exist_ok=True)
    except Exception:
        pass
    target = os.path.join(profile_root, account)

    # 已迁过（已有联接）直接返回
    if os.path.isdir(target) and os.path.exists(src):
        try:
            if os.path.islink(src):
                return True, "", target
        except Exception:
            pass

    # 1) 触发一次登录，让 Windows 生成资料目录（cmd 立即退出）
    if not os.path.isdir(src):
        run_cmd([PSEXEC_PATH, "-accepteula", "-h", "-u", account, "-p", password,
                 "cmd.exe", "/c", "exit"], timeout=60)
        for _ in range(30):
            if os.path.isdir(src):
                break
            time.sleep(1)
    if not os.path.isdir(src):
        return False, "未能生成账户资料目录（首登失败）", target
    time.sleep(3)   # 等 NTUSER.DAT 解锁

    # 2) robocopy 整体搬移（/MOVE：复制后删源；/B 备份模式可绕过注册表档案等锁；退出码 <8 都算成功）
    code, _ = run_cmd(["robocopy", src, target, "/E", "/MOVE", "/B",
                       "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1"], timeout=900)
    if code >= 8:
        # 可能是注册表档案被锁，等几秒重试一次
        time.sleep(5)
        code, _ = run_cmd(["robocopy", src, target, "/E", "/MOVE", "/B",
                           "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1"], timeout=900)
        if code >= 8:
            return False, "搬移资料失败（robocopy 码 {}）".format(code), target

    # 3) 清空源目录并建立联接
    shutil.rmtree(src, ignore_errors=True)
    try:
        os.rmdir(src)
    except OSError:
        pass
    code, out = run_cmd(["cmd", "/c", "mklink", "/J", src, target], timeout=30)
    if code == 0 and os.path.isdir(target) and os.path.isdir(src):
        return True, "", target
    return False, "联接创建失败：{}".format((out or "").strip()[:120]), target


def create_sandbox(name, as_admin=True):
    """创建沙箱：独立数据目录 + 独立 Windows 账户（默认管理员成员，方便安装软件）"""
    err = validate_name(name)
    if err:
        return False, err
    cfg = load_config()
    if get_sandbox(cfg, name):
        return False, "沙箱「{}」已存在".format(name)

    account = "sb_" + name
    password = gen_password()
    root = cfg["sandbox_root"]
    sdir = sandbox_dir(root, name)

    # 1) 建目录
    try:
        os.makedirs(sdir, exist_ok=True)
        for sub in ("apps", "Data", "Downloads", "Temp"):
            os.makedirs(os.path.join(sdir, sub), exist_ok=True)
    except Exception as e:
        return False, "创建沙箱目录失败：{}".format(e)

    # 2) 建账户
    code, out = run_cmd(["net", "user", account, password, "/add"], timeout=60)
    if code != 0:
        shutil.rmtree(sdir, ignore_errors=True)
        return False, "创建账户失败：{}".format(out.strip() or code)
    time.sleep(1)   # 等 SAM 状态落定，避免新账户立即使用时的竞态

    # 3) 加入管理员组（勾选"管理员账户"时）
    if as_admin:
        code, out = run_cmd(["net", "localgroup", "administrators", account, "/add"], timeout=60)
        if code != 0:
            run_cmd(["net", "user", account, "/delete"], timeout=60)
            shutil.rmtree(sdir, ignore_errors=True)
            return False, "加入管理员组失败：{}".format(out.strip() or code)

    # 4) 不做 profile 迁移：新账户首次登录时 Windows 自动在 C:\Users\<account> 生成，简单可靠
    # 5) 记入配置
    sb = {
        "name": name,
        "account": account,
        "password": password,
        "as_admin": as_admin,
        "dir": sdir,
        "profile_dir": "",
        "apps": [],
    }
    cfg["sandboxes"].append(sb)
    save_config(cfg)
    tip = "沙箱「{}」创建成功\n账户：{}\n数据目录：{}".format(name, account, sdir)
    return True, tip


def delete_sandbox(name):
    """删除沙箱：结束进程 → 拆联接/删资料 → 删账户 → 删数据目录"""
    cfg = load_config()
    sb = get_sandbox(cfg, name)
    if not sb:
        return False, "沙箱「{}」不存在".format(name)

    account = sb["account"]
    # 1) 结束该账户名下所有进程（否则资料文件被锁）
    kill_account_processes(account)
    time.sleep(2)

    # 2) 处理 C:\Users\<账户>：联接只拆链接；实体目录则递归删除
    profile = os.path.join("C:\\Users", account)
    if os.path.exists(profile):
        run_cmd(["cmd", "/c", "rmdir", profile], timeout=30)
        if os.path.exists(profile):
            for _ in range(3):
                shutil.rmtree(profile, ignore_errors=True)
                if not os.path.exists(profile):
                    break
                time.sleep(1)

    # 3) 通知系统清理该账户的配置注册（新方案下 profile 在 E 盘、未登录过，通常查不到；短超时，找不到就算了）
    try:
        ps = ("Get-CimInstance Win32_UserProfile -Filter \"LocalPath='{}'\" | "
              "Remove-CimInstance -ErrorAction SilentlyContinue".format(profile.replace("\\", "\\\\")))
        run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout=10)
    except Exception:
        pass
    prof_dir = sb.get("profile_dir")
    if prof_dir and os.path.isdir(prof_dir):
        shutil.rmtree(prof_dir, ignore_errors=True)

    # 4) 删除账户
    code, out = run_cmd(["net", "user", account, "/delete"], timeout=60)
    if code != 0:
        return False, "删除账户失败：{}".format(out.strip() or code)

    # 5) 删除沙箱数据目录
    shutil.rmtree(sb["dir"], ignore_errors=True)

    # 6) 更新配置
    cfg["sandboxes"] = [s for s in cfg["sandboxes"] if s["name"] != name]
    save_config(cfg)
    return True, "沙箱「{}」已删除（账户、资料、数据目录均已清理）".format(name)


# ============================================================
# 四、沙箱内运行应用
# ============================================================

def _require_sandbox(name):
    cfg = load_config()
    sb = get_sandbox(cfg, name)
    if not sb:
        return None, "沙箱「{}」不存在".format(name)
    return sb, None


def launch(sb, exe, args=None, progress=None):
    """以沙箱账户在桌面启动程序（安装程序 / 应用本体均可）"""
    if not os.path.isfile(exe):
        return False, "找不到程序：{}".format(exe)
    if not ensure_psexec(progress):
        return False, "PsExec 不可用，无法以沙箱账户启动程序"
    cmd = build_psexec_base(sb) + [exe]
    if args:
        if isinstance(args, str):
            cmd += shlex.split(args)
        else:
            cmd += list(args)
    code, out = run_cmd(cmd, timeout=60)
    # 说明：psexec 加 -d（不等待）时，返回码是"已启动进程的 PID"，而非 0；
    # 因此以输出中是否出现 "started on" 判定启动成功。
    if code != 0 and "started on" not in out.lower():
        return False, "启动失败（退出码 {}）：{}".format(code, out.strip() or "请确认账户/密码配置正常")
    return True, "已以「{}」账户启动：{}".format(sb["account"], os.path.basename(exe))


def add_app(sb, exe, alias=None):
    """把程序记入沙箱的应用列表（只登记，不启动）"""
    for app in sb["apps"]:
        if app["exe"].lower() == exe.lower():
            return False, "该程序已在列表中"
    if not alias:
        alias = os.path.splitext(os.path.basename(exe))[0]
    sb["apps"].append({"name": alias, "exe": exe})
    cfg = load_config()
    for s in cfg["sandboxes"]:
        if s["name"] == sb["name"]:
            s["apps"] = sb["apps"]
    save_config(cfg)
    return True, "已添加：{}".format(alias)


def remove_app(sb, index):
    if 0 <= index < len(sb["apps"]):
        del sb["apps"][index]
        cfg = load_config()
        for s in cfg["sandboxes"]:
            if s["name"] == sb["name"]:
                s["apps"] = sb["apps"]
        save_config(cfg)
        return True, "已移除"
    return False, "未选中有效条目"


def rename_app(sb, index, new_name):
    """修改某条程序的显示名（不影响 exe 路径），方便用中文/好记的名字查找。"""
    new_name = (new_name or "").strip()
    if not new_name:
        return False, "名字不能为空"
    if not (0 <= index < len(sb["apps"])):
        return False, "未选中有效条目"
    old_name = sb["apps"][index].get("name", "")
    if new_name == old_name:
        return True, "名字未改变"
    sb["apps"][index]["name"] = new_name
    cfg = load_config()
    for s in cfg["sandboxes"]:
        if s["name"] == sb["name"]:
            s["apps"] = sb["apps"]
    save_config(cfg)
    return True, old_name


def sync_desktop_shortcuts(sb):
    """把沙箱 apps 列表里登记的程序，自动在该沙箱账户的真实桌面（RDP 桌面版能看到的那个）
    生成/更新快捷方式。这样「添加程序」后不用手动建图标。
    返回 (ok, 已同步的名字列表)。"""
    profile_dir = sb.get("profile_dir", "")
    # 没做迁移时，profile 就在 C:\Users\<account>
    if not profile_dir:
        profile_dir = os.path.join("C:\\Users", sb["account"])
    if not os.path.isdir(profile_dir):
        # 首次登录前 C:\Users\<account> 还不存在，等登录后再同步
        return False, []
    desktop = os.path.join(profile_dir, "Desktop")
    if not os.path.isdir(desktop):
        return False, []
    created = []
    for app in sb.get("apps", []):
        exe = app["exe"]
        name = app.get("name") or os.path.splitext(os.path.basename(exe))[0]
        if not os.path.isfile(exe):
            continue
        lnk = os.path.join(desktop, name + ".lnk")
        workdir = os.path.dirname(exe)
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            "$sc = $ws.CreateShortcut('{lnk}'); "
            "$sc.TargetPath = '{exe}'; "
            "$sc.WorkingDirectory = '{wd}'; "
            "$sc.Description = '{nm} （沙箱）'; "
            "$sc.Save()"
        ).format(
            lnk=lnk.replace("'", "''"),
            exe=exe.replace("'", "''"),
            wd=workdir.replace("'", "''"),
            nm=name.replace("'", "''"),
        )
        run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout=30)
        created.append(name)
    # 清理：移除列表里没有、但桌面还留着的旧快捷方式（避免失效图标）
    valid_names = { (a.get("name") or os.path.splitext(os.path.basename(a["exe"]))[0])
                    for a in sb.get("apps", []) }
    try:
        for f in os.listdir(desktop):
            if f.lower().endswith(".lnk") and os.path.splitext(f)[0] not in valid_names:
                # 只删我们按规则生成的（名字即应用名），Edge 等系统自带不动
                pass
    except Exception:
        pass
    return True, created


# ============================================================
# 五、图形界面
# ============================================================

def gui_main():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print("本机缺少 tkinter，请安装 Python 时勾选 tcl/tk 组件。")
        return 1

    if not ensure_elevated():
        return 0   # 已触发 UAC 重启

    class App:
        def __init__(self, root):
            self.root = root
            self.cfg = load_config()
            self.current = None      # 当前选中的沙箱 dict
            root.title("轻沙箱 LightSandbox · 应用隔离沙箱")
            root.geometry("900x600")
            root.minsize(820, 540)

            # --- 左：沙箱列表 ---
            left = ttk.Frame(root, padding=10)
            left.pack(side="left", fill="y")
            ttk.Label(left, text="我的沙箱", font=("Microsoft YaHei", 11, "bold")).pack(anchor="w")
            self.listbox = tk.Listbox(left, width=24, height=16, font=("Microsoft YaHei", 10))
            self.listbox.pack(fill="y", expand=True, pady=6)
            self.listbox.bind("<<ListboxSelect>>", self.on_select)

            ttk.Label(left, text="新沙箱名称（英文/数字/下划线）", font=("Microsoft YaHei", 9)).pack(anchor="w")
            self.name_var = tk.StringVar()
            ttk.Entry(left, textvariable=self.name_var, width=26).pack(fill="x", pady=3)
            self.admin_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(left, text="沙箱账户设为管理员（默认，便于安装软件）",
                            variable=self.admin_var).pack(anchor="w", pady=2)
            ttk.Button(left, text="＋ 新建沙箱", command=self.do_create).pack(fill="x", pady=3)
            ttk.Button(left, text="－ 删除沙箱", command=self.do_delete).pack(fill="x", pady=3)

            # --- 右：沙箱详情 ---
            right = ttk.Frame(root, padding=10)
            right.pack(side="left", fill="both", expand=True)

            self.detail = ttk.LabelFrame(right, text="沙箱详情", padding=8)
            self.detail.pack(fill="x")
            self.detail_text = tk.Text(self.detail, height=5, font=("Consolas", 9), state="disabled")
            self.detail_text.pack(fill="x")

            apps_frame = ttk.LabelFrame(right, text="沙箱内应用（安装/启动）", padding=8)
            apps_frame.pack(fill="both", expand=True, pady=8)
            self.app_list = tk.Listbox(apps_frame, height=8, font=("Microsoft YaHei", 10))
            self.app_list.pack(side="left", fill="both", expand=True)
            btns = ttk.Frame(apps_frame)
            btns.pack(side="right", fill="y", padx=(8, 0))
            ttk.Button(btns, text="启动应用", command=self.do_launch, width=14).pack(pady=3)
            ttk.Button(btns, text="添加程序(不启动)", command=self.do_add, width=14).pack(pady=3)
            ttk.Button(btns, text="移除所选程序", command=self.do_remove, width=14).pack(pady=3)
            ttk.Button(btns, text="重命名程序", command=self.do_rename, width=14).pack(pady=3)
            ttk.Button(btns, text="安装应用…", command=self.do_install, width=14).pack(pady=3)
            ttk.Button(btns, text="打开桌面版", command=self.do_open_desktop, width=14).pack(pady=3)

            tools = ttk.LabelFrame(right, text="沙箱工具", padding=8)
            tools.pack(fill="x")
            ttk.Button(tools, text="打开沙箱目录", command=self.do_opendir).pack(side="left", padx=3)
            ttk.Button(tools, text="沙箱命令行 CMD", command=self.do_cmd).pack(side="left", padx=3)
            ttk.Button(tools, text="显示沙箱密码", command=self.do_showpass).pack(side="left", padx=3)
            ttk.Button(tools, text="刷新", command=self.refresh).pack(side="left", padx=3)

            # 代理控制区（tizi 翻墙沙箱用）
            proxy_frame = ttk.LabelFrame(right, text="网络代理", padding=8)
            proxy_frame.pack(fill="x", pady=8)
            self.proxy_status = tk.StringVar(value="代理模式")
            ttk.Label(proxy_frame, textvariable=self.proxy_status, foreground="#0066cc").pack(side="left", padx=3)
            ttk.Button(proxy_frame, text="代理端口设置", command=self.do_proxy_port).pack(side="left", padx=3)
            self.proxy_toggle_btn = ttk.Button(proxy_frame, text="切到直连", command=self.do_proxy_toggle)
            self.proxy_toggle_btn.pack(side="left", padx=3)

            # --- 底部状态与新手提示 ---
            self.status = tk.StringVar(value="正在初始化…")
            ttk.Label(root, textvariable=self.status, relief="sunken",
                      anchor="w", padding=4).pack(side="bottom", fill="x")
            hint = ("使用三步：① 新建沙箱 → ② 「安装应用」选安装包（安装时把目录粘到 沙箱目录\\apps 下，路径已自动复制）"
                    "→ ③ 「启动应用」选主程序。\n"
                    "更省空间的用法：不重复安装，直接「添加程序」指向本机已装的主程序（如 D:\\Program Files\\Tencent\\Weixin\\Weixin.exe），"
                    "以沙箱账户启动即独立登录。数据/登录态与主系统完全分开。")
            ttk.Label(root, text=hint, foreground="#555", padding=6).pack(side="bottom", fill="x")

            self.refresh()
            self.refresh_status()

        # ---------- 界面刷新 ----------
        def refresh_status(self):
            if not is_admin():
                self.status.set("当前未以管理员运行——新建/删除沙箱需要管理员权限，请用「启动沙箱.bat」启动。")
            elif os.path.exists(PSEXEC_PATH):
                self.status.set("就绪：管理员权限 ✓   PsExec ✓  沙箱 {} 个".format(len(self.cfg["sandboxes"])))
            else:
                self.status.set("就绪：管理员权限 ✓   正在检查/下载 PsExec（首次使用自动下载）…")
                threading.Thread(target=self._ensure_psexec_bg, daemon=True).start()

        def _ensure_psexec_bg(self):
            def cb(msg):
                self.status.set(msg)
            ok = ensure_psexec(cb)
            self.root.after(0, lambda: self.refresh_status() if ok else None)

        def refresh(self):
            self.cfg = load_config()
            self.listbox.delete(0, "end")
            for sb in self.cfg["sandboxes"]:
                self.listbox.insert("end", sb["name"])
            if self.current and not get_sandbox(self.cfg, self.current["name"]):
                self.current = None
            if self.current is None and self.cfg["sandboxes"]:
                self.current = self.cfg["sandboxes"][0]
            self.show_detail()

        def on_select(self, _evt=None):
            sel = self.listbox.curselection()
            if sel:
                name = self.listbox.get(sel[0])
                self.current = get_sandbox(self.cfg, name)
                self.show_detail()

        def show_detail(self):
            if self.current is None:
                self.set_detail("（左侧新建一个沙箱后，这里会显示详情）")
                self.app_list.delete(0, "end")
                return
            sb = self.current
            admin_txt = "管理员成员（可装软件）" if sb.get("as_admin", True) else "标准用户"
            self.set_detail(
                "沙箱名   ：{}\n账户     ：{}\n权限     ：{}\n数据目录 ：{}\n"
                "密码     ：{}（用于账户模式启动，一般无需手动输入）".format(
                    sb["name"], sb["account"], admin_txt, sb["dir"], sb["password"]))
            self.app_list.delete(0, "end")
            for app in sb["apps"]:
                self.app_list.insert("end", "{}  →  {}".format(app["name"], os.path.basename(app["exe"])))
            # 代理状态显示
            port = sb.get("proxy_port", 7897)
            enabled = sb.get("proxy_enabled", True)
            if enabled:
                self.proxy_status.set("代理模式：127.0.0.1:{}".format(port))
                self.proxy_toggle_btn.config(text="切到直连")
            else:
                self.proxy_status.set("直连模式：本机网络")
                self.proxy_toggle_btn.config(text="切回代理")

        def set_detail(self, text):
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", text)
            self.detail_text.config(state="disabled")

        # ---------- 沙箱操作 ----------
        def do_create(self):
            name = self.name_var.get().strip()
            if not name:
                messagebox.showwarning("新建沙箱", "请先输入新沙箱名称")
                return
            # 放到后台线程跑，避免建账户+首次登录+robocopy 迁移配置目录时 GUI 卡死（AppHang）
            self.status.set("正在创建沙箱「{}」：建账户、首次登录、迁移配置目录到 E 盘，请耐心等待（约 1~2 分钟）…".format(name))
            self.root.update_idletasks()
            as_admin = self.admin_var.get()

            def worker():
                try:
                    ok, msg = create_sandbox(name, as_admin=as_admin)
                except Exception as e:
                    import traceback
                    ok, msg = False, "创建过程中发生异常：{}\n\n{}".format(e, traceback.format_exc())
                def done():
                    messagebox.showinfo("新建沙箱" if ok else "无法新建", msg)
                    if ok:
                        self.name_var.set("")
                        self.refresh()
                        for i, sb in enumerate(self.cfg["sandboxes"]):
                            if sb["name"] == name:
                                self.listbox.selection_clear(0, "end")
                                self.listbox.selection_set(i)
                                self.current = sb
                                self.show_detail()
                                break
                    self.refresh_status()
                self.root.after(0, done)

            threading.Thread(target=worker, daemon=True).start()

        def do_delete(self):
            if self.current is None:
                messagebox.showwarning("删除沙箱", "请先在左侧选中要删除的沙箱")
                return
            name = self.current["name"]
            if not messagebox.askyesno("删除沙箱",
                                       "将删除沙箱「{}」的账户、该账户的全部资料与数据目录，\n"
                                       "沙箱内安装的软件将不可恢复。确定删除？".format(name)):
                return
            self.status.set("正在删除沙箱「{}」：结束进程、清理资料与目录，请稍候…".format(name))
            self.root.update_idletasks()

            def worker():
                try:
                    ok, msg = delete_sandbox(name)
                except Exception as e:
                    import traceback
                    ok, msg = False, "删除过程中发生异常：{}\n\n{}".format(e, traceback.format_exc())
                def done():
                    messagebox.showinfo("删除沙箱" if ok else "无法删除", msg)
                    self.refresh()
                    self.refresh_status()
                self.root.after(0, done)

            threading.Thread(target=worker, daemon=True).start()

        def _selected_sandbox(self):
            if self.current is None:
                messagebox.showwarning("提示", "请先在左侧选中一个沙箱")
                return None
            return self.current

        def do_install(self):
            sb = self._selected_sandbox()
            if not sb:
                return
            exe = filedialog.askopenfilename(
                title="选择要安装到沙箱的安装包（.exe / .msi）",
                filetypes=[("安装程序", "*.exe *.msi"), ("所有文件", "*.*")])
            if not exe:
                return
            # 自动准备沙箱 apps 目录：建好、复制路径到剪贴板、并打开文件夹
            apps_dir = os.path.join(sb["dir"], "apps")
            os.makedirs(apps_dir, exist_ok=True)
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(apps_dir)
            except Exception:
                pass
            subprocess.Popen(["explorer", apps_dir])
            self.status.set("正在以「{}」账户启动安装程序…".format(sb["account"]))
            self.root.update_idletasks()
            ok, msg = launch(sb, exe, progress=lambda m: self.status.set(m))
            if ok:
                tip = ("安装已启动。安装时把「安装路径」粘贴/选择到：\n"
                       "{}\n（路径已自动复制到剪贴板，对应的文件夹已打开）\n\n"
                       "注意：不要装到系统已有的安装目录（如 D:\\Program Files），"
                       "否则会覆盖主系统的同名软件。".format(apps_dir))
            else:
                tip = msg
            messagebox.showinfo("安装应用" if ok else "启动安装失败", tip)
            self.refresh_status()

        def do_open_desktop(self):
            """打开当前沙箱的完整 RDP 桌面窗口（可拖拽缩放，F11 真全屏，等比不变形）"""
            sb = self._selected_sandbox()
            if not sb:
                return
            ps1 = os.path.join(RESOURCE_DIR, "沙箱桌面客户端.ps1")
            if not os.path.isfile(ps1):
                messagebox.showerror("打开桌面版", "找不到客户端脚本：\n{}".format(ps1))
                return
            # 打开前先同步一次（如果 profile 已存在）
            sync_desktop_shortcuts(sb)
            # 无控制台黑窗地启动；ps1 内部的 WinForms 桌面窗口照常显示
            no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                subprocess.Popen(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", ps1,
                     "-UserName", sb["account"],
                     "-Password", sb["password"]],
                    cwd=APP_DIR, creationflags=no_window)
            except Exception as e:
                messagebox.showerror("打开桌面版", "启动失败：{}".format(e))
                return
            self.status.set("正在打开「{}」的完整桌面版窗口…（F11 真全屏，可拖拽缩放，等比不变形）".format(sb["name"]))
            # 首次登录时 Windows 会在 E 盘创建 profile；等 15 秒让它建完，再同步一次图标
            def delayed_sync():
                sync_desktop_shortcuts(sb)
                self.refresh()
            self.root.after(15000, delayed_sync)

        def do_launch(self):
            sb = self._selected_sandbox()
            if not sb:
                return
            sel = self.app_list.curselection()
            if sel:
                app = sb["apps"][sel[0]]
                ok, msg = launch(sb, app["exe"], args=app.get("args"), progress=lambda m: self.status.set(m))
                if ok:
                    self.status.set(msg)
                else:
                    messagebox.showerror("启动失败", msg)
            else:
                exe = filedialog.askopenfilename(
                    title="选择沙箱里已安装的程序主程序（将记住到应用列表）",
                    filetypes=[("程序", "*.exe"), ("所有文件", "*.*")])
                if not exe:
                    return
                ok, msg = launch(sb, exe, progress=lambda m: self.status.set(m))
                if ok:
                    add_app(sb, exe)
                    self.refresh()
                    self.status.set(msg)
                else:
                    messagebox.showerror("启动失败", msg)
            self.refresh_status()

        def do_add(self):
            sb = self._selected_sandbox()
            if not sb:
                return
            exe = filedialog.askopenfilename(title="选择程序主程序",
                                             filetypes=[("程序", "*.exe"), ("所有文件", "*.*")])
            if not exe:
                return
            ok, msg = add_app(sb, exe)
            if ok:
                sync_desktop_shortcuts(sb)
                msg += "\n已自动在沙箱桌面生成该程序图标（打开「桌面版」即可看到）。"
            messagebox.showinfo("添加程序" if ok else "无法添加", msg)
            self.refresh()

        def do_remove(self):
            sb = self._selected_sandbox()
            if not sb:
                return
            sel = self.app_list.curselection()
            if not sel:
                messagebox.showwarning("移除程序", "请先在列表中选择要移除的程序")
                return
            ok, msg = remove_app(sb, sel[0])
            messagebox.showinfo("移除程序" if ok else "无法移除", msg)
            self.refresh()

        def do_rename(self):
            from tkinter import simpledialog
            sb = self._selected_sandbox()
            if not sb:
                return
            sel = self.app_list.curselection()
            if not sel:
                messagebox.showwarning("重命名程序", "请先在列表中选择要改名的程序")
                return
            idx = sel[0]
            old_name = sb["apps"][idx].get("name", "")
            new_name = simpledialog.askstring("重命名程序",
                                              "给这个程序起个好认的名字（可填中文）：",
                                              initialvalue=old_name, parent=self.root)
            if new_name is None:
                return
            ok, result = rename_app(sb, idx, new_name)
            if not ok:
                messagebox.showwarning("重命名程序", result)
                return
            # 同步桌面快捷方式：删掉旧名字的 .lnk，再按新名字生成
            profile_dir = sb.get("profile_dir", "") or os.path.join("C:\\Users", sb["account"])
            desktop = os.path.join(profile_dir, "Desktop")
            old_lnk = os.path.join(desktop, (result or "") + ".lnk")
            if os.path.isfile(old_lnk):
                try:
                    os.remove(old_lnk)
                except OSError:
                    pass
            sync_desktop_shortcuts(sb)
            self.refresh()
            messagebox.showinfo("重命名程序", "已改名为：{}".format(new_name.strip()))

        def do_opendir(self):
            sb = self._selected_sandbox()
            if not sb:
                return
            os.makedirs(sb["dir"], exist_ok=True)
            subprocess.Popen(["explorer", sb["dir"]])

        def do_cmd(self):
            sb = self._selected_sandbox()
            if not sb:
                return
            if not ensure_psexec(lambda m: self.status.set(m)):
                messagebox.showerror("沙箱 CMD", "PsExec 不可用")
                return
            cmd = build_psexec_base(sb) + ["cmd.exe", "/k", "title", "沙箱 CMD - {}".format(sb["name"])]
            code, out = run_cmd(cmd, timeout=30)
            if code != 0:
                messagebox.showerror("沙箱 CMD", out.strip() or "启动失败")
            self.refresh_status()

        def do_showpass(self):
            sb = self._selected_sandbox()
            if not sb:
                return
            messagebox.showinfo("沙箱账户密码",
                                "账户：{}\n密码：{}\n（密码仅用于以账户模式启动，一般无需使用）".format(
                                    sb["account"], sb["password"]))

        # ---------- 代理控制 ----------
        def _update_app_proxy_args(self, sb):
            """根据 sb 的 proxy_port / proxy_enabled 更新所有应用的 args 里的 --proxy-server"""
            port = sb.get("proxy_port", 7897)
            enabled = sb.get("proxy_enabled", True)
            proxy_flag = "--proxy-server=http://127.0.0.1:{}".format(port)
            for app in sb["apps"]:
                args = app.get("args", "")
                if not args:
                    continue
                # 先去掉旧的 --proxy-server=...
                parts = shlex.split(args) if args else []
                parts = [p for p in parts if not p.startswith("--proxy-server=")]
                if enabled:
                    # 插到最前面
                    parts.insert(0, proxy_flag)
                app["args"] = " ".join('"{}"'.format(p) if " " in p else p for p in parts)
            # 同步更新 Firefox 的 user.js（如果有 Firefox）
            ff_dir = None
            for app in sb["apps"]:
                if "firefox" in app.get("name", "").lower() and app.get("args"):
                    m = re.search(r'-profile\s+"?([^"\s]+)"?', app["args"])
                    if m:
                        ff_dir = m.group(1)
                        break
            if ff_dir:
                try:
                    os.makedirs(ff_dir, exist_ok=True)
                    if enabled:
                        user_js = (
                            'user_pref("network.proxy.type", 1);\n'
                            'user_pref("network.proxy.http", "127.0.0.1");\n'
                            'user_pref("network.proxy.http_port", {});\n'
                            'user_pref("network.proxy.ssl", "127.0.0.1");\n'
                            'user_pref("network.proxy.ssl_port", {});\n'
                            'user_pref("network.proxy.socks", "127.0.0.1");\n'
                            'user_pref("network.proxy.socks_port", {});\n'
                            'user_pref("network.proxy.socks_remote_dns", true);\n'
                            'user_pref("network.proxy.no_proxies_on", "");\n'.format(port, port, port))
                    else:
                        user_js = 'user_pref("network.proxy.type", 0);\n'
                    with open(os.path.join(ff_dir, "user.js"), "w", encoding="utf-8") as f:
                        f.write(user_js)
                except Exception:
                    pass
            # 保存到 config
            cfg = load_config()
            for s in cfg["sandboxes"]:
                if s["name"] == sb["name"]:
                    s["apps"] = sb["apps"]
                    s["proxy_port"] = port
                    s["proxy_enabled"] = enabled
            save_config(cfg)

        def do_proxy_port(self):
            sb = self._selected_sandbox()
            if not sb:
                return
            current_port = sb.get("proxy_port", 7897)
            from tkinter import simpledialog
            new_port = simpledialog.askstring("代理端口设置",
                "输入代理端口号（当前：{}）：".format(current_port),
                initialvalue=str(current_port), parent=self.root)
            if new_port is None:
                return
            new_port = new_port.strip()
            if not new_port.isdigit():
                messagebox.showerror("代理端口", "端口号必须是数字")
                return
            sb["proxy_port"] = int(new_port)
            self._update_app_proxy_args(sb)
            self.refresh()
            self.status.set("代理端口已改为 {}".format(new_port))

        def do_proxy_toggle(self):
            sb = self._selected_sandbox()
            if not sb:
                return
            current = sb.get("proxy_enabled", True)
            if current:
                sb["proxy_enabled"] = False
                self.status.set("已切换到直连模式（本机网络）")
            else:
                sb["proxy_enabled"] = True
                self.status.set("已切换到代理模式")
            self._update_app_proxy_args(sb)
            self.refresh()

    # 设置任务栏应用标识（让任务栏显示自定义图标，而不是 pythonw 默认图标）
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Doubao.LightSandbox")
    except Exception:
        pass

    root = tk.Tk()
    # 设置窗口图标
    _icon = os.path.join(RESOURCE_DIR, "sandbox.ico")
    if os.path.isfile(_icon):
        try:
            root.iconbitmap(_icon)
        except Exception:
            pass
    App(root)

    # 冒烟测试模式：自动关闭（用于开发自检）
    if "--smoke" in sys.argv:
        root.after(1200, root.destroy)

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(gui_main())
