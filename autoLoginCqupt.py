# Copyright [2025] [依然安然]
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
校园网自动登录工具 (autoLoginCqupt)
功能：自动检测校园网连接状态，断开时自动重连，支持多运营商/多UA模式
维护：优化代码结构 | 日志自动清理 | 界面字体标准化 | 注释工程化
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests
import socket
import time
import logging
import threading
import re
import random
from base64 import b64decode
import json
import os
import traceback
import winsound
from typing import Optional, Tuple
import sys
# 替换plyer，使用Windows原生通知（打包后稳定）
from win10toast import ToastNotifier

# ===================== 核心修复：路径区分（资源文件vs持久化文件）=====================
def get_resource_path(relative_path):
    """获取打包后资源文件（图标）的路径（临时目录）"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def get_persist_path(relative_path):
    """获取持久化文件（配置/日志）的路径（exe所在目录）"""
    # 打包后：获取exe所在目录
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
    # 打包前：获取脚本所在目录
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(exe_dir, relative_path)

# ===================== 全局常量配置（工程化拆分）=====================
# 持久化文件路径（配置/日志，保存在exe目录）
CONFIG_FILE = get_persist_path("config.txt")
LOG_FILE = get_persist_path("network_log.txt")
# 日志清理阈值（单位：MB）
LOG_CLEAN_THRESHOLD = 5  # 日志文件超过5MB自动清理
# 网络配置
HOST = "192.168.200.2:801"
REFERER = "http://192.168.200.2/"
PORTAL = "http://192.168.200.2:801/eportal"
# 重连策略配置
RECONNECT_INTERVALS = [10, 30, 60, 180, 300]  # 重连间隔（秒）
CHECK_INTERVAL = 60  # 已登录状态检查间隔（秒）
FAIL_THRESHOLD = 5   # 连续失败阈值
# 系统通知图标配置（资源文件，临时目录）
ICON_CONFIG = {
    "already": get_resource_path(os.path.join("ico", "Tips.ico")),
    "success": get_resource_path(os.path.join("ico", "Check.ico")),
    "fail": get_resource_path(os.path.join("ico", "Cross.ico")),
    "unknown": get_resource_path(os.path.join("ico", "Questionmark.ico"))
}
# UA池配置
UA_POOL = {
    "android-chrome": "Mozilla/5.0 (Linux; Android 12; Pixel 6 Build/SD1A.210817.023; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/94.0.4606.71 Mobile Safari/537.36",
    "ios-safari": "Mozilla/5.0 (iPhone13,2; U; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Version/10.0 Mobile/15E148 Safari/602.1",
    "windows-edge": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.135 Safari/537.36 Edge/12.246",
    "macos-safari": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_2) AppleWebKit/601.3.9 (KHTML, like Gecko) Version/9.0.2 Safari/601.3.9",
    "linux-firefox": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:15.0) Gecko/20100101 Firefox/15.0.1",
}
# 全局配置变量（运行时加载）
config = {
    "account": "",
    "password": "",
    "carrier": "cmcc",
    "ua_mode": "ios-safari"
}
# 初始化Windows原生通知器
toaster = ToastNotifier()

# ===================== 日志配置（新增自动清理）=====================
def init_logger() -> None:
    """初始化日志系统（含自动清理逻辑）"""
    # 日志文件大小检查 & 清理
    clean_log_if_needed()
    
    # 日志格式标准化
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(funcName)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        encoding='utf-8'
    )

def get_file_size_mb(file_path: str) -> float:
    """获取文件大小（MB）"""
    if not os.path.exists(file_path):
        return 0.0
    return os.path.getsize(file_path) / 1024 / 1024

def clean_log_if_needed() -> None:
    """日志文件超过阈值时自动清理"""
    try:
        file_size = get_file_size_mb(LOG_FILE)
        if file_size >= LOG_CLEAN_THRESHOLD:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write("")  # 清空日志
            logging.info(f"【日志清理】文件大小{file_size:.2f}MB超过阈值{LOG_CLEAN_THRESHOLD}MB，已清空")
    except Exception as e:
        logging.error(f"【日志清理】执行失败: {str(e)}")

# ===================== 配置文件操作（逻辑精简）=====================
def load_config() -> bool:
    """加载配置文件
    
    Returns:
        bool: 加载成功返回True，失败/不完整返回False
    """
    global config
    try:
        if not os.path.exists(CONFIG_FILE):
            logging.warning(f"【配置加载】配置文件不存在: {CONFIG_FILE}")
            return False
        
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            for line in f.readlines():
                line = line.strip()
                # 跳过注释/空行/无效行
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key in config:
                    config[key] = value
        
        # 校验配置完整性
        if all(config.values()):
            logging.info(f"【配置加载】成功读取配置文件: {CONFIG_FILE}")
            return True
        logging.warning("【配置加载】配置文件内容不完整（账号/密码/运营商/UA模式缺失）")
        return False
    except Exception as e:
        logging.error(f"【配置加载】读取失败: {str(e)}", exc_info=True)
        return False

def save_config() -> bool:
    """保存配置到文件
    
    Returns:
        bool: 保存成功返回True，失败返回False
    """
    try:
        # 确保exe目录可写（创建目录，防止权限问题）
        exe_dir = os.path.dirname(CONFIG_FILE)
        if not os.path.exists(exe_dir):
            os.makedirs(exe_dir)
        
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("# 校园网自动登录配置文件\n")
            f.write(f"account={config['account']}\n")
            f.write(f"password={config['password']}\n")
            f.write(f"carrier={config['carrier']}\n")
            f.write(f"ua_mode={config['ua_mode']}\n")
        logging.info(f"【配置保存】成功保存到: {CONFIG_FILE}")
        return True
    except Exception as e:
        logging.error(f"【配置保存】失败: {str(e)}", exc_info=True)
        messagebox.showerror("错误", f"保存配置失败：{str(e)}\n请检查exe所在目录是否有写入权限")
        return False

# ===================== 配置窗口类（优化字体/映射逻辑）=====================
class ConfigWindow(tk.Toplevel):
    """配置窗口（System Configuration）"""
    # 静态映射表（工程化管理）
    CARRIER_MAP = {
        "China Mobile": "cmcc",
        "China Telecom": "telecom",
        "China Unicom": "unicom",
        "Campus Network": "xyw"
    }
    UA_MAP = {
        "Android Chrome": "android-chrome",
        "iOS Safari": "ios-safari",
        "Windows Edge": "windows-edge",
        "macOS Safari": "macos-safari",
        "Linux Firefox": "linux-firefox",
        "Random": "random"
    }
    # 反向映射（用于初始化选中状态）
    CARRIER_REVERSE_MAP = {v: k for k, v in CARRIER_MAP.items()}
    UA_REVERSE_MAP = {v: k for k, v in UA_MAP.items()}

    def __init__(self, parent: tk.Tk):
        super().__init__(parent)
        self.title("System Configuration")
        self.geometry("400x350")
        self.resizable(False, False)
        self.configure(bg="#f5f5f5")
        self.attributes('-topmost', True)
        self.grab_set()  # 模态窗口
        
        # 初始化UI
        self._init_style()
        self._create_widgets()

    def _init_style(self) -> None:
        """初始化界面样式（标准化字体）"""
        self.style = ttk.Style()
        self.style.configure("Transparent.TFrame", background="#f5f5f5")
        self.style.configure(
            "Accent.TButton", 
            font=("Segoe UI", 10, "normal"),
            padding=5
        )

    def _create_widgets(self) -> None:
        """创建配置窗口控件"""
        # 标题
        title_label = ttk.Label(
            self,
            text="System Configuration",
            font=("Segoe UI", 16, "bold")
        )
        title_label.pack(pady=20)
        
        # 配置框架
        config_frame = ttk.Frame(self, style="Transparent.TFrame")
        config_frame.pack(pady=10, padx=30, fill=tk.X)
        
        # 账号输入框
        ttk.Label(config_frame, text="Account:", font=("Segoe UI", 12)).grid(row=0, column=0, sticky=tk.W, pady=10)
        self.account_entry = ttk.Entry(config_frame, font=("Segoe UI", 12), width=25)
        self.account_entry.grid(row=0, column=1, pady=10)
        if config["account"]:
            self.account_entry.insert(0, config["account"])
        
        # 密码输入框（密文显示，明文存储）
        ttk.Label(config_frame, text="Password:", font=("Segoe UI", 12)).grid(row=1, column=0, sticky=tk.W, pady=10)
        self.password_entry = ttk.Entry(config_frame, font=("Segoe UI", 12), width=25, show="*")
        self.password_entry.grid(row=1, column=1, pady=10)
        if config["password"]:
            self.password_entry.insert(0, config["password"])
        
        # 运营商选择框
        ttk.Label(config_frame, text="Carrier:", font=("Segoe UI", 12)).grid(row=2, column=0, sticky=tk.W, pady=10)
        self.carrier_var = tk.StringVar()
        carrier_options = list(self.CARRIER_MAP.keys())
        default_carrier = self.CARRIER_REVERSE_MAP.get(config["carrier"], "China Mobile")
        self.carrier_var.set(default_carrier)
        carrier_combo = ttk.Combobox(
            config_frame,
            textvariable=self.carrier_var,
            values=carrier_options,
            font=("Segoe UI", 12),
            width=23,
            state="readonly"
        )
        carrier_combo.grid(row=2, column=1, pady=10)
        
        # UA模式选择框
        ttk.Label(config_frame, text="UA Mode:", font=("Segoe UI", 12)).grid(row=3, column=0, sticky=tk.W, pady=10)
        self.ua_var = tk.StringVar()
        ua_options = list(self.UA_MAP.keys())
        default_ua = self.UA_REVERSE_MAP.get(config["ua_mode"], "iOS Safari")
        self.ua_var.set(default_ua)
        ua_combo = ttk.Combobox(
            config_frame,
            textvariable=self.ua_var,
            values=ua_options,
            font=("Segoe UI", 12),
            width=23,
            state="readonly"
        )
        ua_combo.grid(row=3, column=1, pady=10)
        
        # 按钮框架
        btn_frame = ttk.Frame(self, style="Transparent.TFrame")
        btn_frame.pack(pady=20)
        
        # 保存按钮
        save_btn = ttk.Button(
            btn_frame,
            text="Save Config",
            command=self.save_config,
            style="Accent.TButton",
            width=15
        )
        save_btn.pack(side=tk.LEFT, padx=10)
        
        # 取消按钮
        cancel_btn = ttk.Button(
            btn_frame,
            text="Cancel",
            command=self.destroy,
            style="Accent.TButton",
            width=15
        )
        cancel_btn.pack(side=tk.RIGHT, padx=10)

    def save_config(self) -> None:
        """保存配置（转换显示名→后台标识）"""
        # 读取输入内容
        account = self.account_entry.get().strip()
        password = self.password_entry.get().strip()
        
        # 校验必填项
        if not account or not password:
            messagebox.showwarning("警告", "账号和密码不能为空！")
            return
        
        # 转换运营商/UA标识
        carrier = self.CARRIER_MAP.get(self.carrier_var.get().strip(), "cmcc")
        ua_mode = self.UA_MAP.get(self.ua_var.get().strip(), "ios-safari")
        
        # 更新全局配置
        global config
        config.update({
            "account": account,
            "password": password,
            "carrier": carrier,
            "ua_mode": ua_mode
        })
        
        # 保存到文件
        if save_config():
            messagebox.showinfo("成功", "配置保存成功！")
            self.destroy()

# ===================== 警告窗口（逻辑精简）=====================
def show_alert_window(fail_count: int, error_type: str = "reconnect", main_root: Optional[tk.Tk] = None) -> None:
    """显示登录失败警告窗口
    
    Args:
        fail_count: 失败次数
        error_type: 错误类型（account/ip/reconnect/unknown）
        main_root: 主窗口实例
    """
    # 初始化根窗口（若未传入）
    if main_root is None:
        main_root = tk.Tk()
        main_root.withdraw()
    
    # 创建警告窗口（全屏+置顶）
    alert_root = tk.Toplevel(main_root)
    alert_root.title("⚠️ 校园网登录失败警告")
    alert_root.geometry(f"{alert_root.winfo_screenwidth()}x{alert_root.winfo_screenheight()}+0+0")
    alert_root.configure(bg="#ff0000")
    alert_root.attributes('-topmost', True)
    alert_root.overrideredirect(True)

    # 播放提示音（异步执行）
    def play_alert_sound() -> None:
        for _ in range(3):
            winsound.Beep(2000, 500)
            time.sleep(0.2)
    threading.Thread(target=play_alert_sound, daemon=True).start()

    # 错误类型文案映射
    error_text_map = {
        "account": "账号/密码为空",
        "ip": "获取IP失败",
        "reconnect": "重连失败",
        "unknown": "未知错误"
    }
    error_text = error_text_map.get(error_type, "登录失败")

    # 警告内容布局
    title_label = tk.Label(
        alert_root,
        text="⚠️ 登录失败！",
        font=("微软雅黑", 60, "bold"),
        bg="#ff0000",
        fg="white"
    )
    title_label.place(relx=0.5, rely=0.3, anchor=tk.CENTER)

    count_label = tk.Label(
        alert_root,
        text=f"{error_text} × {fail_count}次（达到上限）",
        font=("微软雅黑", 80, "bold"),
        bg="#ff0000",
        fg="white"
    )
    count_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    tip_label = tk.Label(
        alert_root,
        text="点击任意位置关闭 | 监控已暂停（可手动点击Start重启）",
        font=("微软雅黑", 20),
        bg="#ff0000",
        fg="white"
    )
    tip_label.place(relx=0.5, rely=0.7, anchor=tk.CENTER)

    # 关闭逻辑
    def close_alert(event=None) -> None:
        alert_root.destroy()
    alert_root.bind("<Button-1>", close_alert)
    alert_root.focus_set()
    alert_root.grab_set()

# ===================== 自定义控件（工程化封装）=====================
class RoundedWindow(tk.Tk):
    """自定义弧形矩形主窗口"""
    def __init__(self):
        super().__init__()
        self.title("autoLoginCqupt (Stupid Custom Edition)")
        self.geometry("400x340")  # 增加高度适配新按钮
        self.resizable(False, False)
        self.configure(bg="#f5f5f5")
        
        # 绘制弧形背景
        self.canvas = tk.Canvas(self, width=400, height=340, bg="#f5f5f5", highlightthickness=0)
        self.canvas.place(x=0, y=0)
        self.create_rounded_rectangle(
            10, 10, 390, 330, 
            radius=30, 
            fill="#f5f5f5", 
            outline="#e0e0e0", 
            width=2
        )
    
    def create_rounded_rectangle(self, x1: int, y1: int, x2: int, y2: int, radius: int = 25, **kwargs) -> int:
        """绘制弧形矩形
        
        Returns:
            int: 画布元素ID
        """
        points = [
            x1+radius, y1, x1+radius, y1,
            x2-radius, y1, x2-radius, y1,
            x2, y1, x2, y1+radius,
            x2, y1+radius, x2, y2-radius,
            x2, y2-radius, x2, y2,
            x2-radius, y2, x2-radius, y2,
            x1+radius, y2, x1+radius, y2,
            x1, y2, x1, y2-radius,
            x1, y2-radius, x1, y1+radius,
            x1, y1+radius, x1, y1
        ]
        return self.canvas.create_polygon(points, **kwargs, smooth=True)

class CircleButton(tk.Canvas):
    """自定义圆形按钮（支持禁用/悬停效果）"""
    def __init__(
        self, 
        parent: tk.Widget, 
        text: str, 
        command: callable, 
        radius: int = 40, 
        bg_color: str = "#4CAF50", 
        fg_color: str = "white", 
        font: Tuple[str, int, str] = ("Segoe UI", 11, "bold")
    ):
        # 适配父容器背景（兼容Frame/Label等不同控件）
        try:
            # 优先尝试获取background（Frame用这个）
            parent_bg = parent.cget("background")
        except (AttributeError, tk.TclError):  # 改用tk.TclError
            try:
                # 再尝试bg（Label/Canvas用这个）
                parent_bg = parent.cget("bg")
            except:
                parent_bg = "#f5f5f5"
        
        super().__init__(parent, width=radius*2, height=radius*2, bg=parent_bg, highlightthickness=0)
        
        # 按钮属性
        self.radius = radius
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.command = command
        self.text = text
        self.font = font
        self.disabled = False
        self.original_bg = bg_color

        # 初始化绘制
        self.draw()
        self.bind("<Button-1>", self.on_click)
        self.bind("<Enter>", self.on_hover)
        self.bind("<Leave>", self.on_leave)

    def draw(self) -> None:
        """绘制按钮（根据状态更新样式）"""
        self.delete("all")
        bg = "#cccccc" if self.disabled else self.bg_color
        self.create_oval(1, 1, self.radius*2-1, self.radius*2-1, fill=bg, outline="", width=0)
        self.create_text(self.radius, self.radius, text=self.text, fill=self.fg_color, font=self.font)

    def on_click(self, event) -> None:
        """点击事件（禁用状态不响应）"""
        if not self.disabled:
            self.command()

    def on_hover(self, event) -> None:
        """悬停效果（亮化背景）"""
        if not self.disabled:
            self.create_oval(1, 1, self.radius*2-1, self.radius*2-1, fill=self.lighten_color(self.bg_color, 10), outline="", width=0)
            self.create_text(self.radius, self.radius, text=self.text, fill=self.fg_color, font=self.font)

    def on_leave(self, event) -> None:
        """离开事件（恢复原样式）"""
        self.draw()

    def lighten_color(self, color: str, percent: int) -> str:
        """颜色亮化处理
        
        Args:
            color: 原始颜色（#RRGGBB）
            percent: 亮化百分比
        
        Returns:
            str: 亮化后的颜色
        """
        color = color.lstrip('#')
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        # 计算亮化值（不超过255）
        r = min(255, r + int(255 * percent / 100))
        g = min(255, g + int(255 * percent / 100))
        b = min(255, b + int(255 * percent / 100))
        return f"#{r:02x}{g:02x}{b:02x}"

    def set_state(self, state: str) -> None:
        """设置按钮状态（NORMAL/DISABLED）"""
        self.disabled = (state == tk.DISABLED)
        self.draw()

class LogViewerWindow(tk.Toplevel):
    """日志查看窗口（支持错误行高亮）"""
    def __init__(self, parent: tk.Tk, error_line: Optional[int] = None):
        super().__init__(parent)
        self.title("Log Viewer")
        self.geometry("800x500")
        self.resizable(True, True)
        self.configure(bg="#f5f5f5")
        
        # 初始化属性
        self.error_line = error_line
        self._create_widgets()
        self.load_log()
        
        # 高亮错误行（若指定）
        if self.error_line:
            self.highlight_error_line()

    def _create_widgets(self) -> None:
        """创建日志查看控件"""
        # 日志文本框（带滚动条）
        self.log_text = scrolledtext.ScrolledText(
            self, 
            wrap=tk.WORD, 
            font=("Consolas", 10),
            bg="white",
            fg="black"
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 日志清理按钮（新增）
        clean_btn = ttk.Button(
            self,
            text="Clean Log Now",
            command=self.clean_log_immediately,
            style="Accent.TButton"
        )
        clean_btn.pack(side=tk.BOTTOM, padx=10, pady=5)

    def load_log(self) -> None:
        """加载日志文件内容"""
        self.log_text.delete(1.0, tk.END)
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                log_content = f.readlines()
            
            # 按级别着色
            for idx, line in enumerate(log_content, 1):
                if "ERROR" in line or (self.error_line and str(self.error_line) in line):
                    self.log_text.insert(tk.END, line, "error")
                elif "WARNING" in line:
                    self.log_text.insert(tk.END, line, "warning")
                else:
                    self.log_text.insert(tk.END, line)
            
            # 样式配置
            self.log_text.tag_configure("error", foreground="red", font=("Consolas", 10, "bold"))
            self.log_text.tag_configure("warning", foreground="#ff7f00", font=("Consolas", 10, "bold"))
            self.log_text.see(tk.END)
            
        except FileNotFoundError:
            self.log_text.insert(tk.END, f"Log file not found! Path: {LOG_FILE}", "error")
        except Exception as e:
            self.log_text.insert(tk.END, f"Load log failed: {str(e)} | Path: {LOG_FILE}", "error")

    def highlight_error_line(self) -> None:
        """高亮指定错误行"""
        self.log_text.tag_remove("highlight", 1.0, tk.END)
        self.log_text.tag_configure("highlight", background="#ffeeee")
        
        start = 1.0
        while True:
            pos = self.log_text.search(str(self.error_line), start, stopindex=tk.END)
            if not pos:
                break
            line_start = pos.split('.')[0] + '.0'
            line_end = f"{int(line_start.split('.')[0]) + 1}.0"
            self.log_text.tag_add("highlight", line_start, line_end)
            self.log_text.see(line_start)
            start = line_end

    def clean_log_immediately(self) -> None:
        """立即清理日志（手动触发）"""
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write("")
            self.log_text.delete(1.0, tk.END)
            self.log_text.insert(tk.END, "Log file cleaned successfully!", "warning")
            logging.info("【日志清理】手动触发日志清空")
        except Exception as e:
            self.log_text.insert(tk.END, f"Clean log failed: {str(e)}", "error")
            logging.error(f"【日志清理】手动清理失败: {str(e)}", exc_info=True)

# ===================== 主界面核心逻辑（精简冗余）=====================
class SimpleCampusNetworkGUI:
    """校园网自动登录主界面核心类"""
    def __init__(self, root: RoundedWindow):
        # 基础属性初始化
        self.root = root
        self.log_window: Optional[LogViewerWindow] = None
        self.log_window_opened = False
        self.reconnect_fail_count = 0
        self.reconnect_attempts = 0
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        # 通知状态标记（避免重复推送）
        self._notified_start = False
        self._notified_already_logged = False
        self._notified_stop = False
        self._notified_close = False
        
        # 初始化UI & 检查配置
        self._create_widgets()
        self.check_config()

    def _create_widgets(self) -> None:
        """创建主界面控件"""
        # 样式初始化
        style = ttk.Style()
        style.configure("Transparent.TFrame", background="#f5f5f5")

        # 标题
        title_label = ttk.Label(
            self.root,
            text="Automatic Login",
            font=("Segoe UI", 18, "bold"),
            background="#f5f5f5"
        )
        title_label.pack(pady=(30, 5))

        # 状态显示
        self.status_var = tk.StringVar(value="Not running")
        status_label = ttk.Label(
            self.root,
            textvariable=self.status_var,
            font=("Segoe UI", 12),
            foreground="#2196F3",
            background="#f5f5f5"
        )
        status_label.pack(pady=10)

        # 日志查看链接
        log_link = tk.Label(
            self.root,
            text="📝 Inspect Runtime Logs",
            font=("Segoe UI", 12),
            fg="#2196F3",
            cursor="hand2",
            bg="#f5f5f5"
        )
        log_link.pack(pady=5)
        log_link.bind("<Button-1>", lambda e: self.open_log_viewer())
        log_link.bind("<Enter>", lambda e: log_link.config(fg="#1976D2"))
        log_link.bind("<Leave>", lambda e: log_link.config(fg="#2196F3"))

        # 按钮容器
        frame_buttons = ttk.Frame(self.root, style="Transparent.TFrame")
        frame_buttons.pack(pady=15)

        # 日志清理按钮（调整为超链接样式，放左侧）
        clean_log_link = tk.Label(
            self.root,
            text="🗑 Clean Log",
            font=("Segoe UI", 12),
            fg="#2196F3",
            cursor="hand2",
            bg="#f5f5f5",
            padx=0,  # 关键：清空水平内边距
            pady=0   # 关键：清空垂直内边距
        )
        clean_log_link.place(relx=0.1, rely=0.95, anchor=tk.SW)  # 左下角
        clean_log_link.bind("<Button-1>", lambda e: self.clean_log_manually())
        clean_log_link.bind("<Enter>", lambda e: clean_log_link.config(fg="#1976D2"))
        clean_log_link.bind("<Leave>", lambda e: clean_log_link.config(fg="#2196F3"))

        # 启动按钮
        self.start_btn = CircleButton(
            frame_buttons,
            text="Start",
            command=self.start_monitor,
            radius=45,
            bg_color="#4CAF50",
            fg_color="white",
            font=("Segoe UI", 11, "bold")
        )
        self.start_btn.pack(side=tk.LEFT, padx=15)

        # 停止按钮
        self.stop_btn = CircleButton(
            frame_buttons,
            text="Stop",
            command=self.stop_monitor,
            radius=45,
            bg_color="#f44336",
            fg_color="white",
            font=("Segoe UI", 11, "bold")
        )
        self.stop_btn.set_state(tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT, padx=15)
            
        # 右下角设置链接
        settings_link = tk.Label(
            self.root,
            text="⚙️ Settings",
            font=("Segoe UI", 12),
            fg="#2196F3",
            cursor="hand2",
            bg="#f5f5f5"
        )
        settings_link.place(relx=0.9, rely=0.95, anchor=tk.SE)  # 右下角
        settings_link.bind("<Button-1>", lambda e: self.open_config_window())
        settings_link.bind("<Enter>", lambda e: settings_link.config(fg="#1976D2"))
        settings_link.bind("<Leave>", lambda e: settings_link.config(fg="#2196F3"))

    def check_config(self) -> None:
        """检查配置完整性，缺失则弹出配置窗口"""
        if not load_config():
            messagebox.showinfo("提示", "未检测到有效配置，请先完成配置！")
            self.open_config_window()

    def open_config_window(self) -> None:
        """打开配置窗口"""
        ConfigWindow(self.root)

    def open_log_viewer(self, error_line: Optional[int] = None) -> None:
        """打开日志查看窗口（防止重复打开）"""
        if self.log_window_opened:
            return
        
        # 关闭已有日志窗口
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.destroy()
        
        # 创建新日志窗口
        self.log_window = LogViewerWindow(self.root, error_line)
        self.log_window.attributes('-topmost', True)
        self.log_window.after(1000, lambda: self.log_window.attributes('-topmost', False))
        
        # 标记窗口状态
        self.log_window_opened = True
        self.log_window.protocol("WM_DELETE_WINDOW", self.on_log_window_close)

    def on_log_window_close(self) -> None:
        """日志窗口关闭回调"""
        self.log_window.destroy()
        self.log_window_opened = False

    def clean_log_manually(self) -> None:
        """手动清理日志（弹窗确认）"""
        if messagebox.askyesno("确认", "是否立即清空日志文件？"):
            try:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("")
                messagebox.showinfo("成功", "日志文件已清空！")
                logging.info("【日志清理】用户手动清空日志文件")
            except Exception as e:
                messagebox.showerror("错误", f"清理日志失败：{str(e)}")
                logging.error(f"【日志清理】手动清理失败: {str(e)}", exc_info=True)

    def _get_error_line(self) -> Optional[int]:
        """获取当前异常的行号"""
        try:
            exc_type, exc_value, exc_traceback = traceback.sys.exc_info()
            if exc_traceback:
                tb_frame = traceback.extract_tb(exc_traceback)[-1]
                return tb_frame.lineno
        except:
            pass
        return None

    def _get_user_agent(self) -> str:
        """获取当前UA模式对应的User-Agent
        
        Returns:
            str: 匹配的UA字符串（默认linux-firefox）
        """
        ua_mode = config["ua_mode"]
        if ua_mode == "random":
            ua_key = random.choice(list(UA_POOL.keys()))
            logging.info(f"【UA选择】随机选择: {ua_key}")
            return UA_POOL[ua_key]
        else:
            if ua_mode in UA_POOL:
                return UA_POOL[ua_mode]
            logging.warning(f"【UA选择】模式{ua_mode}不合法，使用默认linux-firefox")
            return UA_POOL["linux-firefox"]

    def _try_decode(self, s: str) -> str:
        """解码返回信息（兼容Unicode/Base64）"""
        try:
            if s.startswith("\\u"):
                return bytes(s, "utf-8").decode("unicode_escape")
            return b64decode(s).decode()
        except:
            return s

    def _extract(self, varname: str, html: str) -> Optional[str]:
        """从HTML中提取指定变量值"""
        m = re.search(rf"{varname}\s*=\s*['\"]([^'\"]+)['\"]", html)
        return m.group(1) if m else None

    def get_ip(self) -> Optional[str]:
        """获取当前WLAN IP地址
        
        Returns:
            str: IP地址 | None（获取失败）
        """
        try:
            # 尝试从门户页面提取
            req = requests.get(REFERER, timeout=5)
            charset = req.encoding or "gb2312"
            html = req.content.decode(charset, errors="ignore")
            
            # 优先提取门户页面中的IP
            for name in ("v46ip", "ss5", "v4ip"):
                val = self._extract(name, html)
                if val:
                    logging.info(f"【IP获取】从门户提取: {val}")
                    return val
            
            # 尝试从ss3转换IP
            hex3 = self._extract("ss3", html)
            if hex3:
                if len(hex3) % 2:
                    hex3 = "0" + hex3
                parts = [str(int(hex3[i:i+2], 16)) for i in range(0, len(hex3), 2)]
                ip = ".".join(parts)
                logging.info(f"【IP获取】从ss3转换: {ip}")
                return ip
            
            # 兜底：通过Socket获取
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            logging.info(f"【IP获取】Socket方式: {ip}")
            return ip
        except Exception as e:
            logging.error(f"【IP获取】失败: {str(e)}", exc_info=True)
            error_line = self._get_error_line()
            self.root.after(0, self.open_log_viewer, error_line)
            return None

    def _send_notification(self, title: str, message: str, icon_type: str) -> None:
        """修复：替换plyer为Windows原生通知（打包后可用）"""
        try:
            icon_path = ICON_CONFIG.get(icon_type, "")
            
            # 检查图标是否存在，不存在则用默认
            if not os.path.exists(icon_path):
                logging.warning(f"【通知发送】图标{icon_type}不存在: {icon_path}")
                icon_path = None
            
            # 使用win10toast发送通知
            toaster.show_toast(
                title=title,
                msg=message,
                icon_path=icon_path,
                duration=5,
                threaded=True  # 线程化，不阻塞程序
            )
            logging.info(f"【通知发送】成功: {title} - {message}")
        except Exception as e:
            logging.error(f"【通知发送】失败: {str(e)}", exc_info=True)
            # 降级：无图标发送通知
            toaster.show_toast(
                title=title,
                msg=message,
                duration=5,
                threaded=True
            )

    def check_and_login(self) -> bool:
        """核心登录/重连逻辑
        
        Returns:
            bool: 连接成功返回True，失败返回False
        """
        # 基础配置校验
        account = config["account"]
        password = config["password"]
        carrier = config["carrier"]
        ua = self._get_user_agent()

        if not account or not password:
            self._send_notification("配置错误", "请设置账号密码!", "fail")
            logging.error("【登录逻辑】配置错误：账号/密码未设置")
            self.reconnect_fail_count += 1
            return False

        # 获取IP
        ipv4 = self.get_ip()
        if not ipv4:
            self._send_notification("IP失败", "无法获取IP!", "fail")
            self.reconnect_fail_count += 1
            return False
        
        # 定义移动端UA模式列表
        mobile_ua_modes = ["android-chrome", "ios-safari", "random"]
        # 判断当前UA模式类型（random模式也按移动端处理）
        if config["ua_mode"] in mobile_ua_modes:
            account_prefix = "1"  # 移动端前缀为1
            logging.info(f"【UA类型】移动端 - 使用前缀1 | 模式: {config['ua_mode']}")
        else:
            account_prefix = "0"  # PC端前缀为0
            logging.info(f"【UA类型】PC端 - 使用前缀0 | 模式: {config['ua_mode']}")

        # 构建登录URL
        login_url = (
            f"{PORTAL}?c=Portal&a=login&callback=dr1003&login_method=1"
            f"&wlan_user_ip={ipv4}"
            f"&wlan_user_mac=50ebf6ca3dbc"
            f"&user_account=,{account_prefix},{account}@{carrier}"
            f"&user_password={password}"
            f"&jsVersion=3.3.3&v=9635"
        )

        # 请求头配置
        headers = {
            "Host": HOST,
            "Referer": REFERER,
            "User-Agent": ua,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive"
        }

        try:
            # 检查是否已登录
            check_resp = requests.get(REFERER, timeout=5, headers=headers)
            if "注销页" in check_resp.text:
                logging.info(f"【登录状态】已登录 | IP: {ipv4} | UA: {ua[:30]}")
                if not self._notified_already_logged:
                    self._send_notification("【万物皆可调度，指令即为准则】", "全域态势，尽在掌握。", "success")
                    self._notified_already_logged = True
                self.reconnect_fail_count = 0
                self.reconnect_attempts = 0
                return True
            logging.warning(f"【登录状态】已断开 | IP: {ipv4} | 执行重连")
            self._send_notification("网络已断开", "立即执行单次重连...", "fail")

            # 执行重连
            resp = requests.get(login_url, headers=headers, timeout=5)
            resp_text = resp.text.lstrip("dr1003(").rstrip(")")
            resp_json = json.loads(resp_text)

            # 重连结果处理
            if resp_json["result"] == "1":
                logging.info(f"【重连结果】成功 | IP: {ipv4} | UA: {ua[:30]}")
                # 匹配UA模式名称
                ua_name = [k for k, v in UA_POOL.items() if v == ua][0]
                self._send_notification(
                    "重连成功",
                    f"IP: {ipv4}\nUA: {ua_name}",
                    "success"
                )
                self._notified_already_logged = False
                self.reconnect_fail_count = 0
                self.reconnect_attempts = 0
                return True
            elif resp_json["result"] == "0":
                ret_code = resp_json.get("ret_code", 0)
                msg = self._try_decode(resp_json.get("msg", ""))
                if ret_code == 2:
                    logging.info(f"【重连结果】已登录 | IP: {ipv4} | UA: {ua[:30]}")
                    if not self._notified_already_logged:
                        self._send_notification("已登录", "监控中...", "success")
                        self._notified_already_logged = True
                    self.reconnect_fail_count = 0
                    self.reconnect_attempts = 0
                    return True
                logging.error(f"【重连结果】失败 | 原因: {msg} | IP: {ipv4}")
                self._send_notification("重连失败", f"原因: {msg}", "fail")
                error_line = self._get_error_line()
                self.root.after(0, self.open_log_viewer, error_line)

            # 重连失败计数
            self.reconnect_fail_count += 1
            self.reconnect_attempts += 1
            logging.info(f"【失败计数】连续失败{self.reconnect_fail_count}次 | 重连尝试{self.reconnect_attempts}次")
            return False

        except requests.exceptions.RequestException as e:
            logging.error(f"【重连异常】网络请求失败 | 原因: {str(e)} | IP: {ipv4}", exc_info=True)
            self._send_notification("网络异常", "重连请求失败...", "fail")
            error_line = self._get_error_line()
            self.root.after(0, self.open_log_viewer, error_line)
            self.reconnect_fail_count += 1
            self.reconnect_attempts += 1
            return False
        except Exception as e:
            logging.error(f"【重连异常】未知错误 | 原因: {str(e)} | IP: {ipv4}", exc_info=True)
            self._send_notification("未知错误", "重连出错，查看日志", "unknown")
            error_line = self._get_error_line()
            self.root.after(0, self.open_log_viewer, error_line)
            self.reconnect_fail_count += 1
            self.reconnect_attempts += 1
            return False
        
    def monitor_loop(self) -> None:
        """监控循环（后台线程执行）"""
        # 运营商中文映射（用于通知）
        carrier_cn = {
            "cmcc": "中国移动",
            "telecom": "中国电信",
            "unicom": "中国联通",
            "xyw": "校园网"
        }.get(config["carrier"], "未知")

        # 首次启动通知
        if not self._notified_start:
            self._send_notification(
                "【系统启动完毕】\n欢迎您，执掌全局的决策者。",
                f"账号: {config['account']}\n运营商: {carrier_cn}\nUA: {config['ua_mode']}",
                "already"
            )
            self._notified_start = True
            self._notified_already_logged = False

        # 监控主循环
        while self.running:
            is_connected = self.check_and_login()
            
            # 达到失败阈值，暂停监控
            if self.reconnect_fail_count >= FAIL_THRESHOLD:
                # 判定错误类型
                error_type = "reconnect"
                if not config["account"] or not config["password"]:
                    error_type = "account"
                elif not self.get_ip():
                    error_type = "ip"
                
                logging.error(f"【监控暂停】连续{FAIL_THRESHOLD}次{error_type}错误，暂停监控")
                self._send_notification("操作上限", f"连续{FAIL_THRESHOLD}次{error_type}错误，暂停监控", "fail")
                self.running = False
                self.update_status()
                # 恢复按钮状态
                self.start_btn.set_state(tk.NORMAL)
                self.stop_btn.set_state(tk.DISABLED)
                # 弹出警告窗口
                self.root.after(0, lambda: show_alert_window(FAIL_THRESHOLD, error_type, self.root))
                # 重置计数器
                self.reconnect_fail_count = 0
                self.reconnect_attempts = 0
                break
            
            # 计算下次检查间隔
            if self.running:
                if is_connected:
                    next_interval = CHECK_INTERVAL
                    self.reconnect_attempts = 0
                else:
                    attempt_idx = min(self.reconnect_attempts, len(RECONNECT_INTERVALS) - 1)
                    next_interval = RECONNECT_INTERVALS[attempt_idx]
                
                logging.info(f"【监控计划】下次检查间隔: {next_interval}秒 | 重连尝试: {self.reconnect_attempts}次")
                # 间隔等待（支持中断）
                for _ in range(next_interval):
                    if not self.running:
                        break
                    time.sleep(1)

        self.update_status()

    def start_monitor(self) -> None:
        """启动监控线程"""
        # 配置校验
        if not config["account"] or not config["password"]:
            messagebox.showwarning("警告", "请先完成配置！")
            self.open_config_window()
            return
            
        if self.running:
            messagebox.showinfo("提示", "监控已运行!")
            return

        # 重置状态标记
        self._notified_start = False
        self._notified_stop = False
        self._notified_already_logged = False
        self.reconnect_fail_count = 0
        self.reconnect_attempts = 0
        
        # 启动后台线程
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.update_status()

        # 更新按钮状态
        self.start_btn.set_state(tk.DISABLED)
        self.stop_btn.set_state(tk.NORMAL)

    def stop_monitor(self) -> None:
        """停止监控"""
        if not self.running:
            return

        self.running = False
        self.update_status()

        # 发送停止通知
        if not self._notified_stop:
            self._send_notification("【全域资源已封存，顶级权限已休眠】", "等待指令唤醒...", "already")
            self._notified_stop = True

        # 等待线程结束
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2)

        # 恢复按钮状态
        self.start_btn.set_state(tk.NORMAL)
        self.stop_btn.set_state(tk.DISABLED)

    def update_status(self) -> None:
        """更新界面状态显示"""
        self.status_var.set("Running" if self.running else "Not running")

    def on_close(self) -> None:
        """修复：窗口关闭回调（安全退出，确保线程终止）"""
        # 停止监控
        exit_notified = False
        if self.running:
            self.running = False  # 立即终止循环
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=3)  # 等待线程终止
            self.stop_monitor()
            exit_notified = True
        
        # 发送退出通知
        if not exit_notified:
            self._send_notification("【系统安全退出】", "恭送您离场，静候您再次降临。", "already")
        
        # 关闭日志窗口
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.destroy()
        
        # 强制退出程序，避免残留
        self.root.quit()
        self.root.destroy()
        sys.exit(0)

# ===================== 程序入口 =====================
if __name__ == '__main__':
    # 初始化日志系统
    init_logger()
    
    # 验证图标路径
    for icon_type, path in ICON_CONFIG.items():
        if os.path.exists(path):
            logging.info(f"【初始化】图标{icon_type}存在: {path}")
        else:
            logging.warning(f"【初始化】图标{icon_type}不存在: {path}")

    # 启动主程序
    try:
        root = RoundedWindow()
        app = SimpleCampusNetworkGUI(root)
        root.protocol("WM_DELETE_WINDOW", app.on_close)
        root.mainloop()
    except Exception as e:
        logging.critical(f"【程序崩溃】未捕获异常: {str(e)}", exc_info=True)
        messagebox.showerror("致命错误", f"程序启动失败：{str(e)}\n请查看日志文件获取详情")