#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
from pathlib import Path
import re
import unicodedata
from datetime import datetime
import csv
import json
import uuid

PTR_START_DEFAULT = 0x0B561D
PTR_COUNT_DEFAULT = 0
TEXT_START_DEFAULT = None
BANK_BASE_DEFAULT = 0xC0
END_BYTE = 0x00
PTR_ORDER_DEFAULT = "lo_hi_bank"
PTR_ORDER_OPTIONS = ["lo_hi_bank", "bank_lo_hi", "hi_lo_bank"]
READ_MODE_POINTER = "pointer_block"
READ_MODE_DIRECT = "direct_text"
READ_MODE_OPTIONS = [READ_MODE_POINTER, READ_MODE_DIRECT]

TABLE_RE = re.compile(r"^\s*([0-9A-Fa-f]{2,6})=(.*)\s*$")
ID_LINE_RE = re.compile(r"^\s*\[ID:\s*(\d+)\s*\]")


def parse_hex_flexible(s):
    t = (s or "").strip().replace("，", " ").replace(",", " ")
    t = t.replace("0x", "").replace("0X", "")
    # 仅保留十六进制字符与空白，便于手工输入时容错
    cleaned = "".join(ch if (ch in "0123456789abcdefABCDEF" or ch.isspace()) else " " for ch in t)
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return b""
    # 允许写成连续串: 89A01B4B
    if len(parts) == 1 and len(parts[0]) > 2 and len(parts[0]) % 2 == 0:
        parts = [parts[0][i:i + 2] for i in range(0, len(parts[0]), 2)]
    for p in parts:
        if len(p) != 2:
            raise ValueError(f"HEX字节长度应为2: {p}")
    return bytes(int(p, 16) for p in parts)


def parse_hex_lossy(s):
    """永不抛错: 从任意字符串中尽量提取 2位HEX 字节对。"""
    t = (s or "").replace("0x", "").replace("0X", "")
    pairs = re.findall(r"[0-9A-Fa-f]{2}", t)
    if not pairs:
        return b""
    return bytes(int(p, 16) for p in pairs)


