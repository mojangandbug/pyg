import os
import sys
import json
import yaml
import winreg
import shutil
import urllib.request
import threading
import zipfile
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText

# 托盘依赖
from PIL import Image, ImageDraw
import pystray

# ---- 动态获取项目根目录 ----
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- 相对目录配置 ----
CLASH_DIR = os.path.join(BASE_DIR, "clash_core")      
CONFIG_DIR = os.path.join(CLASH_DIR, "profiles")     
CORE_PATH = os.path.join(CLASH_DIR, "mihomo.exe")    
NODE_TXT_PATH = os.path.join(BASE_DIR, "node.txt")   

# 默认下载源 
CORE_URL = "https://github.com/MetaCubeX/mihomo/releases/download/v1.18.9/mihomo-windows-amd64-v1.18.9.zip"
GEOIP_URL = "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.dat"
GEOSITE_URL = "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat"
MMDB_URL = "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/country.mmdb"

# 初始化自动创建所需文件夹和文件
os.makedirs(CLASH_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)
if not os.path.exists(NODE_TXT_PATH):
    with open(NODE_TXT_PATH, "w", encoding="utf-8") as f:
        f.write("# 请在下方粘贴你的订阅链接，支持用 | 后面写配置名称\n")
        f.write("# 格式示例：https://example.com/sub.yaml|香港原生\n")

class ClashManagerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Mihomo/Clash 相对路径管理器")
        self.root.geometry("620x680")  
        
        self.core_process = None  
        self.tray = None  
        
        self.setup_ui()
        self.refresh_configs()
        self.check_sys_proxy_status()
        
        # 拦截窗口右上角 X 按钮，改为隐藏到托盘
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        
        # 异步启动托盘图标
        self.run_async(self.setup_tray)

    def setup_ui(self):
        # ---- 状态监视 ----
        status_frame = ttk.LabelFrame(self.root, text=" 状态监视 ", padding=10)
        status_frame.pack(fill="x", padx=15, pady=5)
        
        self.lbl_proxy_status = ttk.Label(status_frame, text="系统代理: 检测中...", font=("Helvetica", 10, "bold"))
        self.lbl_proxy_status.pack(side="left", padx=5)
        
        self.lbl_core_status = ttk.Label(status_frame, text="内核状态: 未运行", font=("Helvetica", 10, "bold"), foreground="red")
        self.lbl_core_status.pack(side="right", padx=5)
        
        # ---- 控制台（启动/停止）----
        control_frame = ttk.LabelFrame(self.root, text=" 内核控制 ", padding=10)
        control_frame.pack(fill="x", padx=15, pady=5)
        
        self.btn_toggle_core = ttk.Button(control_frame, text="▶ 启动 Clash 内核", command=self.toggle_core)
        self.btn_toggle_core.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        
        ttk.Button(control_frame, text="更新 Mihomo 内核", command=lambda: self.run_async(self.update_core)).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(control_frame, text="更新 GEO 数据集", command=lambda: self.run_async(self.update_geo)).grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)
        control_frame.columnconfigure(2, weight=1)

        # ---- 系统代理与 TUN ----
        switch_frame = ttk.LabelFrame(self.root, text=" 模式切换 (部分需要管理员权限) ", padding=10)
        switch_frame.pack(fill="x", padx=15, pady=5)
        
        self.btn_toggle_proxy = ttk.Button(switch_frame, text="切换系统代理", command=self.toggle_system_proxy)
        self.btn_toggle_proxy.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        
        ttk.Button(switch_frame, text="一键注入并开启 TUN 模式", command=self.enable_tun_mode).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        switch_frame.columnconfigure(0, weight=1)
        switch_frame.columnconfigure(1, weight=1)

        # ---- 配置选择 ----
        config_frame = ttk.LabelFrame(self.root, text=" 配置文件切换 ", padding=10)
        config_frame.pack(fill="x", padx=15, pady=5)
        
        self.config_listbox = tk.Listbox(config_frame, height=4)
        self.config_listbox.pack(side="left", fill="both", expand=True, padx=5)
        
        scrollbar = ttk.Scrollbar(config_frame, orient="vertical", command=self.config_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.config_listbox.config(yscrollcommand=scrollbar.set)
        
        btn_box = ttk.Frame(self.root, padding=5)
        btn_box.pack(fill="x", padx=15, pady=2)
        ttk.Button(btn_box, text="从 node.txt 下载订阅", command=lambda: self.run_async(self.download_from_node_txt)).pack(side="left", padx=5)
        ttk.Button(btn_box, text="本地导入 (.yaml)", command=self.import_config).pack(side="left", padx=5)
        ttk.Button(btn_box, text="应用所选配置", command=self.apply_config).pack(side="right", padx=5)

        # ---- 实时日志监控显示 ----
        log_frame = ttk.LabelFrame(self.root, text=" 内核控制台实时日志监控 ", padding=10)
        log_frame.pack(fill="both", expand=True, padx=15, pady=10)
        
        self.log_text = ScrolledText(log_frame, bg="black", fg="#00FF00", font=("Consolas", 9), insertbackground="white")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.insert(tk.END, "[System] 监控就绪。等待内核启动...\n")

    def run_async(self, func, *args):
        threading.Thread(target=func, args=args, daemon=True).start()

    def log_to_ui(self, message):
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)

    # ================= 托盘管理模块 =================
    def create_tray_image(self):
        image = Image.new('RGB', (64, 64), color=(30, 144, 255))
        dc = ImageDraw.Draw(image)
        dc.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
        return image

    def setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", self.show_from_tray, default=True),
            pystray.MenuItem("切换系统代理", self.toggle_system_proxy),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("完全退出整个程序", self.quit_app)
        )
        self.tray = pystray.Icon("ClashManager", self.create_tray_image(), "Mihomo/Clash 管理器", menu)
        self.tray.run()

    def hide_to_tray(self):
        self.root.withdraw()  

    def show_from_tray(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)  

    def quit_app(self, icon=None, item=None):
        """完全退出程序（清理系统代理、清理内核与托盘）"""
        # 1. 【安全核心】自动关闭并清理 Windows 系统代理，防止断网
        try:
            inter_set = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0, winreg.KEY_WRITE)
            winreg.SetValueEx(inter_set, "ProxyEnable", 0, winreg.REG_DWORD, 0) 
            os.system('Rundll32.exe USER32.dll,UpdatePerUserSystemParameters')
            print("[System] 退出前已成功清理 Windows 系统代理。")
        except Exception as e:
            print(f"[System] 退出时清理系统代理失败: {e}")

        # 2. 停止内核进程
        if self.core_process:
            try:
                self.core_process.terminate()
                self.core_process.wait()
            except Exception:
                pass
        
        # 3. 停止托盘图标
        if self.tray:
            self.tray.stop()
            
        # 4. 销毁 Tkinter 实例
        self.root.after(0, self.root.destroy)

    # ================= 内核控制与监控 =================
    def toggle_core(self):
        if self.core_process and self.core_process.poll() is None:
            self.stop_core()
        else:
            self.start_core()

    def start_core(self):
        if not os.path.exists(CORE_PATH):
            messagebox.showerror("错误", "未找到内核文件 mihomo.exe，请先点击更新内核！")
            return
        active_config = os.path.join(CLASH_DIR, "config.yaml")
        if not os.path.exists(active_config):
            messagebox.showerror("错误", "未检测到活动的 config.yaml 配置文件！")
            return

        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            self.core_process = subprocess.Popen(
                [CORE_PATH, "-d", CLASH_DIR],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                cwd=CLASH_DIR,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            self.lbl_core_status.config(text="内核状态: 正在运行", foreground="green")
            self.btn_toggle_core.config(text="■ 停止 Clash 内核")
            self.log_to_ui("[System] 内核进程成功拉起...\n")
            self.run_async(self.monitor_core_log)
        except Exception as e:
            messagebox.showerror("启动失败", f"内核拉起异常: {e}")

    def stop_core(self):
        if self.core_process:
            self.core_process.terminate() 
            self.core_process.wait()
            self.core_process = None
        self.lbl_core_status.config(text="内核状态: 已停止", foreground="red")
        self.btn_toggle_core.config(text="▶ 启动 Clash 内核")
        self.log_to_ui("[System] 内核进程已安全关闭。\n")

    def monitor_core_log(self):
        while self.core_process and self.core_process.poll() is None:
            line = self.core_process.stdout.readline()
            if line:
                self.root.after(0, self.log_to_ui, line)
        self.root.after(0, self.handle_core_exit)

    def handle_core_exit(self):
        if self.core_process and self.core_process.poll() is not None:
            self.lbl_core_status.config(text="内核状态: 异常退出", foreground="orange")
            self.btn_toggle_core.config(text="▶ 启动 Clash 内核")
            self.log_to_ui(f"[System] 内核已终止。退出代码: {self.core_process.poll()}\n")
            self.core_process = None

    # ================= 订阅与配置 =================
    def download_from_node_txt(self):
        if not os.path.exists(NODE_TXT_PATH):
            messagebox.showerror("错误", "未找到 node.txt 文件！")
            return
        with open(NODE_TXT_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        valid_lines = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        if not valid_lines:
            messagebox.showwarning("提示", "你的 node.txt 中还没有有效的订阅链接！")
            return
            
        success_count = 0
        error_logs = []
        for line in valid_lines:
            if "|" in line:
                parts = line.split("|", 1)
                target_url = parts[0].strip()
                config_name = parts[1].strip()
                for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
                    config_name = config_name.replace(char, "_")
                filename = f"{config_name}.yaml"
            else:
                target_url = line
                filename = "sub_config.yaml"

            dest_path = os.path.join(CONFIG_DIR, filename)
            try:
                req = urllib.request.Request(
                    target_url, 
                    headers={'User-Agent': 'clash-meta/1.18.9 Mihomo/GUI-Manager'}
                )
                with urllib.request.urlopen(req, timeout=15) as response, open(dest_path, 'wb') as out_file:
                    out_file.write(response.read())
                success_count += 1
            except Exception as e:
                error_logs.append(f"链接 [{target_url}] 下载失败: {e}")

        self.refresh_configs()
        if success_count > 0:
            msg = f"成功下载 {success_count} 个订阅配置！"
            if error_logs: msg += f"\n部分失败：\n" + "\n".join(error_logs)
            messagebox.showinfo("完成", msg)
        else:
            messagebox.showerror("失败", "所有订阅下载均失败：\n" + "\n".join(error_logs))

    def check_sys_proxy_status(self):
        try:
            inter_set = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            server, _ = winreg.QueryValueEx(inter_set, "ProxyServer")
            enable, _ = winreg.QueryValueEx(inter_set, "ProxyEnable")
            if enable == 1:
                self.lbl_proxy_status.config(text=f"系统代理: 已开启 ({server})", foreground="green")
            else:
                self.lbl_proxy_status.config(text="系统代理: 已关闭", foreground="red")
        except Exception:
            self.lbl_proxy_status.config(text="系统代理: 未配置", foreground="gray")

    def toggle_system_proxy(self):
        try:
            inter_set = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0, winreg.KEY_WRITE | winreg.KEY_READ)
            enable, _ = winreg.QueryValueEx(inter_set, "ProxyEnable")
            new_state = 0 if enable == 1 else 1
            winreg.SetValueEx(inter_set, "ProxyEnable", 0, winreg.REG_DWORD, new_state)
            winreg.SetValueEx(inter_set, "ProxyServer", 0, winreg.REG_SZ, "127.0.0.1:7890")
            os.system('Rundll32.exe USER32.dll,UpdatePerUserSystemParameters')
            self.check_sys_proxy_status()
            messagebox.showinfo("成功", f"系统代理已{'开启' if new_state else '关闭'}")
        except Exception as e:
            messagebox.showerror("错误", f"无法修改系统代理注册表: {e}")

    def update_core(self):
        zip_dest = os.path.join(CLASH_DIR, "core.zip")
        try:
            messagebox.showinfo("提示", "开始下载内核，请耐心等待...")
            urllib.request.urlretrieve(CORE_URL, zip_dest)
            with zipfile.ZipFile(zip_dest, 'r') as zip_ref:
                for file in zip_ref.namelist():
                    if file.endswith(".exe"):
                        with open(CORE_PATH, "wb") as f_out:
                            f_out.write(zip_ref.read(file))
            os.remove(zip_dest)
            messagebox.showinfo("完成", f"内核更新成功！")
        except Exception as e:
            messagebox.showerror("异常", f"内核下载解压失败: {e}")

    def update_geo(self):
        try:
            messagebox.showinfo("提示", "正在后台下载 GeoIP/GeoSite/Country.mmdb ...")
            urllib.request.urlretrieve(GEOIP_URL, os.path.join(CLASH_DIR, "geoip.dat"))
            urllib.request.urlretrieve(GEOSITE_URL, os.path.join(CLASH_DIR, "geosite.dat"))
            urllib.request.urlretrieve(MMDB_URL, os.path.join(CLASH_DIR, "country.mmdb"))
            messagebox.showinfo("完成", "GEO 数据集全部更新成功！")
        except Exception as e:
            messagebox.showerror("异常", f"GEO 数据更新失败: {e}")

    def refresh_configs(self):
        self.config_listbox.delete(0, tk.END)
        if os.path.exists(CONFIG_DIR):
            for file in os.listdir(CONFIG_DIR):
                if file.endswith((".yaml", ".yml")):
                    self.config_listbox.insert(tk.END, file)

    def import_config(self):
        file_path = filedialog.askopenfilename(filetypes=[("YAML Files", "*.yaml *.yml")])
        if file_path:
            shutil.copy(file_path, CONFIG_DIR)
            self.refresh_configs()
            messagebox.showinfo("成功", "配置导入成功！")

    def apply_config(self):
        selected = self.config_listbox.get(tk.ACTIVE)
        if not selected:
            messagebox.showwarning("警告", "请先选择一个配置文件")
            return
        src_path = os.path.join(CONFIG_DIR, selected)
        target_path = os.path.join(CLASH_DIR, "config.yaml")
        try:
            shutil.copy(src_path, target_path)
            messagebox.showinfo("激活成功", f"当前已激活并应用配置: {selected}\n如果是运行中，请点击停止内核并重新启动。")
        except Exception as e:
            messagebox.showerror("错误", f"无法应用配置: {e}")

    def enable_tun_mode(self):
        target_path = os.path.join(CLASH_DIR, "config.yaml")
        if not os.path.exists(target_path):
            messagebox.showwarning("提示", "主目录下没有检测到活动的 config.yaml，请先应用一个配置。")
            return
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            data['tun'] = {
                'enable': True,
                'stack': 'mixed',
                'auto-route': True,
                'auto-detect-interface': True,
                'dns-hijack': ['any:53']
            }
            if 'dns' not in data or not isinstance(data['dns'], dict):
                data['dns'] = {}
            data['dns']['enable'] = True
            data['dns']['enhanced-mode'] = 'fake-ip'

            with open(target_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            messagebox.showinfo("TUN 激活", "已在 config.yaml 中成功注入并开启 TUN 模式模块！\n注意：运行 TUN 需要以管理员身份启动内核。")
        except Exception as e:
            messagebox.showerror("解析错误", f"修改 YAML 失败: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = ClashManagerGUI(root)
    root.mainloop()
