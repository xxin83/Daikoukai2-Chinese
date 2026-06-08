# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os

class AdvancedRomTranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("汉化单句文本控制与溢出校验工具 (安全增强版)")
        self.root.geometry("1000x850") 

        # 核心码表映射缓存
        self.normal_to_char = {}
        self.char_to_normal = {}
        self.hiragana_to_char = {}
        self.char_to_hiragana = {}
        self.complement_table = {} 

        # 文本与句子管理缓存
        self.hex_sentences = []          # 拆分后的原始十六进制句子列表
        self.modified_texts = []         # 存放用户修改后的文本缓存
        self.current_index = -1          # 当前正在编辑的句子索引

        self.create_widgets()

    def create_widgets(self):
        """初始化构建现代化 UI 界面布局"""
        # ==================== 1. 码表加载与配置区 ====================
        file_frame = ttk.LabelFrame(self.root, text=" 1. 加载码表与工具配置 ", padding=10)
        file_frame.pack(fill="x", padx=15, pady=5)

        ttk.Button(file_frame, text="加载普通码表 (.tbl/.txt)", command=self.load_normal_tbl).grid(row=0, column=0, padx=5, pady=3, sticky="w")
        self.lbl_normal = ttk.Label(file_frame, text="未加载", foreground="gray")
        self.lbl_normal.grid(row=0, column=1, padx=10, pady=3, sticky="w")

        ttk.Button(file_frame, text="加载平假名码表 (.tbl/.txt)", command=self.load_hiragana_tbl).grid(row=1, column=0, padx=5, pady=3, sticky="w")
        self.lbl_hiragana = ttk.Label(file_frame, text="未加载", foreground="gray")
        self.lbl_hiragana.grid(row=1, column=1, padx=10, pady=3, sticky="w")

        ttk.Button(file_frame, text="加载繁简互补表 (.txt)", command=self.load_complement_tbl).grid(row=2, column=0, padx=5, pady=3, sticky="w")
        self.lbl_complement = ttk.Label(file_frame, text="未加载", foreground="gray")
        self.lbl_complement.grid(row=2, column=1, padx=10, pady=3, sticky="w")


        # ==================== 2. 双栏联动核心工作区 ====================
        workspace_frame = ttk.Frame(self.root, padding=5)
        workspace_frame.pack(fill="both", expand=True, padx=15, pady=5)

        # ---- 左侧栏：大文本全量十六进制原始编码输入与集成块 (框1) ----
        left_frame = ttk.LabelFrame(workspace_frame, text=" 2. 全量编码输入与导出阵地 ", padding=5)
        left_frame.pack(side="left", fill="both", expand=True, padx=5)

        ttk.Label(left_frame, text="【框1】在此粘贴全量原始 Hex 编码 (自动以 00 分句):").pack(anchor="w", padx=5)
        self.txt_box1_full_hex = tk.Text(left_frame, width=35, wrap="word")
        self.txt_box1_full_hex.pack(fill="both", expand=True, padx=5, pady=5)

        btn_analyze = ttk.Button(left_frame, text="🔥 执行大文本智能分句解析", command=self.analyze_and_split_hex)
        btn_analyze.pack(fill="x", padx=5, pady=3)

        btn_save_all = ttk.Button(left_frame, text="💾 导出全量汉化编码 (.txt)", command=self.save_all_hex_to_txt)
        btn_save_all.pack(fill="x", padx=5, pady=5)


        # ---- 右侧栏：单句精细化交互、动态编译与溢出/缺字校验台 (框2, 3, 4) ----
        right_frame = ttk.LabelFrame(workspace_frame, text=" 3. 单句精修与多模态属性絕對校验控制台 ", padding=5)
        right_frame.pack(side="right", fill="both", expand=True, padx=5)

        # 线性导航面板
        nav_frame = ttk.Frame(right_frame, padding=5)
        nav_frame.pack(fill="x", pady=2)
        self.btn_prev = ttk.Button(nav_frame, text="◀ 上一句", command=self.nav_prev, state="disabled")
        self.btn_prev.pack(side="left", padx=10)
        self.lbl_nav_status = ttk.Label(nav_frame, text="暂无句子载入", font=("Arial", 11, "bold"))
        self.lbl_nav_status.pack(side="left", expand=True)
        self.btn_next = ttk.Button(nav_frame, text="下一句 ▶", command=self.nav_next, state="disabled")
        self.btn_next.pack(side="right", padx=10)

        # 框2：原始文本静态映射参考
        ttk.Label(right_frame, text="【框2】当前句·原始文本反查展示 (只读):").pack(anchor="w", padx=5)
        self.txt_box2_orig_text = tk.Text(right_frame, height=4, wrap="word", bg="#f4f4f4", state="disabled")
        self.txt_box2_orig_text.pack(fill="x", padx=5, pady=2)

        # 框3：核心修改交互框
        ttk.Label(right_frame, text="【框3】当前句·汉化修改文本输入区 (支持即时校验):").pack(anchor="w", padx=5)
        self.txt_box3_mod_text = tk.Text(right_frame, height=5, wrap="word")
        self.txt_box3_mod_text.pack(fill="x", padx=5, pady=2)
        # 挂载键盘事件，保持在用户输入期间进行高频校验
        self.txt_box3_mod_text.bind("<KeyRelease>", lambda e: self.validate_current_sentence())

        # 框4：实时动态编译结果
        ttk.Label(right_frame, text="【框4】当前句·实时编译生成的十六进制编码:").pack(anchor="w", padx=5)
        self.txt_box4_new_hex = tk.Text(right_frame, height=4, wrap="word", bg="#f4f4f4", state="disabled")
        self.txt_box4_new_hex.pack(fill="x", padx=5, pady=2)

        # 状态可视化大看板
        self.lbl_validation_board = tk.Label(
            right_frame, 
            text="等待解析句子...", 
            font=("Microsoft YaHei", 11, "bold"), 
            bg="#dcdcdc", 
            anchor="center",
            padx=8,
            pady=8
        )
        self.lbl_validation_board.pack(fill="x", padx=5, pady=10)

    # ==================== 基础数据源加载与解析 ====================
    def parse_tbl(self, filepath):
        """解析标准和特殊扩展 TBL 文本码表"""
        fwd, rev = {}, {}
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line:
                        parts = line.split('=', 1)
                        hex_str = parts[0].strip().upper().replace(" ", "")
                        char_str = parts[1]
                        if hex_str and char_str:
                            fwd[hex_str] = char_str
                            rev[char_str] = hex_str
            return fwd, rev
        except Exception as e:
            messagebox.showerror("错误", f"读取码表失败: {str(e)}")
            return {}, {}

    def load_normal_tbl(self):
        path = filedialog.askopenfilename(filetypes=[("Table Files", "*.tbl *.txt"), ("All Files", "*.*")])
        if path:
            self.normal_to_char, self.char_to_normal = self.parse_tbl(path)
            self.lbl_normal.config(text=f"已加载 ({len(self.normal_to_char)} 条) - {os.path.basename(path)}", foreground="green")
            if self.current_index >= 0: self.refresh_workspace()

    def load_hiragana_tbl(self):
        path = filedialog.askopenfilename(filetypes=[("Table Files", "*.tbl *.txt"), ("All Files", "*.*")])
        if path:
            self.hiragana_to_char, self.char_to_hiragana = self.parse_tbl(path)
            self.lbl_hiragana.config(text=f"已加载 ({len(self.hiragana_to_char)} 条) - {os.path.basename(path)}", foreground="green")
            if self.current_index >= 0: self.refresh_workspace()

    def load_complement_tbl(self):
        path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if path:
            self.complement_table.clear()
            try:
                count = 0
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if '=' in line:
                            parts = line.split('=', 1)
                            c1, c2 = parts[0].strip(), parts[1].strip()
                            if c1 and c2:
                                self.complement_table[c1] = c2
                                self.complement_table[c2] = c1
                                count += 1
                self.lbl_complement.config(text=f"已加载 ({count} 组双向) - {os.path.basename(path)}", foreground="green")
                if self.current_index >= 0: self.refresh_workspace()
            except Exception as e:
                messagebox.showerror("错误", f"读取繁简互补表失败: {str(e)}")

    # ==================== 核心逻辑：智能无损分句机制 ====================
    def analyze_and_split_hex(self):
        """清洗框1原始十六进制文本，并按 00 终结符切分"""
        raw_hex = self.txt_box1_full_hex.get("1.0", tk.END).strip().upper().replace(" ", "").replace("\n", "").replace("\r", "")
        if not raw_hex:
            messagebox.showwarning("提示", "请先在框1中输入全量十六进制编码！")
            return
        if len(raw_hex) % 2 != 0:
            messagebox.showerror("错误", "输入的十六进制字符总数必须为偶数（确保字节完整）！")
            return

        bytes_list = [raw_hex[i:i+2] for i in range(0, len(raw_hex), 2)]
        
        self.hex_sentences = []
        current_sentence = []
        
        for b in bytes_list:
            current_sentence.append(b)
            if b == "00":
                self.hex_sentences.append("".join(current_sentence))
                current_sentence = []
        if current_sentence: 
            self.hex_sentences.append("".join(current_sentence))

        if not self.hex_sentences:
            messagebox.showinfo("提示", "未能识别出有效的句子。")
            return

        self.modified_texts = [None] * len(self.hex_sentences)
        self.current_index = 0
        
        self.refresh_workspace()
        messagebox.showinfo("成功", f"全量文本分句成功！共拆分出 {len(self.hex_sentences)} 句。")

    # ==================== 核心功能：工作流状态刷新 ====================
    def save_current_edit_cache(self):
        """将右侧编辑结果暂存到对应句子索引的内存缓存中"""
        if self.current_index >= 0 and self.current_index < len(self.hex_sentences):
            self.modified_texts[self.current_index] = self.txt_box3_mod_text.get("1.0", tk.END).strip()

    def refresh_workspace(self):
        """渲染更新当前选定句子的所有面板内容"""
        if self.current_index < 0 or self.current_index >= len(self.hex_sentences):
            return

        self.lbl_nav_status.config(text=f"当前第 {self.current_index + 1} / {len(self.hex_sentences)} 句")
        self.btn_prev.config(state="normal" if self.current_index > 0 else "disabled")
        self.btn_next.config(state="normal" if self.current_index < len(self.hex_sentences) - 1 else "disabled")

        current_orig_hex = self.hex_sentences[self.current_index]
        decoded_text = self.decode_hex_to_text(current_orig_hex)

        self.txt_box2_orig_text.config(state="normal")
        self.txt_box2_orig_text.delete("1.0", tk.END)
        self.txt_box2_orig_text.insert("1.0", decoded_text)
        self.txt_box2_orig_text.config(state="disabled")

        self.txt_box3_mod_text.delete("1.0", tk.END)
        if self.modified_texts[self.current_index] is not None:
            self.txt_box3_mod_text.insert("1.0", self.modified_texts[self.current_index])
        else:
            self.txt_box3_mod_text.insert("1.0", decoded_text)

        self.validate_current_sentence()

    def nav_prev(self):
        self.save_current_edit_cache()
        self.current_index -= 1
        self.refresh_workspace()

    def nav_next(self):
        self.save_current_edit_cache()
        self.current_index += 1
        self.refresh_workspace()

    # ==================== 核心算法：变长多状态单句解码 ====================
    def decode_hex_to_text(self, raw_hex):
        output_text = []
        is_hiragana_mode = False
        i = 0
        length = len(raw_hex)

        while i < length:
            if raw_hex[i:i+2] == "00":
                i += 2
                continue
            if raw_hex[i:i+4] == "1B4B":
                is_hiragana_mode = True
                i += 4
                continue
            elif raw_hex[i:i+4] == "1B48":
                is_hiragana_mode = False
                i += 4
                continue

            active_tbl = self.hiragana_to_char if is_hiragana_mode else self.normal_to_char
            key_lengths = sorted(list(set(len(k) for k in active_tbl.keys())), reverse=True)
            if not key_lengths: key_lengths = [2]

            matched = False
            for kl in key_lengths:
                if i + kl <= length:
                    sub_hex = raw_hex[i:i+kl]
                    if sub_hex in active_tbl:
                        output_text.append(active_tbl[sub_hex])
                        i += kl
                        matched = True
                        break
            if not matched:
                output_text.append(f"[?{raw_hex[i:i+2]}]")
                i += 2
        return "".join(output_text)

    # ==================== 核心算法：高级动态全编译引擎 (带字模缺失捕获) ====================
    def compile_text_to_hex(self, text, orig_hex):
        output_hex_list = []
        is_hiragana_mode = False
        missing_chars = set()  # 精确存储该段文本中所有缺失的汉字集合
        
        i = 0
        text_len = len(text)

        while i < text_len:
            if not is_hiragana_mode:
                current_rev = self.char_to_normal
                other_rev = self.char_to_hiragana
                switch_code = "1B4B"
                other_mode = True
            else:
                current_rev = self.char_to_hiragana
                other_rev = self.char_to_normal
                switch_code = "1B48"
                other_mode = False

            # 阶段 1：优先检索并匹配当前处于激活状态的码表
            current_lengths = sorted(list(set(len(k) for k in current_rev.keys())), reverse=True)
            matched = False
            
            for l in current_lengths:
                if i + l <= text_len:
                    sub_text = text[i:i+l]
                    if sub_text in current_rev:
                        output_hex_list.append(current_rev[sub_text])
                        i += l
                        matched = True
                        break
                    elif l == 1 and sub_text in self.complement_table:
                        variant = self.complement_table[sub_text]
                        if variant in current_rev:
                            output_hex_list.append(current_rev[variant])
                            i += l
                            matched = True
                            break
            if matched:
                continue

            # 阶段 2：激活表匹配失败，尝试副表匹配并自动计算控制切换码
            other_lengths = sorted(list(set(len(k) for k in other_rev.keys())), reverse=True)
            switch_matched = False
            
            for l in other_lengths:
                if i + l <= text_len:
                    sub_text = text[i:i+l]
                    if sub_text in other_rev:
                        output_hex_list.append(switch_code)
                        is_hiragana_mode = other_mode
                        output_hex_list.append(other_rev[sub_text])
                        i += l
                        switch_matched = True
                        break
                    elif l == 1 and sub_text in self.complement_table:
                        variant = self.complement_table[sub_text]
                        if variant in other_rev:
                            output_hex_list.append(switch_code)
                            is_hiragana_mode = other_mode
                            output_hex_list.append(other_rev[variant])
                            i += l
                            switch_matched = True
                            break
            if switch_matched:
                continue

            # 阶段 3：如果主表、副表及繁简替换表全面查询失败，抛出缺失异常，记录字符并进行盲区处理
            missing_chars.add(text[i])
            output_hex_list.append("3F")  # 生成3F占位，但不再默默放行
            i += 1

        # 闭合原始句子的句尾结束符
        if orig_hex.endswith("00"):
            output_hex_list.append("00")

        return "".join(output_hex_list), missing_chars

    # ==================== 核心算法：实时高频属性综合校验渲染 ====================
    def validate_current_sentence(self):
        if self.current_index < 0: return

        mod_text = self.txt_box3_mod_text.get("1.0", tk.END).strip()
        orig_hex = self.hex_sentences[self.current_index]
        
        # 实时动态编译转换
        new_hex_raw, missing_chars = self.compile_text_to_hex(mod_text, orig_hex)
        
        # 将新生成的纯编码格式化输出至【框4】
        formatted_hex = " ".join(new_hex_raw[i:i+2] for i in range(0, len(new_hex_raw), 2)).upper()
        self.txt_box4_new_hex.config(state="normal")
        self.txt_box4_new_hex.delete("1.0", tk.END)
        self.txt_box4_new_hex.insert("1.0", formatted_hex)
        self.txt_box4_new_hex.config(state="disabled")

        # 长度字节测算
        orig_bytes_len = len(orig_hex) // 2
        new_bytes_len = len(new_hex_raw) // 2
        diff = new_bytes_len - orig_bytes_len

        # 属性决策模型选择可视化主题
        if diff > 0:
            len_status = f"❌ 严重溢出！超长 {diff} 字节 (可能导致游戏死机或文本被截断)"
            bg_color = "#FFC0CB" 
            fg_color = "#CC0000"
        elif diff == 0:
            len_status = "✅ 完美契合！长度与原版完全一致"
            bg_color = "#E0EEE0" 
            fg_color = "#006400"
        else:
            len_status = f"⚠️ 空间充足！尚余 {-diff} 字节未使用 (请使用空格或00填充)"
            bg_color = "#E0FFFF" 
            fg_color = "#00008B"

        board_text = f"原始长度: {orig_bytes_len} 字节  |  当前长度: {new_bytes_len} 字节  |  {len_status}"

        # 🚨 第一重安全锁：如果单句中存在缺失字符，立刻在看板拦截展示
        if missing_chars:
            missing_list_str = " ， ".join([f"\"{c}\"=缺失" for c in sorted(list(missing_chars))])
            board_text += f"\n🚫 缺失警报：检测到码表未收录字模 ➡️  {missing_list_str}"
            bg_color = "#FFE4E1" 
            fg_color = "#CD5C5C"
            if diff > 0:
                bg_color = "#FFC0CB" # 溢出级别更高，保持深红警示
                fg_color = "#CC0000"

        self.lbl_validation_board.config(text=board_text, bg=bg_color, foreground=fg_color)

    # ==================== 核心逻辑：安全集成导出连续纯 Hex 编码 ====================
    def save_all_hex_to_txt(self):
        if not self.hex_sentences:
            messagebox.showwarning("提示", "当前没有解析任何句子，请先在框1输入编码并执行分句！")
            return
        
        # 强制同步当前处于正在编辑状态的数据至全局缓存
        self.save_current_edit_cache()
        
        try:
            all_hex_output = []
            global_missing_chars = set() # 汇聚全文本中全部缺失的异常字
            
            for i, orig_hex in enumerate(self.hex_sentences):
                mod_text = self.modified_texts[i]
                
                if mod_text is not None:
                    # 激活过或修改过的句子采用最新翻译重新编译
                    compiled_hex, missing_chars = self.compile_text_to_hex(mod_text, orig_hex)
                    all_hex_output.append(compiled_hex)
                    global_missing_chars.update(missing_chars)
                else:
                    # 未作改动的文本采用原样十六进制，保证100%不对健康文本造成破坏
                    all_hex_output.append(orig_hex)
            
            # 🚨 第二重安全锁：终极拦截。导出时如果有漏网之鱼，罗列全部缺失汉字供人工核对决策
            if global_missing_chars:
                missing_summary = "  ".join([f"[{c}]=缺失" for c in sorted(list(global_missing_chars))])
                confirm = messagebox.askyesno(
                    "⚠️ 码表缺失字模终极拦截", 
                    f"在即将导出的汉化文本中发现了未录入码表的汉字：\n\n{missing_summary}\n\n"
                    f"如果执意导出，这些缺失字会用 3F 代替（在游戏中可能会乱码或显示问号）。\n\n"
                    f"您确定仍要继续导出编码文件吗？"
                )
                if not confirm:
                    return # 用户拒绝，中断导出回去校正码表

            # 保存并拉起文件保存会话窗口
            path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
                title="保存全量纯十六进制编码文件"
            )
            if not path: return
            
            # 纯编码无缝拼接输出（无额外字符、空格或折行）
            full_hex_string = "".join(all_hex_output).upper()
            with open(path, 'w', encoding='utf-8') as f:
                f.write(full_hex_string)
                
            messagebox.showinfo("成功", f"恭喜！全量汉化纯Hex编码文件已安全导出：\n{path}")
        except Exception as e:
            messagebox.showerror("错误", f"保存编码文件失败: {str(e)}")


if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    style.theme_use("clam")
    app = AdvancedRomTranslatorApp(root)
    root.mainloop()