class TableCodec:
    def __init__(self):
        self.normal_code_to_token = {}  # bytes -> str
        self.kata_code_to_token = {}    # bytes -> str
        self.code_to_token = {}         # merged bytes -> str (for fallback)
        self.token_to_code = {}         # merged token -> bytes (for encode)
        self.max_code_len = 1
        self.warnings = []
        self.alias_map = {}
        self._init_default_aliases()

    def _init_default_aliases(self):
        # 默认常见字形别名（可被外部字典扩展）
        defaults = {
            "你": ["妳"],
            "妳": ["你"],
            "并": ["並"],
            "並": ["并"],
            "么": ["麼"],
            "麼": ["么"],
            "厂": ["廠"],
            "廠": ["厂"],
            "万": ["萬"],
            "萬": ["万"],
        }
        self.alias_map = {}
        for k, arr in defaults.items():
            self.alias_map.setdefault(k, [])
            for x in arr:
                if x not in self.alias_map[k]:
                    self.alias_map[k].append(x)

    def load_aliases(self, path):
        """
        加载别名字典:
        - 每行格式: 你=妳
        - 或: 你=妳,祢
        - 注释行: # ...
        """
        p = Path(path)
        raw = p.read_bytes()
        text = None
        for enc in ("utf-8-sig", "utf-8", "gb18030", "cp936", "big5", "cp932"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")

        cnt = 0
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            a, b = s.split("=", 1)
            a = a.strip()
            if not a:
                continue
            bs = [x.strip() for x in b.replace("，", ",").split(",") if x.strip()]
            if not bs:
                continue
            self.alias_map.setdefault(a, [])
            for x in bs:
                if x not in self.alias_map[a]:
                    self.alias_map[a].append(x)
                    cnt += 1
                # 双向补一条，查询更稳
                self.alias_map.setdefault(x, [])
                if a not in self.alias_map[x]:
                    self.alias_map[x].append(a)
        return cnt

    def _candidate_tokens(self, ch):
        # 编码候选顺序：原字 -> NFKC -> 别名
        cands = [ch]
        nfk = unicodedata.normalize("NFKC", ch)
        if nfk not in cands:
            cands.append(nfk)
        for a in self.alias_map.get(ch, []):
            if a not in cands:
                cands.append(a)
        for a in self.alias_map.get(nfk, []):
            if a not in cands:
                cands.append(a)
        return cands

    def _decode_text_auto(self, raw):
        # 优先 UTF，避免 UTF 码表被 GBK/CP936 误解码后产生错字映射
        for enc in ("utf-8-sig", "utf-8", "gb18030", "cp936", "big5", "cp932"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="replace")

    def _parse_table_text(self, text, src_name):
        mp = {}
        max_len = 1
        for line in text.splitlines():
            m = TABLE_RE.match(line)
            if not m:
                continue
            h = m.group(1)
            rhs = m.group(2)
            try:
                b = bytes.fromhex(h)
            except Exception:
                continue
            if not rhs:
                continue
            mp[b] = rhs
            if len(b) > max_len:
                max_len = len(b)
        return mp, max_len

    def load_tables(self, normal_path=None, kata_path=None):
        self.normal_code_to_token.clear()
        self.kata_code_to_token.clear()
        self.code_to_token.clear()
        self.token_to_code.clear()
        self.max_code_len = 1
        self.warnings = []

        if normal_path:
            raw = Path(normal_path).read_bytes()
            text = self._decode_text_auto(raw)
            mp, mx = self._parse_table_text(text, Path(normal_path).name)
            self.normal_code_to_token.update(mp)
            self.max_code_len = max(self.max_code_len, mx)

        if kata_path:
            raw = Path(kata_path).read_bytes()
            text = self._decode_text_auto(raw)
            mp, mx = self._parse_table_text(text, Path(kata_path).name)
            self.kata_code_to_token.update(mp)
            self.max_code_len = max(self.max_code_len, mx)

        # merged map: normal first, kata fill missing
        self.code_to_token.update(self.normal_code_to_token)
        for k, v in self.kata_code_to_token.items():
            if k not in self.code_to_token:
                self.code_to_token[k] = v

        # encode map: normal first, kata fill missing token
        for k, v in self.normal_code_to_token.items():
            if v in self.token_to_code and self.token_to_code[v] != k:
                old = self.token_to_code[v]
                self.warnings.append(f"normal: token重复 '{v}' -> {old.hex().upper()} 被 {k.hex().upper()} 覆盖")
            self.token_to_code[v] = k
        for k, v in self.kata_code_to_token.items():
            if v not in self.token_to_code:
                self.token_to_code[v] = k

    def decode_bytes(self, bs):
        out = []
        i = 0
        n = len(bs)
        is_kata_mode = False
        while i < n:
            # 片假名模式开关控制符，编辑器内忽略显示
            if i + 1 < n and bs[i] == 0x1B:
                if bs[i + 1] == 0x4B:
                    is_kata_mode = True
                    i += 2
                    continue
                if bs[i + 1] == 0x48:
                    is_kata_mode = False
                    i += 2
                    continue
            matched = False
            active = self.kata_code_to_token if is_kata_mode else self.normal_code_to_token
            other = self.normal_code_to_token if is_kata_mode else self.kata_code_to_token
            for ln in range(self.max_code_len, 0, -1):
                if i + ln > n:
                    continue
                sub = bs[i:i + ln]
                if sub in active:
                    out.append(active[sub])
                    i += ln
                    matched = True
                    break
                if sub in other:
                    out.append(other[sub])
                    i += ln
                    matched = True
                    break
            if not matched:
                out.append(f"【{bs[i]:02X}】")
                i += 1
        return "".join(out)

    def encode_text(self, s):
        out = bytearray()
        # 允许人工输入控制码标记并忽略（避免触发未编码字符）
        s = s.replace("【片假名开】", "").replace("【片假名关】", "")
        i = 0
        n = len(s)
        while i < n:
            # 支持未识别字节占位符: 【XX】
            if s[i] == "【":
                m2 = re.match(r"^【未知:([0-9A-Fa-f]{2})】", s[i:])
                if m2:
                    out.append(int(m2.group(1), 16))
                    i += len(m2.group(0))
                    continue
                m = re.match(r"^【([0-9A-Fa-f]{2})】", s[i:])
                if m:
                    out.append(int(m.group(1), 16))
                    i += len(m.group(0))
                    continue
            ch = s[i]
            if ch == "[":
                j = s.find("]", i + 1)
                if j != -1:
                    tok = s[i:j + 1]
                    if tok in self.token_to_code:
                        out.extend(self.token_to_code[tok])
                        i = j + 1
                        continue
            encoded = False
            for cand in self._candidate_tokens(ch):
                if cand in self.token_to_code:
                    out.extend(self.token_to_code[cand])
                    encoded = True
                    break
            if encoded:
                i += 1
                continue
            line = s.count("\n", 0, i) + 1
            line_start = s.rfind("\n", 0, i)
            if line_start < 0:
                col = i + 1
            else:
                col = i - line_start
            ctx_l = max(0, i - 12)
            ctx_r = min(len(s), i + 12)
            ctx = s[ctx_l:ctx_r].replace("\n", "\\n")
            raise ValueError(f"未编码字符: {ch} (line={line}, col={col}, idx={i}, ctx='{ctx}')")
        return bytes(out)


def ptr_to_pc(bank, off, bank_base):
    # 项目内使用: PC = (bank - bank_base) << 16 | off
    return ((bank - bank_base) << 16) | off


def pc_to_ptr(pc, bank_base):
    bank = bank_base + ((pc >> 16) & 0xFF)
    off = pc & 0xFFFF
    return bank & 0xFF, off & 0xFFFF


def unpack_ptr3(b0, b1, b2, order):
    if order == "bank_lo_hi":
        bank = b0
        lo = b1
        hi = b2
    elif order == "hi_lo_bank":
        hi = b0
        lo = b1
        bank = b2
    else:
        # default: lo_hi_bank
        lo = b0
        hi = b1
        bank = b2
    off = lo | (hi << 8)
    return bank & 0xFF, off & 0xFFFF


def pack_ptr3(bank, off, order):
    lo = off & 0xFF
    hi = (off >> 8) & 0xFF
    if order == "bank_lo_hi":
        return (bank & 0xFF, lo, hi)
    if order == "hi_lo_bank":
        return (hi, lo, bank & 0xFF)
    # default: lo_hi_bank
    return (lo, hi, bank & 0xFF)


def merge_ranges(ranges):
    if not ranges:
        return []
    ranges = sorted(ranges, key=lambda x: x[0])
    out = [list(ranges[0])]
    for s, e in ranges[1:]:
        if s <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def fmt_hex(v, w=6):
    if v is None or v < 0:
        return "<NA>"
    return f"0x{v:0{w}X}"


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("ROM 指针文本编辑器 (可切换指针字节序)")
        self.root.geometry("1080x760")

        self.codec = TableCodec()
        self.rom_path = None
        self.rom_bytes = None

        self.ptr_start = PTR_START_DEFAULT
        self.ptr_count = PTR_COUNT_DEFAULT
        self.text_start = TEXT_START_DEFAULT
        self.bank_base = BANK_BASE_DEFAULT
        self.ptr_order = PTR_ORDER_DEFAULT
        self.read_mode = READ_MODE_POINTER
        self.direct_count = 200

        self.entries = []  # [{id,ptr_off,bank,off,pc,text}]
        self.idx = 0
        self.normal_table_path = None
        self.katakana_table_path = None
        self.translation_map = {}
        self._syncing = False
        self.alias_path = None
        self.profile_dir = Path(__file__).resolve().parent / "profiles"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile_records = []  # list of dict from profile json
        self.profile_map = {}      # profile_name -> dict
        self.direct_record_path = None

        self._build_ui()
        self.refresh_profiles()

    def _build_ui(self):
        top = tk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=(8, 4))
        top_btn = tk.Frame(top)
        top_btn.pack(fill="x", pady=(0, 4))
        top_args = tk.Frame(top)
        top_args.pack(fill="x")

        tk.Button(top_btn, text="打开ROM", command=self.open_rom, width=12).pack(side="left")
        tk.Button(top_btn, text="加载普通码表", command=self.load_normal_table, width=12).pack(side="left", padx=4)
        tk.Button(top_btn, text="加载片假名码表", command=self.load_katakana_table, width=12).pack(side="left", padx=4)
        tk.Button(top_btn, text="加载别名字典", command=self.load_alias_table, width=12).pack(side="left", padx=4)
        tk.Button(top_btn, text="加载译文TXT", command=self.load_translation_txt, width=12).pack(side="left", padx=4)
        tk.Label(top_btn, text="存档").pack(side="left", padx=(8, 4))
        self.profile_var = tk.StringVar(value="")
        self.profile_combo = ttk.Combobox(top_btn, width=22, textvariable=self.profile_var, state="readonly")
        self.profile_combo.pack(side="left")
        tk.Button(top_btn, text="读取存档", command=self.load_selected_profile, width=10).pack(side="left", padx=4)
        tk.Button(top_btn, text="读取直读记录TXT", command=self.load_direct_record_txt, width=14).pack(side="left", padx=4)
        tk.Button(top_btn, text="读取文本", command=self.read_block, width=10).pack(side="left", padx=4)

        tk.Label(top_args, text="ptr_start(hex)").pack(side="left", padx=(0, 4))
        self.e_ptr_start = tk.Entry(top_args, width=10)
        self.e_ptr_start.insert(0, f"{self.ptr_start:06X}")
        self.e_ptr_start.pack(side="left")

        tk.Label(top_args, text="count(0=自动)").pack(side="left", padx=(8, 4))
        self.e_count = tk.Entry(top_args, width=7)
        self.e_count.insert(0, str(self.ptr_count))
        self.e_count.pack(side="left")
        tk.Label(top_args, text="mode").pack(side="left", padx=(8, 4))
        self.read_mode_var = tk.StringVar(value=self.read_mode)
        self.read_mode_combo = ttk.Combobox(top_args, width=12, textvariable=self.read_mode_var, state="readonly")
        self.read_mode_combo["values"] = READ_MODE_OPTIONS
        self.read_mode_combo.pack(side="left")
        tk.Label(top_args, text="读取句数").pack(side="left", padx=(8, 4))
        self.e_direct_len = tk.Entry(top_args, width=8)
        self.e_direct_len.insert(0, str(self.direct_count))
        self.e_direct_len.pack(side="left")

        tk.Label(top_args, text="text_start(hex)").pack(side="left", padx=(8, 4))
        self.e_text_start = tk.Entry(top_args, width=10)
        self.e_text_start.insert(0, "" if self.text_start is None else f"{self.text_start:06X}")
        self.e_text_start.pack(side="left")

        tk.Label(top_args, text="bank_base(hex)").pack(side="left", padx=(8, 4))
        self.e_bank_base = tk.Entry(top_args, width=6)
        self.e_bank_base.insert(0, f"{self.bank_base:02X}")
        self.e_bank_base.pack(side="left")

        nav = tk.Frame(self.root)
        nav.pack(fill="x", padx=10, pady=6)
        tk.Button(nav, text="上一条", command=self.prev_item, width=12).pack(side="left")
        tk.Button(nav, text="下一条", command=self.next_item, width=12).pack(side="left", padx=6)
        tk.Label(nav, text="ID").pack(side="left", padx=(12, 4))
        self.e_jump_id = tk.Entry(nav, width=8)
        self.e_jump_id.pack(side="left")
        tk.Button(nav, text="跳转", command=self.jump_to_id, width=8).pack(side="left", padx=6)
        tk.Button(nav, text="保存当前", command=self.save_current, width=12).pack(side="left", padx=6)
        tk.Button(nav, text="保存译文TXT", command=self.save_translation_txt, width=12).pack(side="left", padx=6)
        tk.Button(nav, text="写回ROM", command=self.write_back, width=12).pack(side="left", padx=6)
        self.total_var = tk.StringVar(value="总条数: 0")
        tk.Label(nav, textvariable=self.total_var, anchor="w", font=("Consolas", 10)).pack(side="left", padx=(12, 0))
        tk.Label(nav, text="ptr_order").pack(side="left", padx=(12, 4))
        self.ptr_order_var = tk.StringVar(value=self.ptr_order)
        self.ptr_order_combo = ttk.Combobox(nav, width=12, textvariable=self.ptr_order_var, state="readonly")
        self.ptr_order_combo["values"] = PTR_ORDER_OPTIONS
        self.ptr_order_combo.pack(side="left")
        self.inplace_var = tk.BooleanVar(value=False)
        tk.Checkbutton(nav, text="原地址修改(忽略text_start)", variable=self.inplace_var).pack(side="left", padx=(12, 0))

        self.title_var = tk.StringVar(value="地址: -")
        tk.Label(self.root, textvariable=self.title_var, anchor="w", font=("Consolas", 11)).pack(fill="x", padx=10)
        self.conflict_var = tk.StringVar(value="冲突检测: 未加载存档")
        tk.Label(self.root, textvariable=self.conflict_var, anchor="w", font=("Consolas", 10), fg="red").pack(fill="x", padx=10, pady=(2, 2))
        self.plan_var = tk.StringVar(value="块占用规划: -")
        tk.Label(self.root, textvariable=self.plan_var, anchor="w", font=("Consolas", 10), fg="blue").pack(fill="x", padx=10, pady=(0, 2))

        self.raw_hex_var = tk.StringVar(value="原始字节(HEX): -")
        tk.Label(self.root, textvariable=self.raw_hex_var, anchor="w", font=("Consolas", 10)).pack(fill="x", padx=10, pady=(8, 2))
        self.byte_count_var = tk.StringVar(value="字节计数: 原始=0  当前编辑=0")
        tk.Label(self.root, textvariable=self.byte_count_var, anchor="w", font=("Consolas", 10)).pack(fill="x", padx=10, pady=(0, 2))
        self.preview_hex_var = tk.StringVar(value="当前编辑编码HEX: -")
        tk.Label(self.root, textvariable=self.preview_hex_var, anchor="w", font=("Consolas", 10)).pack(fill="x", padx=10, pady=(0, 2))

        tk.Label(self.root, text="上方原文(只读)", anchor="w").pack(fill="x", padx=10, pady=(2, 2))
        self.src_text = tk.Text(self.root, height=7, wrap="word", font=("Consolas", 11))
        self.src_text.pack(fill="x", padx=10, pady=(0, 8))
        self.src_text.configure(state="disabled")

        tk.Label(self.root, text="新地址文本预览", anchor="w").pack(fill="x", padx=10, pady=(0, 2))
        self.new_addr_var = tk.StringVar(value="新地址(预计): -")
        tk.Label(self.root, textvariable=self.new_addr_var, anchor="w", font=("Consolas", 10)).pack(fill="x", padx=10, pady=(0, 2))
        new_hex_row = tk.Frame(self.root)
        new_hex_row.pack(fill="x", padx=10, pady=(0, 2))
        tk.Label(new_hex_row, text="新地址编码HEX(含00):", anchor="w", font=("Consolas", 10)).pack(side="left")
        self.new_hex_var = tk.StringVar(value="")
        self.new_hex_entry = tk.Entry(new_hex_row, textvariable=self.new_hex_var, font=("Consolas", 10))
        self.new_hex_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.new_hex_entry.bind("<KeyRelease>", self.on_hex_changed)
        self.new_text_preview = tk.Text(self.root, height=6, wrap="word", font=("Consolas", 11))
        self.new_text_preview.pack(fill="x", padx=10, pady=(0, 8))
        self.new_text_preview.configure(state="disabled")

        tk.Label(self.root, text="已存档记录(用于防覆盖)", anchor="w").pack(fill="x", padx=10, pady=(0, 2))
        self.history_list = tk.Listbox(self.root, height=6, font=("Consolas", 10))
        self.history_list.pack(fill="x", padx=10, pady=(0, 8))
        tk.Label(self.root, text="本次块地址明细(前120条)", anchor="w").pack(fill="x", padx=10, pady=(0, 2))
        self.block_list = tk.Listbox(self.root, height=7, font=("Consolas", 10))
        self.block_list.pack(fill="x", padx=10, pady=(0, 8))

        tk.Label(self.root, text="下方译文(可编辑，写回用此文本)", anchor="w").pack(fill="x", padx=10, pady=(0, 2))
        self.edit_text = tk.Text(self.root, wrap="word", font=("Consolas", 12))
        self.edit_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.edit_text.bind("<KeyRelease>", self.on_edit_changed)

        self.status_var = tk.StringVar(value="就绪")
        tk.Label(self.root, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(0, 8))

    def set_status(self, s):
        self.status_var.set(s)

    def open_rom(self):
        p = filedialog.askopenfilename(title="选择ROM", filetypes=[("ROM", "*.sfc *.smc *.bin"), ("All", "*.*")])
        if not p:
            return
        self.rom_path = Path(p)
        self.rom_bytes = bytearray(self.rom_path.read_bytes())
        self.set_status(f"已加载ROM: {self.rom_path}")
        self.refresh_profiles()

    def _reload_rom_from_disk(self):
        if self.rom_path is None:
            raise ValueError("请先打开ROM")
        self.rom_bytes = bytearray(self.rom_path.read_bytes())

    def _profile_name(self, ptr_start, text_start):
        return f"ptr_{ptr_start:06X}__text_{text_start:06X}"

    def refresh_profiles(self):
        self.profile_records = []
        self.profile_map = {}
        for p in sorted(self.profile_dir.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            name = d.get("profile_name") or p.stem
            d["_path"] = str(p)
            self.profile_records.append(d)
            self.profile_map[name] = d
        names = sorted(self.profile_map.keys())
        self.profile_combo["values"] = names
        if names and not self.profile_var.get():
            self.profile_var.set(names[-1])
        self.refresh_history_view()
        self.check_conflicts()

    def load_selected_profile(self):
        name = (self.profile_var.get() or "").strip()
        if not name or name not in self.profile_map:
            messagebox.showwarning("提示", "请先选择一个存档")
            return
        d = self.profile_map[name]
        try:
            self.e_ptr_start.delete(0, "end")
            self.e_ptr_start.insert(0, d.get("ptr_start", ""))
            self.e_count.delete(0, "end")
            self.e_count.insert(0, str(d.get("count", "")))
            self.e_text_start.delete(0, "end")
            self.e_text_start.insert(0, d.get("text_start", ""))
            po = d.get("ptr_order", PTR_ORDER_DEFAULT)
            if po not in PTR_ORDER_OPTIONS:
                po = PTR_ORDER_DEFAULT
            self.ptr_order_var.set(po)
            entries = d.get("entries", [])
            self.translation_map = {}
            for e in entries:
                self.translation_map[int(e.get("id", 0))] = e.get("edit_text", "")
            self.set_status(f"已读取存档: {name}")
            messagebox.showinfo("完成", f"已读取存档:\n{name}\n\n请点击“读取指针块”加载到界面。")
            self.check_conflicts()
        except Exception as ex:
            messagebox.showerror("读取失败", str(ex))

    def refresh_history_view(self):
        self.history_list.delete(0, "end")
        if not self.profile_records:
            self.history_list.insert("end", "<无存档记录>")
            return
        for r in self.profile_records[-200:]:
            line = (
                f"{r.get('updated_at','')} | {r.get('profile_name','')} | "
                f"order={r.get('ptr_order','?')} | "
                f"text {r.get('text_start','?')}-{r.get('text_end','?')} | "
                f"entries={r.get('count','?')}"
            )
            self.history_list.insert("end", line)

    def overlaps(self, a1, a2, b1, b2):
        return not (a2 < b1 or b2 < a1)

    def check_conflicts(self):
        if not self.profile_records:
            self.conflict_var.set("冲突检测: 未加载存档")
            return
        try:
            cur_ptr_start = int(self.e_ptr_start.get().strip(), 16)
            cur_count = int(self.e_count.get().strip())
            ts = self.e_text_start.get().strip()
            cur_text_start = int(ts, 16) if ts else None
        except Exception:
            self.conflict_var.set("冲突检测: 参数错误")
            self.plan_var.set("块占用规划: 参数错误")
            return
        cur_ptr_end = cur_ptr_start + cur_count * 3 - 1
        # 仅估算文本长度：已读取条目时用条目长度，否则未知
        cur_text_end = cur_text_start if cur_text_start is not None else 0
        total = 0
        if self.entries:
            for e in self.entries:
                mh = (e.get("hex_override") or "").strip()
                b = parse_hex_lossy(mh)
                if not b:
                    try:
                        b = self.codec.encode_text(e.get("edit_text", e.get("text", ""))) + bytes([END_BYTE])
                    except Exception:
                        b = bytes([END_BYTE])
                total += len(b)
            if cur_text_start is not None:
                cur_text_end = cur_text_start + max(0, total - 1)
        self.update_block_plan(cur_text_start, cur_text_end, total)

        hit = []
        for r in self.profile_records:
            try:
                ps = int(r.get("ptr_start", ""), 16)
                pe = int(r.get("ptr_end", ""), 16)
                ts = int(r.get("text_start", ""), 16)
                te = int(r.get("text_end", ""), 16)
            except Exception:
                continue
            ptr_conf = self.overlaps(cur_ptr_start, cur_ptr_end, ps, pe)
            txt_conf = False
            if cur_text_start is not None:
                txt_conf = self.overlaps(cur_text_start, cur_text_end, ts, te)
            if ptr_conf or txt_conf:
                hit.append((r, ptr_conf, txt_conf))

        if hit:
            self.conflict_var.set(f"冲突检测: 发现 {len(hit)} 条冲突记录（红色警示）")
        else:
            self.conflict_var.set("冲突检测: 未发现冲突")

    def update_block_plan(self, cur_text_start, cur_text_end, total):
        self.block_list.delete(0, "end")
        if not self.entries:
            self.plan_var.set("块占用规划: 先读取指针块")
            self.block_list.insert("end", "<无条目>")
            return
        if cur_text_start is None:
            self.plan_var.set("块占用规划: 请填写 text_start(hex)")
            self.block_list.insert("end", "<text_start为空，无法计算地址范围>")
            return

        # 列出本次每个块实际将写入的范围
        cursor = cur_text_start
        for e in self.entries[:120]:
            mh = (e.get("hex_override") or "").strip()
            b = parse_hex_lossy(mh)
            if not b:
                try:
                    b = self.codec.encode_text(e.get("edit_text", e.get("text", ""))) + bytes([END_BYTE])
                except Exception:
                    b = bytes([END_BYTE])
            s = cursor
            ee = cursor + len(b) - 1
            self.block_list.insert("end", f"ID {e['id']:03d} : 0x{s:06X}-0x{ee:06X} ({len(b)}B)")
            cursor += len(b)
        if len(self.entries) > 120:
            self.block_list.insert("end", f"... 共 {len(self.entries)} 条，仅显示前120条")

        # 计算建议起点：避开存档中已占用文本范围
        suggested = cur_text_start
        if self.profile_records:
            used = []
            for r in self.profile_records:
                try:
                    ts = int(r.get("text_start", ""), 16)
                    te = int(r.get("text_end", ""), 16)
                except Exception:
                    continue
                used.append((ts, te))
            merged = merge_ranges(used)
            need_len = max(1, total)
            # 若当前起点落在已占用中，建议从该占用后开始
            for s, e in merged:
                if s <= suggested <= e:
                    suggested = e + 1
            # 再寻找一个足够容纳的空窗
            changed = True
            while changed:
                changed = False
                need_end = suggested + need_len - 1
                for s, e in merged:
                    if not (need_end < s or e < suggested):
                        suggested = e + 1
                        changed = True
                        break
        if total <= 0:
            self.plan_var.set(f"块占用规划: 文本总占用=0B | 当前范围 0x{cur_text_start:06X}-0x{cur_text_end:06X}")
            return
        suggested_end = suggested + total - 1
        if suggested == cur_text_start:
            self.plan_var.set(
                f"块占用规划: 本次占用 {total}B | 当前范围 0x{cur_text_start:06X}-0x{cur_text_end:06X} | 当前起点可用"
            )
        else:
            self.plan_var.set(
                f"块占用规划: 本次占用 {total}B | 当前范围 0x{cur_text_start:06X}-0x{cur_text_end:06X} | 建议起点>=0x{suggested:06X} (建议范围 0x{suggested:06X}-0x{suggested_end:06X})"
            )

    def _reload_codec(self):
        if not self.normal_table_path and not self.katakana_table_path:
            return
        self.codec.load_tables(self.normal_table_path, self.katakana_table_path)
        alias_cnt = 0
        if self.alias_path:
            try:
                alias_cnt = self.codec.load_aliases(self.alias_path)
            except Exception as ex:
                self.set_status(f"别名字典加载失败: {ex}")
        warn_cnt = len(self.codec.warnings)
        msg = f"已加载码表: 普通={Path(self.normal_table_path).name if self.normal_table_path else '未加载'} | 片假名={Path(self.katakana_table_path).name if self.katakana_table_path else '未加载'}"
        if self.alias_path:
            msg += f" | 别名={Path(self.alias_path).name}({alias_cnt})"
        if warn_cnt > 0:
            msg += f" | 重复映射警告={warn_cnt}"
        self.set_status(msg)

    def load_alias_table(self):
        p = filedialog.askopenfilename(title="选择别名字典", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not p:
            return
        self.alias_path = p
        self._reload_codec()

    def load_normal_table(self):
        p = filedialog.askopenfilename(title="选择普通码表", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not p:
            return
        self.normal_table_path = p
        self._reload_codec()

    def load_katakana_table(self):
        p = filedialog.askopenfilename(title="选择片假名码表", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not p:
            return
        self.katakana_table_path = p
        self._reload_codec()

    def load_translation_txt(self):
        p = filedialog.askopenfilename(title="选择译文TXT", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not p:
            return
        raw = Path(p).read_bytes()
        text = None
        for enc in ("utf-8-sig", "utf-8", "gb18030", "cp936", "big5", "cp932"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")

        # 先尝试识别“记录文件格式”（每行JSON, 含 start/end）
        rec_lines = text.splitlines()
        rec_items = []
        for ln in rec_lines:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            try:
                obj = json.loads(s)
            except Exception:
                rec_items = []
                break
            if isinstance(obj, dict) and "start" in obj and "end" in obj:
                rec_items.append(obj)
            else:
                rec_items = []
                break
        if rec_items:
            if self.rom_path is None:
                messagebox.showerror("错误", "请先打开ROM，再加载记录TXT")
                return
            try:
                self._reload_rom_from_disk()
            except Exception as ex:
                messagebox.showerror("错误", f"重新加载ROM失败: {ex}")
                return
            rb = self.rom_bytes
            self.entries = []
            for i, r in enumerate(rec_items):
                try:
                    s = int(str(r.get("start", "0")).replace("0x", "").replace("0X", ""), 16)
                    e = int(str(r.get("end", "0")).replace("0x", "").replace("0X", ""), 16)
                except Exception:
                    continue
                if s < 0 or e < s or e >= len(rb):
                    continue
                slot_len = e - s + 1
                raw_slot = bytes(rb[s:e + 1])
                zero_pos = raw_slot.find(bytes([END_BYTE]))
                body = raw_slot[:zero_pos] if zero_pos >= 0 else raw_slot
                text_cur = self.codec.decode_bytes(body)
                raw_hex = " ".join(f"{x:02X}" for x in body)
                edit_text = r.get("edit_text", text_cur)
                hx = (r.get("hex_override", "") or "").strip()
                self.entries.append({
                    "id": i,
                    "ptr_off": -1,
                    "bank": 0,
                    "off": 0,
                    "pc": s,
                    "text": text_cur,
                    "edit_text": edit_text,
                    "hex_override": hx,
                    "raw_hex": raw_hex,
                    "slot_len": slot_len,
                    "has_end": True,
                })
            if not self.entries:
                messagebox.showwarning("提示", "记录TXT识别成功，但无有效条目")
                return
            self.read_mode = READ_MODE_DIRECT
            self.read_mode_var.set(READ_MODE_DIRECT)
            self.ptr_start = self.entries[0]["pc"]
            self.e_ptr_start.delete(0, "end")
            self.e_ptr_start.insert(0, f"{self.ptr_start:06X}")
            self.e_direct_len.delete(0, "end")
            self.e_direct_len.insert(0, str(len(self.entries)))
            self.direct_count = len(self.entries)
            self.idx = 0
            self.total_var.set(f"总条数: {len(self.entries)}")
            self.show_current()
            self.check_conflicts()
            self.set_status(f"已按记录地址加载TXT: {Path(p).name} | 条目={len(self.entries)}")
            return

        self.translation_map.clear()
        cur_id = None
        buf = []
        for ln in text.splitlines():
            m = ID_LINE_RE.match(ln)
            if m:
                if cur_id is not None:
                    self.translation_map[cur_id] = "\n".join(buf).strip()
                cur_id = int(m.group(1))
                buf = []
                continue
            if cur_id is not None:
                buf.append(ln)
        if cur_id is not None:
            self.translation_map[cur_id] = "\n".join(buf).strip()

        # 已读取指针后，立刻把译文映射进条目
        if self.entries:
            for e in self.entries:
                if e["id"] in self.translation_map and self.translation_map[e["id"]]:
                    e["edit_text"] = self.translation_map[e["id"]]
            self.show_current()
        self.set_status(f"已加载译文TXT: {Path(p).name} | 匹配ID数={len(self.translation_map)}")

    def load_direct_record_txt(self):
        p = filedialog.askopenfilename(
            title="选择直读记录TXT",
            initialdir=str(self.profile_dir),
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
        )
        if not p:
            return
        try:
            lines = Path(p).read_text(encoding="utf-8").splitlines()
        except Exception as ex:
            messagebox.showerror("错误", f"读取失败: {ex}")
            return

        records = []
        meta = {}
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if s.startswith("#META "):
                try:
                    m = json.loads(s[6:])
                    if isinstance(m, dict):
                        meta.update(m)
                except Exception:
                    pass
                continue
            if s.startswith("#"):
                continue
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and "start" in obj and "end" in obj:
                    records.append(obj)
            except Exception:
                continue

        if not records:
            messagebox.showwarning("提示", "未读取到有效记录")
            return
        if self.rom_path is None:
            messagebox.showerror("错误", "请先打开ROM，再读取直读记录")
            return
        try:
            self._reload_rom_from_disk()
        except Exception as ex:
            messagebox.showerror("错误", f"重新加载ROM失败: {ex}")
            return
        rb = self.rom_bytes
        self.entries = []
        for i, r in enumerate(records):
            try:
                s = int(str(r.get("start", "0")).replace("0x", "").replace("0X", ""), 16)
                e = int(str(r.get("end", "0")).replace("0x", "").replace("0X", ""), 16)
            except Exception:
                continue
            if e < s:
                continue
            slot_len = e - s + 1
            if s < 0 or e >= len(rb):
                continue
            raw_slot = bytes(rb[s:e + 1])
            zero_pos = raw_slot.find(bytes([END_BYTE]))
            body = raw_slot[:zero_pos] if zero_pos >= 0 else raw_slot
            txt_cur = self.codec.decode_bytes(body)
            raw_hex = " ".join(f"{x:02X}" for x in body)
            txt = r.get("edit_text", txt_cur)
            if txt is None:
                txt = txt_cur
            hx = r.get("hex_override", "")
            if hx is None:
                hx = ""
            self.entries.append({
                "id": i,
                "ptr_off": -1,
                "bank": 0,
                "off": 0,
                "pc": s,
                "text": txt_cur,
                "edit_text": txt,
                "hex_override": hx,
                "raw_hex": raw_hex,
                "slot_len": slot_len,
                "has_end": True,
            })

        if not self.entries:
            messagebox.showwarning("提示", "记录格式有效但无可加载条目")
            return

        # 回填关键参数，便于后续直接写回
        self.read_mode = READ_MODE_DIRECT
        self.read_mode_var.set(READ_MODE_DIRECT)
        if self.entries:
            self.ptr_start = self.entries[0]["pc"]
            self.e_ptr_start.delete(0, "end")
            self.e_ptr_start.insert(0, f"{self.ptr_start:06X}")
            total_len = sum(max(1, x.get("slot_len", 1)) for x in self.entries)
            self.e_direct_len.delete(0, "end")
            self.e_direct_len.insert(0, str(len(self.entries)))
            self.direct_count = len(self.entries)
        if meta.get("rom"):
            self.set_status(f"已加载直读记录: {Path(p).name} | 条目={len(self.entries)} | 记录ROM={meta.get('rom')}")
        else:
            self.set_status(f"已加载直读记录: {Path(p).name} | 条目={len(self.entries)}")
        self.direct_record_path = p
        self.idx = 0
        self.total_var.set(f"总条数: {len(self.entries)}")
        self.show_current()
        self.check_conflicts()

    def read_block(self):
        if self.rom_path is None:
            messagebox.showerror("错误", "请先打开ROM")
            return
        try:
            # 每次读取前都从磁盘刷新，避免使用旧内存副本
            self._reload_rom_from_disk()
        except Exception as ex:
            messagebox.showerror("错误", f"重新加载ROM失败: {ex}")
            return
        if not self.codec.code_to_token:
            messagebox.showerror("错误", "请先加载码表")
            return

        try:
            self.read_mode = self.read_mode_var.get().strip() or READ_MODE_POINTER
            if self.read_mode not in READ_MODE_OPTIONS:
                self.read_mode = READ_MODE_POINTER
            self.ptr_start = int(self.e_ptr_start.get().strip(), 16)
            self.ptr_count = int(self.e_count.get().strip())
            ts = self.e_text_start.get().strip()
            self.text_start = int(ts, 16) if ts else None
            self.bank_base = int(self.e_bank_base.get().strip(), 16)
            self.direct_count = int((self.e_direct_len.get().strip() or "0"))
            self.ptr_order = self.ptr_order_var.get().strip()
            if self.ptr_order not in PTR_ORDER_OPTIONS:
                self.ptr_order = PTR_ORDER_DEFAULT
        except Exception:
            messagebox.showerror("错误", "参数格式错误")
            return

        # 每次重新读取时，清空上一次的编辑缓存（译文覆盖与手工HEX覆盖）
        self.entries = []
        self.translation_map = {}
        self.new_hex_var.set("")
        self.edit_text.delete("1.0", "end")
        rb = self.rom_bytes
        if self.read_mode == READ_MODE_DIRECT:
            start = self.ptr_start
            if start < 0 or start >= len(rb):
                messagebox.showerror("错误", "直读起始地址越界")
                return
            if self.direct_count <= 0:
                messagebox.showerror("错误", "读取句数必须大于0")
                return
            end_addr = len(rb)
            cur = start
            tid = 0
            while cur < end_addr and tid < self.direct_count:
                try:
                    zero_pos = rb.index(END_BYTE, cur, end_addr)
                    slot_end = zero_pos + 1
                    body = bytes(rb[cur:zero_pos])
                    has_end = True
                except ValueError:
                    slot_end = end_addr
                    body = bytes(rb[cur:end_addr])
                    has_end = False
                text = self.codec.decode_bytes(body)
                raw_hex = " ".join(f"{x:02X}" for x in body)
                self.entries.append({
                    "id": tid,
                    "ptr_off": -1,
                    "bank": 0,
                    "off": 0,
                    "pc": cur,
                    "text": text,
                    "edit_text": text,
                    "hex_override": "",
                    "raw_hex": raw_hex,
                    "slot_len": slot_end - cur,
                    "has_end": has_end,
                })
                tid += 1
                cur = slot_end
            if not self.entries:
                messagebox.showwarning("提示", "直读模式未读取到内容")
                self.total_var.set("总条数: 0")
                return
            self.idx = 0
            self.total_var.set(f"总条数: {len(self.entries)}")
            self.show_current()
            self.check_conflicts()
            last_end = self.entries[-1]["pc"] + max(1, self.entries[-1].get("slot_len", 1)) - 1
            self.set_status(f"已读取 {len(self.entries)} 条 (文本直读模式, 范围 0x{start:06X}-0x{last_end:06X})")
            return

        auto_mode = (self.ptr_count <= 0)
        i = 0
        while True:
            if (not auto_mode) and i >= self.ptr_count:
                break
            po = self.ptr_start + i * 3
            if po + 2 >= len(rb):
                break
            b0 = rb[po]
            b1 = rb[po + 1]
            b2 = rb[po + 2]
            bank, off = unpack_ptr3(b0, b1, b2, self.ptr_order)

            # 自动模式下: 000000 视为终止
            if auto_mode and b0 == 0 and b1 == 0 and b2 == 0:
                break
            pc = ptr_to_pc(bank, off, self.bank_base)
            if pc < 0 or pc >= len(rb):
                # 自动模式遇到无效指针即停止；固定数量模式保留占位
                if auto_mode:
                    break
                text = "<INVALID PTR>"
                raw_hex = ""
            else:
                end = pc
                while end < len(rb) and rb[end] != END_BYTE:
                    end += 1
                raw = bytes(rb[pc:end])
                text = self.codec.decode_bytes(raw)
                raw_hex = " ".join(f"{x:02X}" for x in raw)

            self.entries.append({
                "id": i,
                "ptr_off": po,
                "bank": bank,
                "off": off,
                "pc": pc,
                "text": text,          # 原文(ROM解码)
                "edit_text": text,     # 译文(可编辑/写回)
                "hex_override": "",    # 手动修改的新地址编码HEX(含00)，非空时优先写回
                "raw_hex": raw_hex,
            })
            i += 1

        # 如果已加载译文TXT，则覆盖对应ID的 edit_text
        if self.translation_map:
            for e in self.entries:
                if e["id"] in self.translation_map and self.translation_map[e["id"]]:
                    e["edit_text"] = self.translation_map[e["id"]]

        # 指针模式: 自动加载对应profiles里的已保存修改(译文/HEX)
        if self.read_mode != READ_MODE_DIRECT and self.text_start is not None:
            pname = self._profile_name(self.ptr_start, self.text_start)
            p = self.profile_dir / f"{pname}.json"
            if p.exists():
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    by_id = {}
                    for x in d.get("entries", []):
                        try:
                            by_id[int(x.get("id", -1))] = x
                        except Exception:
                            continue
                    for e in self.entries:
                        x = by_id.get(e["id"])
                        if not x:
                            continue
                        if x.get("edit_text", "") != "":
                            e["edit_text"] = x.get("edit_text", e["edit_text"])
                        if x.get("hex_override", "") != "":
                            e["hex_override"] = x.get("hex_override", "")
                except Exception:
                    pass

        if not self.entries:
            messagebox.showwarning("提示", "未读取到任何条目")
            self.total_var.set("总条数: 0")
            return
        self.idx = 0
        self.total_var.set(f"总条数: {len(self.entries)}")
        self.show_current()
        self.check_conflicts()
        mode_txt = "自动" if auto_mode else "固定"
        self.set_status(f"已读取 {len(self.entries)} 条 ({mode_txt}模式)")

    def show_current(self):
        if not self.entries:
            return
        e = self.entries[self.idx]
        if e.get("ptr_off", -1) >= 0:
            self.title_var.set(
                f"ID={e['id']}  PTR@0x{e['ptr_off']:06X}  bank={e['bank']:02X} off={e['off']:04X}  pc=0x{e['pc']:06X}"
            )
        else:
            self.title_var.set(f"ID={e['id']}  直读文本  pc=0x{e['pc']:06X}  槽位={e.get('slot_len', 0)}B")
        self.raw_hex_var.set(f"原始字节(HEX): {e.get('raw_hex', '')}")
        self.src_text.configure(state="normal")
        self.src_text.delete("1.0", "end")
        self.src_text.insert("1.0", e["text"])
        self.src_text.configure(state="disabled")

        self.edit_text.delete("1.0", "end")
        self.edit_text.insert("1.0", e.get("edit_text", e["text"]))
        self.new_hex_var.set(e.get("hex_override", ""))
        self.update_preview_hex()

    def on_edit_changed(self, _evt=None):
        if self._syncing:
            return
        # 译文改动 -> 同步刷新 HEX(含00)
        s = self.edit_text.get("1.0", "end-1c")
        try:
            b = self.codec.encode_text(s) + bytes([END_BYTE])
            self._syncing = True
            self.new_hex_var.set(" ".join(f"{x:02X}" for x in b))
        except Exception:
            # 译文暂时不可编码时，不覆盖用户当前 HEX
            pass
        finally:
            self._syncing = False
        self.update_preview_hex()

    def on_hex_changed(self, _evt=None):
        if self._syncing:
            return
        # HEX 改动 -> 同步反解译文；未识别字节保留为【XX】
        b = parse_hex_lossy(self.new_hex_var.get().strip())
        if b:
            body = b[:-1] if b[-1] == END_BYTE else b
            txt = self.codec.decode_bytes(body)
            self._syncing = True
            self.edit_text.delete("1.0", "end")
            self.edit_text.insert("1.0", txt)
            self._syncing = False
        self.update_preview_hex()

    def update_preview_hex(self):
        s = self.edit_text.get("1.0", "end-1c")
        mh = self.new_hex_var.get().strip()
        try:
            raw_len = 0
            if self.entries:
                e = self.entries[self.idx]
                raw_hex = (e.get("raw_hex", "") or "").strip()
                raw_len = len(raw_hex.split()) if raw_hex else 0
            use_hex = False
            if mh:
                b_all = parse_hex_lossy(mh)
                if b_all:
                    b = b_all[:-1] if len(b_all) > 0 and b_all[-1] == END_BYTE else b_all
                    use_hex = True
            if not use_hex:
                # HEX 为空或无有效字节时，只做自动编码预览，不改写输入框
                b = self.codec.encode_text(s) + bytes([END_BYTE])
            hx = " ".join(f"{x:02X}" for x in b[:-1] if len(b) > 0 and b[-1] == END_BYTE)
            src = "来自下方HEX" if use_hex else "来自译文自动编码"
            self.preview_hex_var.set(f"当前编辑编码HEX ({src}): {hx}")
            cur_len = len(b[:-1] if len(b) > 0 and b[-1] == END_BYTE else b)
            self.byte_count_var.set(f"字节计数: 原始={raw_len}  当前编辑={cur_len}")
        except Exception as ex:
            self.preview_hex_var.set(f"当前编辑编码HEX: <编码失败> {ex}")
            raw_len = 0
            if self.entries:
                e = self.entries[self.idx]
                raw_hex = (e.get("raw_hex", "") or "").strip()
                raw_len = len(raw_hex.split()) if raw_hex else 0
            self.byte_count_var.set(f"字节计数: 原始={raw_len}  当前编辑=<编码失败>")
        self.update_new_address_preview()
        self.check_conflicts()

    def update_new_address_preview(self):
        if not self.entries:
            self.new_addr_var.set("新地址(预计): -")
            self.new_text_preview.configure(state="normal")
            self.new_text_preview.delete("1.0", "end")
            self.new_text_preview.configure(state="disabled")
            return
        try:
            ts = self.e_text_start.get().strip()
            if not ts:
                raise ValueError("text_start 为空")
            text_start = int(ts, 16)
            bank_base = int(self.e_bank_base.get().strip(), 16)
        except Exception:
            self.new_addr_var.set("新地址(预计): <参数错误>")
            return

        # 用当前 entries 文本 + 当前编辑框内容，估算本条写回后的新地址
        try:
            cursor = text_start
            for i, e in enumerate(self.entries):
                if i == self.idx:
                    txt = self.edit_text.get("1.0", "end-1c")
                    override_hex = self.new_hex_var.get().strip()
                else:
                    txt = e.get("edit_text", e["text"])
                    override_hex = e.get("hex_override", "").strip()
                b = parse_hex_lossy(override_hex)
                if not b:
                    b = self.codec.encode_text(txt) + bytes([END_BYTE])
                if i == self.idx:
                    bank, off = pc_to_ptr(cursor, bank_base)
                    self.new_addr_var.set(f"新地址(预计): PC=0x{cursor:06X}  PTR={bank:02X} {off & 0xFF:02X} {(off >> 8) & 0xFF:02X}")
                    self.new_text_preview.configure(state="normal")
                    self.new_text_preview.delete("1.0", "end")
                    self.new_text_preview.insert("1.0", txt)
                    self.new_text_preview.configure(state="disabled")
                    break
                cursor += len(b)
        except Exception as ex:
            self.new_addr_var.set(f"新地址(预计): <编码失败> {ex}")

    def save_current(self):
        if not self.entries:
            return
        self.entries[self.idx]["edit_text"] = self.edit_text.get("1.0", "end-1c")
        self.entries[self.idx]["hex_override"] = self.new_hex_var.get().strip()
        self.set_status(f"已保存当前 ID={self.entries[self.idx]['id']}")

    def prev_item(self):
        if not self.entries:
            return
        self.save_current()
        self.idx = max(0, self.idx - 1)
        self.show_current()

    def next_item(self):
        if not self.entries:
            return
        self.save_current()
        self.idx = min(len(self.entries) - 1, self.idx + 1)
        self.show_current()

    def jump_to_id(self):
        if not self.entries:
            return
        s = self.e_jump_id.get().strip()
        if not s:
            return
        try:
            target = int(s)
        except Exception:
            messagebox.showerror("错误", "ID格式错误，请输入整数")
            return
        if target < 0 or target >= len(self.entries):
            messagebox.showerror("错误", f"ID超范围: 0..{len(self.entries)-1}")
            return
        self.save_current()
        self.idx = target
        self.show_current()

    def write_back(self):
        if self.rom_path is None or not self.entries:
            messagebox.showerror("错误", "请先读取指针块")
            return

        self.save_current()

        try:
            self.read_mode = self.read_mode_var.get().strip() or READ_MODE_POINTER
            if self.read_mode not in READ_MODE_OPTIONS:
                self.read_mode = READ_MODE_POINTER
            bank_base = int(self.e_bank_base.get().strip(), 16)
            self.ptr_order = self.ptr_order_var.get().strip()
            if self.ptr_order not in PTR_ORDER_OPTIONS:
                self.ptr_order = PTR_ORDER_DEFAULT
            inplace_mode = bool(self.inplace_var.get())
            if self.read_mode == READ_MODE_DIRECT:
                inplace_mode = True
            if inplace_mode:
                text_start = None
            else:
                ts = self.e_text_start.get().strip()
                if not ts:
                    raise ValueError("text_start 为空，请先填写")
                text_start = int(ts, 16)
        except Exception:
            messagebox.showerror("错误", "text_start/bank_base 参数错误")
            return

        try:
            # 写回前再次从磁盘读取最新ROM，避免覆盖外部新修改
            rb = bytearray(self.rom_path.read_bytes())
        except Exception as ex:
            messagebox.showerror("错误", f"读取磁盘ROM失败: {ex}")
            return
        cursor = text_start if text_start is not None else 0
        text_start_written = cursor

        # 先编码
        encoded = []
        write_details = []
        try:
            for i, e in enumerate(self.entries):
                mh = e.get("hex_override", "").strip()
                # 无条件按“新地址编码HEX”写回；若该行空/无有效字节，则兜底用译文自动编码
                b = parse_hex_lossy(mh)
                if not b:
                    try:
                        b = self.codec.encode_text(e.get("edit_text", e["text"])) + bytes([END_BYTE])
                    except Exception as ex:
                        raise ValueError(f"ID={e.get('id')} 编码失败: {ex}")
                encoded.append((e["id"], b))
                write_details.append({
                    "id": e["id"],
                    "ptr_off": (self.ptr_start + i * 3) if e.get("ptr_off", -1) >= 0 else -1,
                    "old_pc": e.get("pc", -1),
                    "new_pc": None,
                    "new_len": len(b),
                    "new_bank": None,
                    "new_off": None,
                })
        except Exception as ex:
            messagebox.showerror("编码失败", str(ex))
            return

        # 写文本和指针
        if inplace_mode:
            min_pc = None
            max_pc = None
            for i, (tid, b) in enumerate(encoded):
                old_pc = self.entries[i].get("pc", -1)
                if old_pc < 0 or old_pc >= len(rb):
                    messagebox.showerror("错误", f"原地址无效: ID={tid}, pc=0x{old_pc:06X}")
                    return
                old_len = self.entries[i].get("slot_len")
                if not old_len:
                    old_raw = self.entries[i].get("raw_hex", "").strip()
                    old_len = (len(old_raw.split()) if old_raw else 0) + 1  # +00 结尾
                if len(b) > old_len:
                    messagebox.showerror("错误", f"原地址模式长度超限: ID={tid}, 新={len(b)} 旧容量={old_len}")
                    return
                end_pc = old_pc + old_len
                if end_pc > len(rb):
                    messagebox.showerror("错误", f"原地址写入越界: ID={tid}, pc=0x{old_pc:06X}")
                    return
                # 覆盖并清尾，避免残留旧字节
                rb[old_pc:old_pc + len(b)] = b
                if len(b) < old_len:
                    rb[old_pc + len(b):end_pc] = bytes([END_BYTE]) * (old_len - len(b))

                bank, off = self.entries[i]["bank"], self.entries[i]["off"]  # 指针不改
                write_details[i]["new_pc"] = old_pc
                write_details[i]["new_bank"] = bank
                write_details[i]["new_off"] = off
                if min_pc is None or old_pc < min_pc:
                    min_pc = old_pc
                e_pc = old_pc + old_len - 1
                if max_pc is None or e_pc > max_pc:
                    max_pc = e_pc
            text_start_written = min_pc if min_pc is not None else 0
            cursor = (max_pc + 1) if max_pc is not None else text_start_written
        else:
            for i, (tid, b) in enumerate(encoded):
                if cursor + len(b) >= len(rb):
                    messagebox.showerror("错误", f"写入越界: ID={tid}, pc=0x{cursor:06X}")
                    return

                rb[cursor:cursor + len(b)] = b

                bank, off = pc_to_ptr(cursor, bank_base)
                po = self.ptr_start + i * 3
                p0, p1, p2 = pack_ptr3(bank, off, self.ptr_order)
                rb[po] = p0
                rb[po + 1] = p1
                rb[po + 2] = p2
                write_details[i]["new_pc"] = cursor
                write_details[i]["new_bank"] = bank
                write_details[i]["new_off"] = off
                cursor += len(b)

        save_to = filedialog.asksaveasfilename(
            title="保存ROM",
            defaultextension=".sfc",
            filetypes=[("ROM", "*.sfc *.smc *.bin"), ("All", "*.*")],
            initialfile=(self.rom_path.stem + "_edited" + self.rom_path.suffix) if self.rom_path else "edited.sfc",
        )
        if not save_to:
            return

        Path(save_to).write_bytes(rb)
        self.rom_bytes = bytearray(rb)
        if inplace_mode:
            self.set_status(f"写回完成(原地址模式): {save_to} | 覆盖区 0x{text_start_written:06X}..0x{cursor-1:06X}")
        else:
            self.set_status(f"写回完成: {save_to} | 文本区 0x{text_start:06X}..0x{cursor-1:06X}")
        self.write_auto_report(
            save_to=Path(save_to),
            write_details=write_details,
            text_start=text_start_written,
            text_end=cursor - 1,
            bank_base=bank_base,
        )
        if self.read_mode != READ_MODE_DIRECT:
            self.save_profile_snapshot(
                save_to=Path(save_to),
                write_details=write_details,
                text_start=text_start_written,
                text_end=cursor - 1,
            )
        if self.read_mode == READ_MODE_DIRECT:
            self.save_direct_record_txt(write_details, save_to=Path(save_to))
        self.refresh_profiles()
        if inplace_mode:
            mode_name = "文本直读模式(原地址)" if self.read_mode == READ_MODE_DIRECT else "原地址模式"
            messagebox.showinfo("完成", f"已写回ROM({mode_name}):\n{save_to}\n\n覆盖区: 0x{text_start_written:06X}..0x{cursor-1:06X}")
        else:
            messagebox.showinfo("完成", f"已写回ROM:\n{save_to}\n\n文本区: 0x{text_start:06X}..0x{cursor-1:06X}")

    def save_direct_record_txt(self, write_details, save_to):
        # 仅记录“修改过”的直读条目
        mod = []
        by_id = {d["id"]: d for d in write_details}
        for e in self.entries:
            txt = e.get("edit_text", "")
            orig = e.get("text", "")
            hx = (e.get("hex_override", "") or "").strip()
            changed = (txt != orig) or bool(hx)
            if not changed:
                continue
            wd = by_id.get(e["id"], {})
            start = wd.get("new_pc", e.get("pc", -1))
            slot_len = e.get("slot_len")
            if not slot_len:
                raw_hex = (e.get("raw_hex", "") or "").strip()
                slot_len = (len(raw_hex.split()) if raw_hex else 0) + 1
            end = start + max(1, slot_len) - 1
            mod.append({
                "id": e["id"],
                "start": f"0x{start:06X}",
                "end": f"0x{end:06X}",
                "slot_len": slot_len,
                "orig_text": orig,
                "edit_text": txt,
                "hex_override": hx,
                "raw_hex": e.get("raw_hex", ""),
            })
        if not mod:
            return
        max_end = self.ptr_start
        for e in self.entries:
            ee = e.get("pc", self.ptr_start) + max(1, e.get("slot_len", 1)) - 1
            if ee > max_end:
                max_end = ee
        # 同一首地址只保留一个文件：优先复用已有文件，否则创建固定名
        same_start = sorted(self.profile_dir.glob(f"direct_read_{self.ptr_start:06X}_*.txt"))
        if same_start:
            out = same_start[0]
            for extra in same_start[1:]:
                try:
                    extra.unlink()
                except Exception:
                    pass
        else:
            out = self.profile_dir / f"direct_read_{self.ptr_start:06X}_{max_end:06X}.txt"
        meta = {
            "mode": READ_MODE_DIRECT,
            "rom": str(save_to),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ptr_start": f"0x{self.ptr_start:06X}",
            "read_count": self.direct_count,
            "entry_count": len(mod),
            "record_id": str(uuid.uuid4()),
            "file_policy": "single_file_per_start_addr",
        }
        lines = []
        lines.append("# 直读记录TXT（每行一个JSON，供“读取直读记录TXT”加载）")
        lines.append("#META " + json.dumps(meta, ensure_ascii=False))
        for r in mod:
            lines.append(json.dumps(r, ensure_ascii=False))
        out.write_text("\n".join(lines), encoding="utf-8")
        self.set_status(self.status_var.get() + f" | 已写直读记录: {out.name}")

    def write_auto_report(self, save_to, write_details, text_start, text_end, bank_base):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ptr_start = self.ptr_start
        ptr_end = self.ptr_start + len(write_details) * 3 - 1
        second_half_start = 0x200000
        second_half_end = 0x3FFFFF

        text_ranges = []
        ptr_ranges = []
        text_total = 0
        for d in write_details:
            ns = d["new_pc"]
            ne = ns + d["new_len"] - 1
            text_ranges.append((ns, ne))
            text_total += d["new_len"]
            po = d["ptr_off"]
            ptr_ranges.append((po, po + 2))

        merged_text = merge_ranges(text_ranges)
        merged_ptr = merge_ranges(ptr_ranges)

        second_half_text = []
        for s, e in merged_text:
            is_s = max(s, second_half_start)
            is_e = min(e, second_half_end)
            if is_s <= is_e:
                second_half_text.append((is_s, is_e))
        second_half_text = merge_ranges(second_half_text)

        report_txt = save_to.with_name(save_to.stem + "_write_report.txt")
        report_csv = save_to.with_name(save_to.stem + "_write_entries.csv")
        ledger_csv = save_to.with_name(save_to.stem + "_usage_ledger.csv")

        lines = []
        lines.append("ROM Text Editor Auto Report")
        lines.append(f"time={ts}")
        lines.append(f"rom={save_to}")
        lines.append(f"entries={len(write_details)}")
        lines.append(f"bank_base=0x{bank_base:02X}")
        lines.append(f"pointer_table_range=0x{ptr_start:06X}-0x{ptr_end:06X}")
        lines.append(f"text_write_range=0x{text_start:06X}-0x{text_end:06X}")
        lines.append(f"text_total_bytes={text_total}")
        lines.append("")
        lines.append("[Pointer Ranges]")
        for s, e in merged_ptr:
            lines.append(f"pointer,0x{s:06X},0x{e:06X}")
        lines.append("")
        lines.append("[Text Ranges]")
        for s, e in merged_text:
            lines.append(f"text,0x{s:06X},0x{e:06X}")
        lines.append("")
        lines.append("[Used In Back 2M]")
        if second_half_text:
            for s, e in second_half_text:
                lines.append(f"text_back2m,0x{s:06X},0x{e:06X}")
        else:
            lines.append("text_back2m,<none>")
        lines.append("")
        lines.append("[Per Entry]")
        lines.append("id,ptr_off,old_pc,new_pc,new_bank,new_off,new_len")
        for d in write_details:
            lines.append(
                f"{d['id']},{fmt_hex(d['ptr_off'])},{fmt_hex(d['old_pc'])},{fmt_hex(d['new_pc'])},"
                f"{fmt_hex(d['new_bank'],2)},{fmt_hex(d['new_off'],4)},{d['new_len']}"
            )
        report_txt.write_text("\n".join(lines), encoding="utf-8")

        csv_lines = ["id,ptr_off,old_pc,new_pc,new_bank,new_off,new_len"]
        for d in write_details:
            csv_lines.append(
                f"{d['id']},{fmt_hex(d['ptr_off'])},{fmt_hex(d['old_pc'])},{fmt_hex(d['new_pc'])},"
                f"{fmt_hex(d['new_bank'],2)},{fmt_hex(d['new_off'],4)},{d['new_len']}"
            )
        report_csv.write_text("\n".join(csv_lines), encoding="utf-8")

        ledger_header = "time,rom,entries,ptr_start,ptr_end,text_start,text_end,text_bytes,back2m_ranges\n"
        back2m_str = ";".join(f"0x{s:06X}-0x{e:06X}" for s, e in second_half_text) if second_half_text else "<none>"
        ledger_line = (
            f"{ts},{save_to.name},{len(write_details)},0x{ptr_start:06X},0x{ptr_end:06X},"
            f"0x{text_start:06X},0x{text_end:06X},{text_total},{back2m_str}\n"
        )
        if not ledger_csv.exists():
            ledger_csv.write_text(ledger_header + ledger_line, encoding="utf-8")
        else:
            with ledger_csv.open("a", encoding="utf-8") as f:
                f.write(ledger_line)
    def save_profile_snapshot(self, save_to, write_details, text_start, text_end):
        profile_name = self._profile_name(self.ptr_start, text_start)
        d = {
            "profile_name": profile_name,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rom": str(save_to),
            "ptr_start": f"{self.ptr_start:06X}",
            "ptr_end": f"{self.ptr_start + len(self.entries) * 3 - 1:06X}",
            "ptr_order": self.ptr_order_var.get().strip() or PTR_ORDER_DEFAULT,
            "count": len(self.entries),
            "text_start": f"{text_start:06X}",
            "text_end": f"{text_end:06X}",
            "entries": [],
        }
        by_id = {x["id"]: x for x in write_details}
        for e in self.entries:
            wd = by_id.get(e["id"], {})
            d["entries"].append({
                "id": e["id"],
                "ptr_off": (f"{e['ptr_off']:06X}" if e.get("ptr_off", -1) >= 0 else ""),
                "old_text": e.get("text", ""),
                "edit_text": e.get("edit_text", e.get("text", "")),
                "hex_override": e.get("hex_override", ""),
                "new_pc": f"{wd.get('new_pc', 0):06X}" if wd.get("new_pc") is not None else "",
                "new_bank": f"{wd.get('new_bank', 0):02X}" if wd.get("new_bank") is not None else "",
                "new_off": f"{wd.get('new_off', 0):04X}" if wd.get("new_off") is not None else "",
                "new_len": wd.get("new_len", 0),
            })
        p = self.profile_dir / f"{profile_name}.json"
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_translation_txt(self):
        if not self.entries:
            messagebox.showerror("错误", "请先读取指针块")
            return
        self.save_current()

        p = filedialog.asksaveasfilename(
            title="保存译文TXT",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
            initialfile="译文_导出.txt",
        )
        if not p:
            return

        lines = []
        for e in self.entries:
            lines.append(f"[ID: {e['id']:03d}]")
            txt = e.get("edit_text", "") or ""
            lines.append(txt)
            lines.append("")
        Path(p).write_text("\n".join(lines), encoding="utf-8")
        self.set_status(f"已保存译文TXT: {p}")
        messagebox.showinfo("完成", f"已保存译文TXT:\n{p}")


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
