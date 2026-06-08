import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import time

# ================= 核心作战坐标 (物理级绝对钉死) =================
HOOK_ADDR   = 0x00A0C5  # 阵地一：双轨传送门
ZONE2_ADDR  = 0x2002E0  # 阵地二：入场与调度逻辑
ZONE4_ADDR  = 0x200A00  # 阵地四：弹药库首个领地起点
BLOCK_SIZE  = 0x0800    # 死锁 2048 字节

RECORD_DIR = "压缩文本迁移记录"

class KoeiCommanderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("大航海时代2压缩文本迁移工具")
        self.root.geometry("1000x800")
        
        self.rom_path = ""
        self.target_rows = []
        
        # 确保档案室存在
        if not os.path.exists(RECORD_DIR):
            os.makedirs(RECORD_DIR)

        self.setup_ui()

    def setup_ui(self):
        # ================= 顶部：雷达与指挥部 =================
        frame_top = tk.LabelFrame(self.root, text=" 📡 第一步：ROM 侦察与档案中心 ", font=("微软雅黑", 10, "bold"), padx=10, pady=10)
        frame_top.pack(fill=tk.X, padx=15, pady=10)
        
        # 选文件与扫描
        tk.Button(frame_top, text="📂 选择目标 ROM", command=self.select_file, width=15).grid(row=0, column=0, padx=5, pady=5)
        self.lbl_file = tk.Label(frame_top, text="尚未选择 ROM...", fg="red", font=("Consolas", 10))
        self.lbl_file.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        tk.Button(frame_top, text="🔍 扫描当前 ROM (逆向还原)", command=self.scan_rom, bg="#FF9800", fg="white", font=("微软雅黑", 9, "bold")).grid(row=0, column=2, padx=20)
        
        # 历史记录
        tk.Button(frame_top, text="💾 保存当前战报", command=self.save_record, bg="#2196F3", fg="white").grid(row=1, column=0, padx=5, pady=5)
        tk.Button(frame_top, text="📂 载入历史记录", command=self.load_record, bg="#4CAF50", fg="white").grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)

        # ================= 中间：弹药装填流水线 (可滚动阵地) =================
        frame_mid = tk.LabelFrame(self.root, text=" 📝 第二步：汉化阵地序列 (每块严格锁定 2KB) ", font=("微软雅黑", 10, "bold"), padx=10, pady=10)
        frame_mid.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        # Canvas 滚动条方案
        self.canvas = tk.Canvas(frame_mid)
        scrollbar = ttk.Scrollbar(frame_mid, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = tk.Frame(self.canvas)
        
        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        tk.Button(frame_mid, text="➕ 新增拦截阵地", command=self.add_target_row, bg="#9C27B0", fg="white", font=("微软雅黑", 10, "bold")).pack(side=tk.BOTTOM, pady=10)

        # 默认给一个空行
        self.add_target_row()

        # ================= 底部：最终打击 =================
        btn_execute = tk.Button(self.root, text="🚀 立即写入 ROM (物理覆盖打击) 🚀", font=("微软雅黑", 14, "bold"), bg="#D32F2F", fg="white", command=self.execute_patch)
        btn_execute.pack(fill=tk.X, padx=15, pady=15)

    def select_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("SNES ROM", "*.sfc *.smc"), ("All Files", "*.*")])
        if filepath:
            self.rom_path = filepath
            self.lbl_file.config(text=f"就绪: {os.path.basename(filepath)}", fg="green")

    def add_target_row(self, ptr_val="", hex_val=""):
        row_frame = tk.Frame(self.scroll_frame, pady=5)
        row_frame.pack(fill=tk.X, anchor=tk.W)
        
        idx = len(self.target_rows) + 1
        tk.Label(row_frame, text=f"阵地 {idx:02d} - 原指针(Hex):").pack(side=tk.LEFT)
        
        entry_ptr = tk.Entry(row_frame, width=6, font=("Consolas", 11, "bold"), justify="center")
        entry_ptr.insert(0, ptr_val)
        entry_ptr.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row_frame, text="纯汉字Hex (自动补齐2KB):").pack(side=tk.LEFT, padx=(10, 2))
        
        text_hex = tk.Text(row_frame, height=3, width=60, font=("Consolas", 9))
        text_hex.insert(tk.END, hex_val)
        text_hex.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        def del_row(f=row_frame, r_data=(entry_ptr, text_hex)):
            f.destroy()
            self.target_rows.remove(r_data)
            
        tk.Button(row_frame, text="❌", command=del_row, fg="red").pack(side=tk.LEFT, padx=5)
        self.target_rows.append((entry_ptr, text_hex))

    def clear_all_rows(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.target_rows.clear()

    # ---------------- 核心战术组件 ----------------

    def compile_payloads(self):
        """清洗UI数据，返回 (指针字符串, 补齐后的2048字节数据) 列表"""
        compiled = []
        for i, (e_ptr, t_hex) in enumerate(self.target_rows):
            ptr = e_ptr.get().strip().upper()
            raw_hex = t_hex.get("1.0", tk.END).replace(" ", "").replace("\n", "").strip()
            
            if not ptr and not raw_hex: continue
            
            if len(ptr) != 4:
                raise ValueError(f"阵地 {i+1} 指针格式错误，必须为4位字符！(当前: {ptr})")
            
            if len(raw_hex) % 2 != 0:
                raise ValueError(f"阵地 {i+1} Hex数据损坏，长度必须是偶数！")
                
            data_bytes = bytes.fromhex(raw_hex)
            if len(data_bytes) > BLOCK_SIZE:
                raise ValueError(f"🚨 红色警戒！阵地 {i+1} ({ptr}) 的数据长度 ({len(data_bytes)} 字节) 超过了物理极限 2048 字节！\n请删减内容！")
            
            # 自动填弹：用 00 撑满 2048 字节
            padded_bytes = data_bytes.ljust(BLOCK_SIZE, b'\x00')
            compiled.append((ptr, padded_bytes))
            
        return compiled

    def execute_patch(self):
        if not self.rom_path:
            messagebox.showerror("错误", "长官，请先选择目标 ROM！")
            return
            
        try:
            targets = self.compile_payloads()
            if not targets:
                messagebox.showwarning("空仓告警", "没有检测到任何弹药部署！")
                return
                
            N = len(targets)
            
            # ================= 1. 组装阵地二 (入场逻辑) =================
            zone2 = bytearray([0xA5, 0x56]) # LDA $56
            for i, (ptr, _) in enumerate(targets):
                p_bytes = bytes.fromhex(ptr)[::-1] # 小端翻转
                zone2.extend([0xC9, p_bytes[0], p_bytes[1]]) # CMP
                
                # 核心相对跳转公式
                jump_offset = (N - 1 - i) * 5 + 15 
                zone2.extend([0xF0, jump_offset]) # BEQ
                
            # 公共放行与陷阱压栈
            zone2.extend(bytes.fromhex("48 A5 54 48 A5 58 E2 20 F4 D1 A0 5C 4C A2 C0"))
            zone2.extend(bytes.fromhex("48 A5 54 48 A5 58 E2 20 F4 C8 A0 5C 4C A2 C0"))
            
            # 计算阵地三起点坐标 (用于阵地一的返程票)
            z3_phys_addr = ZONE2_ADDR + len(zone2)
            z3_snes_low = z3_phys_addr & 0xFF
            z3_snes_high = (z3_phys_addr >> 8) & 0xFF
            
            # ================= 2. 组装阵地一 (双轨传送门) =================
            hook_bytes = bytearray(bytes.fromhex("5C E0 02 E0")) # 去程永远不变
            hook_bytes.extend([0x5C, z3_snes_low, z3_snes_high, 0xE0]) # 返程动态对齐
            
            # ================= 3. 组装阵地三 (覆写逻辑) =================
            zone3 = bytearray(bytes.fromhex("8B C2 30 A5 56")) # 前置保护
            for i, (ptr, _) in enumerate(targets):
                p_bytes = bytes.fromhex(ptr)[::-1]
                zone3.extend([0xC9, p_bytes[0], p_bytes[1]]) # CMP
                zone3.extend([0xD0, 0x05]) # BNE (不相等则跳过接下来5个字节)
                
                # 自动指派 2048 步长仓库 (0A00, 1200...)
                payload_snes = 0x0A00 + i * BLOCK_SIZE
                p_low = payload_snes & 0xFF
                p_high = (payload_snes >> 8) & 0xFF
                zone3.extend([0xA2, p_low, p_high]) # LDX
                
                jump_offset = (N - 1 - i) * 10
                zone3.extend([0x80, jump_offset]) # BRA (跳到最后执行拷贝)
                
            # 统一 MVN 与撤退
            zone3.extend(bytes.fromhex("A4 54 A9 FF 07 54 7F E0 AB E2 10 5C D2 A0 C0"))
            
            # ================= 4. 组装阵地四 (纯数据) =================
            zone4 = bytearray()
            for _, p_bytes in targets:
                zone4.extend(p_bytes)
                
            # === 执行物理打击 ===
            with open(self.rom_path, 'r+b') as f:
                f.seek(HOOK_ADDR)
                f.write(hook_bytes)
                
                f.seek(ZONE2_ADDR)
                f.write(zone2)
                f.write(zone3) # 阵地三紧贴阵地二
                
                f.seek(ZONE4_ADDR)
                f.write(zone4)
                
            msg = f"物理打击圆满成功！\n\n✅ 成功接管 {N} 个阵地\n✅ 阵地三安全边界退至: 0x{z3_phys_addr:06X}\n✅ 弹药库写入: {len(zone4)} 字节"
            messagebox.showinfo("战役胜利", msg)
            
        except Exception as e:
            messagebox.showerror("系统崩溃", f"发生致命错误:\n{str(e)}")

    # ---------------- 扫描与侦察系统 ----------------
    def scan_rom(self):
        if not self.rom_path:
            messagebox.showerror("错误", "请先选择要扫描的 ROM 文件！")
            return
            
        try:
            with open(self.rom_path, 'rb') as f:
                f.seek(HOOK_ADDR)
                hook_check = f.read(4)
                if hook_check != bytes.fromhex("5CE002E0"):
                    messagebox.showinfo("侦察报告", "报告长官！这是一个未修改的原版 ROM（或被其他势力占领），未侦测到我们的基地。")
                    return
                
                # 确认友军，开启扫雷
                f.seek(ZONE2_ADDR + 2) # 跳过初始的 A5 56
                found_targets = []
                
                while True:
                    op = f.read(1)
                    if op == b'\x48': # 压栈指令，代表判断循环结束
                        break
                    if op == b'\xC9':
                        ptr_b = f.read(2)
                        ptr_str = f"{ptr_b[1]:02X}{ptr_b[0]:02X}" # 小端翻回
                        f.read(2) # 跳过 F0 XX
                        found_targets.append(ptr_str)
                
                if not found_targets:
                    messagebox.showinfo("侦察报告", "雷达扫描完毕，该 ROM 虽有引擎框架，但无任何文本记录。")
                    return
                    
                # 挖出弹药
                self.clear_all_rows()
                for i, ptr in enumerate(found_targets):
                    f.seek(ZONE4_ADDR + i * BLOCK_SIZE)
                    data_chunk = f.read(BLOCK_SIZE).rstrip(b'\x00') # 剥离用于占位的0
                    hex_str = data_chunk.hex(" ").upper()
                    self.add_target_row(ptr, hex_str)
                    
                messagebox.showinfo("雷达截获", f"雷达扫描完毕！\n成功提取出 {len(found_targets)} 个历史作战阵地，已还原至指挥终端！")
                    
        except Exception as e:
            messagebox.showerror("扫描故障", f"读取出错: {str(e)}")

    # ---------------- 档案系统 ----------------
    def save_record(self):
        try:
            targets = self.compile_payloads()
            if not targets:
                messagebox.showwarning("警告", "当前无作战数据可保存！")
                return
                
            filename = f"汉化战报_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(RECORD_DIR, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                for ptr, data in targets:
                    f.write(f"[{ptr}]\n")
                    # 只保存有效长度，去掉尾部为了物理填仓补充的 00
                    real_data = data.rstrip(b'\x00').hex(" ").upper()
                    # 分行写入，更美观
                    for i in range(0, len(real_data), 48): 
                        f.write(real_data[i:i+48] + "\n")
                    f.write("\n")
                    
            messagebox.showinfo("归档成功", f"当前战列序列已安全入档：\n{filename}")
        except Exception as e:
            messagebox.showerror("归档失败", str(e))

    def load_record(self):
        filepath = filedialog.askopenfilename(initialdir=RECORD_DIR, filetypes=[("Text Files", "*.txt")])
        if not filepath: return
        
        try:
            self.clear_all_rows()
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            current_ptr = ""
            current_hex = ""
            
            for line in lines:
                line = line.strip()
                if not line: continue
                if line.startswith("[") and line.endswith("]"):
                    # 如果有上一个，先推入 UI
                    if current_ptr:
                        self.add_target_row(current_ptr, current_hex.strip())
                    current_ptr = line[1:-1]
                    current_hex = ""
                else:
                    current_hex += line + " "
                    
            # 推入最后一个
            if current_ptr:
                self.add_target_row(current_ptr, current_hex.strip())
                
            messagebox.showinfo("读取成功", "战情档案载入完毕，随时可以执行二次打击！")
            
        except Exception as e:
            messagebox.showerror("读取失败", f"档案损坏或格式错误:\n{str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = KoeiCommanderApp(root)
    root.mainloop()