# -*- coding: utf-8 -*-
import os
import re
import time
from collections import OrderedDict
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


PAGE_SIZE = 0x800
HOOK_ADDR = 0x00A0C5
ZONE2_ADDR = 0x2002E0
ZONE4_ADDR = 0x200A00
RECORD_DIR = "压缩文本指针文本处理记录"

ROLE_CONSTANTS = OrderedDict(
    [
        (
            "法雷尔",
            {
                "signature": bytes.fromhex("BB41FC25"),
                "block_start": 0xCF2B0F,
                "pointer_range": (0xE948F, 0xE9DD2),
                "block_slot_range": (1, 32),
            },
        ),
        (
            "卡特琳娜",
            {
                "signature": bytes.fromhex("ED462E26"),
                "block_start": 0xCFA142,
                "pointer_range": (0xE9DD3, 0xEA542),
                "block_slot_range": (25, 56),
            },
        ),
        (
            "奥托",
            {
                "signature": bytes.fromhex("51516026"),
                "block_start": 0xCFFD16,
                "pointer_range": (0xEA543, 0xEA988),
                "block_slot_range": (38, 69),
            },
        ),
        (
            "恩斯特",
            {
                "signature": bytes.fromhex("B55B9226"),
                "block_start": 0xD032CB,
                "pointer_range": (0xEA989, 0xEAB7C),
                "block_slot_range": (47, 75),
            },
        ),
        (
            "皮耶罗",
            {
                "signature": bytes.fromhex("8356C426"),
                "block_start": 0xD04C96,
                "pointer_range": (0xEAB7D, 0xEAE1E),
                "block_slot_range": (52, 75),
            },
        ),
        (
            "阿里",
            {
                "signature": bytes.fromhex("1F4CF626"),
                "block_start": 0xD06F5C,
                "pointer_range": (0xEAE1F, 0xEB5A4),
                "block_slot_range": (59, 75),
            },
        ),
    ]
)

ROLE_SIGNATURES = OrderedDict((name, meta["signature"]) for name, meta in ROLE_CONSTANTS.items())
CHARACTER_BLOCK_STARTS = OrderedDict((name, meta["block_start"]) for name, meta in ROLE_CONSTANTS.items())
POINTER_RANGES = OrderedDict((name, meta["pointer_range"]) for name, meta in ROLE_CONSTANTS.items())
ROLE_BLOCK_SLOT_RANGES = OrderedDict((name, meta["block_slot_range"]) for name, meta in ROLE_CONSTANTS.items())
ROLE_MAP = OrderedDict((name, meta["signature"].hex().upper()) for name, meta in ROLE_CONSTANTS.items())

FULL_BLOCK_ADDRS = [
    0xCF2B0F, 0xCF3135, 0xCF3722, 0xCF3D2C, 0xCF4312,
    0xCF490C, 0xCF4F13, 0xCF5543, 0xCF599B, 0xCF5F56,
    0xCF6533, 0xCF6A5E, 0xCF7076, 0xCF7650, 0xCF7B68,
    0xCF805E, 0xCF86AC, 0xCF8C3F, 0xCF921B, 0xCF9886,
    0xCF9EBB, 0xCFA142, 0xCFA765, 0xCFAC23, 0xCFB233,
    0xCFB820, 0xCFBD6E, 0xCFC2EE, 0xCFC908, 0xCFCF45,
    0xCFD4C3, 0xCFDAD5, 0xCFE0E2, 0xCFE6D0, 0xCFECDA,
    0xCFF323, 0xCFF962, 0xCFFD16, 0xD00380, 0xD009BC,
    0xD01000, 0xD0164B, 0xD01BE0, 0xD02212, 0xD02822,
    0xD02E5F, 0xD032CB, 0xD038A1, 0xD03EAF, 0xD043C3,
    0xD048A6, 0xD04C96, 0xD052D4, 0xD058DE, 0xD05DF3,
    0xD0636F, 0xD067CF, 0xD06D9A, 0xD06F5C, 0xD07581,
    0xD07B89, 0xD08180, 0xD08792, 0xD08D76, 0xD09371,
    0xD0999E, 0xD09EC4, 0xD0A333, 0xD0A8D0, 0xD0ADDD,
    0xD0B383, 0xD0B91F, 0xD0BD74, 0xD0C2FF, 0xD0C7D6,
]

FULL_BLOCK_INPUT_ADDRS = [addr & 0xFFFF for addr in FULL_BLOCK_ADDRS]


def _build_role_addr_records():
    records = []
    full_index_by_addr = {addr: index for index, addr in enumerate(FULL_BLOCK_ADDRS)}

    for role_name, meta in ROLE_CONSTANTS.items():
        start_addr = meta["block_start"]
        start_index = full_index_by_addr.get(start_addr)
        if start_index is None:
            continue

        end_index = min(start_index + 30, len(FULL_BLOCK_ADDRS))
        for block_addr in FULL_BLOCK_ADDRS[start_index:end_index]:
            records.append(
                {
                    "role": role_name,
                    "signature": meta["signature"],
                    "full_addr": block_addr,
                    "input_addr": block_addr & 0xFFFF,
                }
            )

    return records


ROLE_ADDR_RECORDS = _build_role_addr_records()

class TextHandoverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("大航海时代2 - 压缩文本接管工具")
        self.root.geometry("1020x790")
        self.root.minsize(960, 720)

        self.rom_path_var = tk.StringVar(value="尚未选择 ROM...")
        self.role_var = tk.StringVar(value="全文本")
        self.modify_sentence_var = tk.StringVar()
        self.live_hex_var = tk.StringVar()
        self.status_var = tk.StringVar(value="未加载")

        self.rom_path = ""
        self.normal_table = {}
        self.katakana_table = {}
        self.reverse_normal_table = {}
        self.reverse_katakana_table = {}
        self.variant_map = {}

        self.dump_blocks = []
        self.dump_block_index_by_addr = {}
        self.character_streams = {}
        self.role_pointer_entries = {}
        self.full_sentence_items = []
        self.current_sentence_items = []
        self.selected_sentence_index = None
        self.preview_source = "dump"

        if not os.path.exists(RECORD_DIR):
            os.makedirs(RECORD_DIR)

        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self):
        frame_top = tk.LabelFrame(
            self.root,
            text="第一步：ROM 侦察与档案中心",
            font=("Microsoft YaHei", 12, "bold"),
            padx=10,
            pady=10,
        )
        frame_top.pack(fill=tk.X, padx=18, pady=(14, 10))

        row1 = tk.Frame(frame_top)
        row1.pack(fill=tk.X, anchor=tk.W)
        self._btn(row1, "选择目标 ROM", self.select_rom, 0, 15)
        tk.Label(row1, textvariable=self.rom_path_var, fg="red", font=("Microsoft YaHei", 10)).grid(
            row=0, column=1, padx=(10, 16), sticky=tk.W
        )
        self._btn(row1, "检测 ROM 补丁", self.detect_rom_patch, 2, 14)
        self._btn(row1, "加载普通码表", self.load_normal_table, 3, 12)
        self._btn(row1, "加载片假名码表", self.load_katakana_table, 4, 13)
        self._btn(row1, "加载繁简映射表", self.load_variant_map, 5, 13)
        self._btn(row1, "加载导出明文编码", self.load_dump_file, 6, 15)
        self._btn(row1, "加载翻译TXT", self.load_translation_txt, 7, 12)

        row2 = tk.Frame(frame_top)
        row2.pack(fill=tk.X, anchor=tk.W, pady=(12, 0))
        tk.Label(row2, text="1. 选择观察角色:", font=("Microsoft YaHei", 10)).grid(
            row=0, column=0, padx=(0, 6), sticky=tk.W
        )
        self.role_combo = ttk.Combobox(
            row2,
            textvariable=self.role_var,
            values=["全文本"] + list(ROLE_SIGNATURES.keys()),
            state="readonly",
            width=10,
        )
        self.role_combo.grid(row=0, column=1, padx=(0, 16), sticky=tk.W)
        self.role_combo.bind("<<ComboboxSelected>>", self.refresh_view_for_role)
        self._btn(row2, "2. 获取文本指针", self.get_text_pointer, 2, 15)
        self._btn(row2, "3. 改写文本指针", self.rewrite_text_pointer, 3, 15)

        row3 = tk.Frame(frame_top)
        row3.pack(fill=tk.X, anchor=tk.W, pady=(12, 0))
        self._btn(row3, "一键导出全量文本", self.export_full_text, 0, 18)
        self._btn(row3, "导出文本块编码", self.export_block_encoding, 1, 18)

        ttk.Separator(self.root, orient="horizontal").pack(fill=tk.X, padx=12, pady=(6, 8))

        main = tk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        tk.Label(main, text="原始句编码检视窗 (Hex):", font=("Microsoft YaHei", 10)).pack(anchor=tk.W)
        self.raw_hex_text = tk.Text(main, height=2, font=("Consolas", 10), wrap="none")
        self.raw_hex_text.pack(fill=tk.X, pady=(4, 12))
        self.raw_hex_text.bind("<KeyRelease>", lambda _e: self._sync_selected_hex_from_editor())

        tk.Label(main, text="全景雷达 (全局句号 : 解码明文):", font=("Microsoft YaHei", 10)).pack(anchor=tk.W)
        radar_frame = tk.Frame(main)
        radar_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 12))
        self.radar_list = tk.Listbox(radar_frame, font=("Consolas", 10), activestyle="none")
        radar_scroll = ttk.Scrollbar(radar_frame, orient="vertical", command=self.radar_list.yview)
        self.radar_list.configure(yscrollcommand=radar_scroll.set)
        self.radar_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        radar_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.radar_list.bind("<<ListboxSelect>>", self._on_record_select)

        tk.Label(main, text="战术修改句:", font=("Microsoft YaHei", 10)).pack(anchor=tk.W)
        self.modify_sentence_entry = tk.Entry(main, textvariable=self.modify_sentence_var, font=("Microsoft YaHei", 10))
        self.modify_sentence_entry.pack(fill=tk.X, pady=(4, 10))
        self.modify_sentence_entry.bind("<KeyRelease>", lambda _e: self._update_live_hex_preview())
        self.modify_sentence_entry.bind("<Return>", lambda _e: self._apply_sentence_edit())

        bottom = tk.Frame(main)
        bottom.pack(fill=tk.X, anchor=tk.W)
        tk.Label(bottom, text="实时 Hex:", font=("Microsoft YaHei", 10)).grid(row=0, column=0, sticky=tk.W)
        self.live_hex_entry = tk.Entry(bottom, textvariable=self.live_hex_var, font=("Consolas", 10))
        self.live_hex_entry.grid(row=0, column=1, sticky=tk.EW, padx=(6, 10))
        self.live_hex_entry.configure(state="readonly")
        bottom.columnconfigure(1, weight=1)

        tk.Button(
            bottom,
            text="全局字库校验",
            command=self.global_charset_check,
            bg="#ff6a00",
            fg="white",
            activebackground="#e55f00",
            activeforeground="white",
            relief=tk.RAISED,
            font=("Microsoft YaHei", 10, "bold"),
            width=16,
        ).grid(row=0, column=2, sticky=tk.E, padx=(10, 0))

    def _btn(self, parent, text, command, column, width):
        tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg="#f5f5f5",
            relief=tk.RAISED,
            font=("Microsoft YaHei", 9),
        ).grid(row=0, column=column, padx=(0, 8), pady=3, sticky=tk.W)

    # ---------------- 鍩虹宸ュ叿 ----------------
    def _info(self, title, msg):
        messagebox.showinfo(title, msg)

    def _warn(self, title, msg):
        messagebox.showwarning(title, msg)

    def _error(self, title, msg):
        messagebox.showerror(title, msg)

    def _ensure_rom_selected(self):
        if not self.rom_path:
            self._error("閿欒", "璇峰厛閫夋嫨鐩爣 ROM")
            return ""
        return self.rom_path

    def _current_role(self):
        role = self.role_var.get().strip()
        return role if role in ("全文本", *ROLE_SIGNATURES.keys()) else "全文本"

    def _sentence_hex(self, sentence_bytes):
        return sentence_bytes.hex(" ").upper()

    def _build_reverse_table(self, table):
        reverse = {}
        for code, text in table.items():
            if text and text not in reverse:
                reverse[text] = code
        return reverse

    def _parse_tbl(self, path):
        table = {}
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or "=" not in line or line.startswith("#"):
                    continue
                key, value = line.split("=", 1)
                key = key.strip().replace(" ", "")
                value = value.strip()
                if not key:
                    continue
                try:
                    table[int(key, 16)] = value
                except ValueError:
                    continue
        return table

    def _parse_variant_map(self, path):
        mapping = {}
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                left, right = line.split("=", 1)
                left = left.strip()
                right = right.strip()
                if not left or not right:
                    continue
                mapping.setdefault(left, set()).add(right)
                mapping.setdefault(right, set()).add(left)
                mapping.setdefault(left, set()).add(left)
                mapping.setdefault(right, set()).add(right)
        return {key: sorted(values, key=len, reverse=True) for key, values in mapping.items()}

    def _expand_variant_candidates(self, text, pos):
        candidates = [text[pos:pos + size] for size in range(1, min(4, len(text) - pos) + 1)]
        expanded = set()
        ordered = []
        for candidate in sorted(candidates, key=len, reverse=True):
            if candidate not in expanded:
                expanded.add(candidate)
                ordered.append(candidate)
            for alt in self.variant_map.get(candidate, []):
                if alt not in expanded:
                    expanded.add(alt)
                    ordered.append(alt)
        return ordered

    def _find_best_match(self, text, pos, reverse_table):
        candidates = self._expand_variant_candidates(text, pos)
        best_source = None
        best_token = None
        for source in candidates:
            if source in reverse_table:
                best_source = source
                best_token = text[pos:pos + len(source)]
                break
        return best_source, best_token

    def _decode_bytes(self, data_bytes):
        parts = []
        katakana_mode = False
        i = 0
        while i < len(data_bytes):
            b = data_bytes[i]
            if b == 0x00:
                parts.append("[END]")
                i += 1
                continue
            if b == 0x1B and i + 1 < len(data_bytes):
                next_b = data_bytes[i + 1]
                if next_b == 0x4B:
                    katakana_mode = True
                    i += 2
                    continue
                if next_b == 0x48:
                    katakana_mode = False
                    i += 2
                    continue
            table = self.katakana_table if katakana_mode else self.normal_table
            if i + 1 < len(data_bytes):
                pair = (b << 8) | data_bytes[i + 1]
                if pair in table:
                    parts.append(table[pair])
                    i += 2
                    continue
            if b in table:
                parts.append(table[b])
                i += 1
                continue
            parts.append(f"{{{b:02X}}}")
            i += 1
        return "".join(parts).replace("[END]", "\n")

    def _encode_text(self, text):
        if not text:
            return [], []
        tokens = []
        warnings = []
        pos = 0
        mode = "normal"
        while pos < len(text):
            normal_match, normal_token = self._find_best_match(text, pos, self.reverse_normal_table)
            kata_match, kata_token = self._find_best_match(text, pos, self.reverse_katakana_table)

            best_mode = None
            best_source = None
            best_token = None
            if normal_match and kata_match:
                if len(normal_match) >= len(kata_match):
                    best_mode = "normal"
                    best_source = normal_match
                    best_token = normal_token
                else:
                    best_mode = "katakana"
                    best_source = kata_match
                    best_token = kata_token
            elif normal_match:
                best_mode = "normal"
                best_source = normal_match
                best_token = normal_token
            elif kata_match:
                best_mode = "katakana"
                best_source = kata_match
                best_token = kata_token

            if best_token is None:
                warnings.append(f"鏃犳硶缂栫爜: {text[pos]!r} @ {pos}")
                pos += 1
                continue

            if best_mode != mode:
                tokens.extend([0x1B, 0x4B] if best_mode == "katakana" else [0x1B, 0x48])
                mode = best_mode

            code = self.reverse_normal_table[best_source] if best_mode == "normal" else self.reverse_katakana_table[best_source]
            if code > 0xFF:
                tokens.extend([(code >> 8) & 0xFF, code & 0xFF])
            else:
                tokens.append(code)
            pos += len(best_token)

        if mode == "katakana":
            tokens.extend([0x1B, 0x48])
        return tokens, warnings

    def _get_item_encoded_bytes(self, item):
        raw_hex = item.get("hex", "")
        if raw_hex and raw_hex.strip():
            compact = re.sub(r"\s+", "", raw_hex)
            if len(compact) % 2 != 0 or re.search(r"[^0-9A-Fa-f]", compact):
                raise ValueError(f"第 {item.get('seq', '?')} 句 Hex 编码格式错误")
            data = bytes.fromhex(compact)
            while data.endswith(b"\x00"):
                data = data[:-1]
            return data, []

        encoded, warnings = self._encode_text(item.get("text", ""))
        return bytes(encoded), warnings

    # ---------------- 鐮佽〃鍔犺浇 ----------------
    def select_rom(self):
        filepath = filedialog.askopenfilename(
            title="选择目标 ROM",
            filetypes=[("SNES ROM", "*.sfc *.smc"), ("All Files", "*.*")],
        )
        if filepath:
            self.rom_path = filepath
            self.rom_path_var.set(filepath)

    def load_normal_table(self):
        filepath = filedialog.askopenfilename(
            title="选择普通码表",
            filetypes=[("TBL", "*.tbl"), ("All Files", "*.*")],
        )
        if not filepath:
            return
        self.normal_table = self._parse_tbl(filepath)
        self.reverse_normal_table = self._build_reverse_table(self.normal_table)
        self.status_var.set(f"普通码表已加载: {os.path.basename(filepath)} ({len(self.normal_table)} 项)")
        self._update_live_hex_preview()

    def load_katakana_table(self):
        filepath = filedialog.askopenfilename(
            title="选择片假名码表",
            filetypes=[("TBL", "*.tbl"), ("All Files", "*.*")],
        )
        if not filepath:
            return
        self.katakana_table = self._parse_tbl(filepath)
        self.reverse_katakana_table = self._build_reverse_table(self.katakana_table)
        self.status_var.set(f"片假名码表已加载: {os.path.basename(filepath)} ({len(self.katakana_table)} 项)")
        self._update_live_hex_preview()

    def load_variant_map(self):
        filepath = filedialog.askopenfilename(
            title="选择繁简映射表",
            filetypes=[("Text", "*.txt *.tbl *.map"), ("All Files", "*.*")],
        )
        if not filepath:
            return
        self.variant_map = self._parse_variant_map(filepath)
        self.status_var.set(f"繁简映射表已加载: {os.path.basename(filepath)} ({len(self.variant_map)} 项)")
        self._update_live_hex_preview()

    def detect_rom_patch(self):
        rom_path = self._ensure_rom_selected()
        if not rom_path:
            return
        try:
            with open(rom_path, "rb") as handle:
                handle.seek(HOOK_ADDR)
                hook_check = handle.read(4)
            if hook_check != bytes.fromhex("5CE002E0"):
                self._info("妫€娴嬬粨鏋?", "鏈娴嬪埌鎺ョ閽╁瓙銆?")
                return
            self._info("妫€娴嬬粨鏋?", "宸叉娴嬪埌鎺ョ閽╁瓙銆?")
        except Exception as exc:
            self._error("閿欒", f"妫€娴嬪け璐ワ細{exc}")

    # ---------------- 瀵煎叆/瀵煎嚭 ----------------
    def _parse_dump_file(self, path):
        blocks = []
        current = None
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                match = re.match(r"^\[Block\s+(\d+)\].*?\$([0-9A-Fa-f]+)", line)
                if match:
                    if current is not None:
                        current["bytes"] = bytes(current["bytes"])
                        blocks.append(current)
                    current = {
                        "index": int(match.group(1)),
                        "address": int(match.group(2), 16),
                        "bytes": bytearray(),
                    }
                    continue
                if current is None:
                    continue
                current["bytes"].extend(int(token, 16) for token in re.findall(r"\b([0-9A-Fa-f]{2})\b", line))
        if current is not None:
            current["bytes"] = bytes(current["bytes"])
            blocks.append(current)
        blocks.sort(key=lambda item: item["address"])
        return blocks

    def _load_role_pointer_entries(self):
        self.role_pointer_entries = {}
        if not self.rom_path:
            return

        with open(self.rom_path, "rb") as handle:
            for role_name, (start_addr, end_addr) in POINTER_RANGES.items():
                if end_addr < start_addr:
                    continue
                handle.seek(start_addr)
                raw = handle.read(end_addr - start_addr + 1)
                entry_count = len(raw) // 2
                offsets = [
                    int.from_bytes(raw[index * 2 : index * 2 + 2], "little")
                    for index in range(entry_count)
                ]
                self.role_pointer_entries[role_name] = offsets

    def _collect_role_sentences_from_pointers(self, role_name, stream_info, seq_start):
        sentences = []
        offsets = self.role_pointer_entries.get(role_name, [])
        if not offsets:
            return sentences, seq_start

        stream_bytes = stream_info["stream_bytes"]
        blocks = stream_info["blocks"]
        for pointer_index, offset in enumerate(offsets):
            if offset >= len(stream_bytes):
                continue

            end = offset
            while end < len(stream_bytes) and stream_bytes[end] != 0x00:
                end += 1

            raw = stream_bytes[offset:end]
            page = offset // PAGE_SIZE
            local = offset % PAGE_SIZE
            block_addr = blocks[page]["address"] if 0 <= page < len(blocks) else None
            sentences.append(
                {
                    "seq": seq_start,
                    "offset": offset,
                    "page": page,
                    "local": local,
                    "length": len(raw),
                    "hex": raw.hex(" ").upper(),
                    "text": self._decode_bytes(raw),
                    "terminated": end < len(stream_bytes),
                    "character": role_name,
                    "role": role_name,
                    "ptr": f"{offset:04X}",
                    "pointer_index": pointer_index,
                    "block_addr": block_addr,
                    "block_seq": page + 1,
                }
            )
            seq_start += 1

        return sentences, seq_start

    def rebuild_character_streams(self):
        self.character_streams = {}
        names = list(CHARACTER_BLOCK_STARTS.keys())
        for index, name in enumerate(names):
            start_addr = CHARACTER_BLOCK_STARTS[name]
            start_index = self.dump_block_index_by_addr.get(start_addr)
            if start_index is None:
                continue
            if index + 1 < len(names):
                next_addr = CHARACTER_BLOCK_STARTS[names[index + 1]]
                end_index = self.dump_block_index_by_addr.get(next_addr, len(self.dump_blocks)) - 1
            else:
                end_index = len(self.dump_blocks) - 1
            if end_index < start_index:
                continue
            used_blocks = self.dump_blocks[start_index:end_index + 1]
            stream_bytes = b"".join(block["bytes"] for block in used_blocks)
            self.character_streams[name] = {
                "start_block_addr": start_addr,
                "start_block_index": start_index,
                "end_block_index": end_index,
                "blocks": used_blocks,
                "stream_bytes": stream_bytes,
                "page_count": (len(stream_bytes) + PAGE_SIZE - 1) // PAGE_SIZE,
            }

    def collect_full_sentences(self):
        sentences = []
        seq = 1
        for name in CHARACTER_BLOCK_STARTS.keys():
            stream_info = self.character_streams.get(name)
            if stream_info is None:
                continue
            if self.role_pointer_entries.get(name):
                role_sentences, seq = self._collect_role_sentences_from_pointers(name, stream_info, seq)
                sentences.extend(role_sentences)
                continue

            stream_bytes = stream_info["stream_bytes"]
            start = 0
            while start < len(stream_bytes):
                while start < len(stream_bytes) and stream_bytes[start] == 0x00:
                    start += 1
                if start >= len(stream_bytes):
                    break
                end = start
                while end < len(stream_bytes) and stream_bytes[end] != 0x00:
                    end += 1
                raw = stream_bytes[start:end]
                sentences.append(
                    {
                        "seq": seq,
                        "offset": start,
                        "page": start // PAGE_SIZE,
                        "local": start % PAGE_SIZE,
                        "length": len(raw),
                        "hex": raw.hex(" ").upper(),
                        "text": self._decode_bytes(raw),
                        "terminated": end < len(stream_bytes),
                        "character": name,
                        "role": name,
                        "ptr": f"{start:04X}",
                        "pointer_index": seq - 1,
                        "block_addr": stream_info["blocks"][start // PAGE_SIZE]["address"] if start // PAGE_SIZE < len(stream_info["blocks"]) else None,
                        "block_seq": start // PAGE_SIZE + 1,
                    }
                )
                seq += 1
                start = end + 1
        return sentences

    def load_dump_file(self):
        path = filedialog.askopenfilename(
            title="加载导出明文编码",
            filetypes=[("Text", "*.txt"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            self.dump_blocks = self._parse_dump_file(path)
            self.dump_block_index_by_addr = {block["address"]: idx for idx, block in enumerate(self.dump_blocks)}
            self.rebuild_character_streams()
            self._load_role_pointer_entries()
            self.full_sentence_items = self.collect_full_sentences()
            self.current_sentence_items = [dict(item) for item in self.full_sentence_items]
            self.role_var.set("全文本")
            self.preview_source = "dump"
            self._refresh_record_list()
            self.status_var.set(f"已加载导出明文编码: {os.path.basename(path)} ({len(self.dump_blocks)} blocks, {len(self.full_sentence_items)} 句)")
        except Exception as exc:
            self._error("鎵弿澶辫触", "璇诲彇鍑洪敊锛? " + str(exc))

    def _collect_sentence_items_for_translation(self, dump_path=None):
        if dump_path:
            previous_dump_blocks = self.dump_blocks
            previous_dump_block_index_by_addr = self.dump_block_index_by_addr
            previous_character_streams = self.character_streams
            previous_role_pointer_entries = self.role_pointer_entries
            try:
                self.dump_blocks = self._parse_dump_file(dump_path)
                self.dump_block_index_by_addr = {block["address"]: idx for idx, block in enumerate(self.dump_blocks)}
                self.rebuild_character_streams()
                self._load_role_pointer_entries()
                return self.collect_full_sentences()
            finally:
                self.dump_blocks = previous_dump_blocks
                self.dump_block_index_by_addr = previous_dump_block_index_by_addr
                self.character_streams = previous_character_streams
                self.role_pointer_entries = previous_role_pointer_entries

        if not self.dump_blocks:
            return []

        self._load_role_pointer_entries()
        return self.collect_full_sentences()

    def _collect_sentence_items_from_pointers_only(self):
        self._load_role_pointer_entries()
        sentences = []
        seq = 1
        for role_name in CHARACTER_BLOCK_STARTS.keys():
            offsets = self.role_pointer_entries.get(role_name, [])
            for pointer_index, offset in enumerate(offsets):
                page = offset // PAGE_SIZE
                local = offset % PAGE_SIZE
                sentences.append(
                    {
                        "seq": seq,
                        "offset": offset,
                        "page": page,
                        "local": local,
                        "length": 0,
                        "hex": "",
                        "text": "",
                        "terminated": False,
                        "character": role_name,
                        "role": role_name,
                        "ptr": f"{offset:04X}",
                        "pointer_index": pointer_index,
                        "block_addr": None,
                        "block_seq": page + 1,
                    }
                )
                seq += 1
        return sentences

    def load_translation_txt(self):
        path = filedialog.askopenfilename(
            title="选择翻译TXT",
            filetypes=[("Text", "*.txt"), ("TSV", "*.tsv"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            pointer_sentence_items = self._collect_sentence_items_from_pointers_only()
            if not pointer_sentence_items:
                self._error("错误", "未能从 ROM 读取到任何指针数据。")
                return

            with open(path, "r", encoding="utf-8-sig", errors="ignore") as handle:
                lines = [line.rstrip("\r\n") for line in handle]
            while lines and lines[-1] == "":
                lines.pop()
            if not lines:
                self._error("閿欒", "缈昏瘧鏂囦欢涓虹┖銆?")
                return

            if "\t" in lines[0] and lines[0].split("\t")[0].lower() == "seq":
                translated_lines = []
                for line in lines[1:]:
                    if not line.strip():
                        translated_lines.append("")
                        continue
                    parts = line.split("\t")
                    translated_lines.append(parts[6] if len(parts) >= 7 else parts[-1])
            else:
                translated_lines = lines

            source_count = len(pointer_sentence_items)
            translated_count = len(translated_lines)
            apply_count = min(source_count, translated_count)
            translated_items = [dict(item) for item in pointer_sentence_items]
            for index in range(apply_count):
                translated_items[index]["text"] = translated_lines[index]
                try:
                    encoded, _warnings = self._encode_text(translated_lines[index])
                    translated_items[index]["hex"] = " ".join(f"{byte:02X}" for byte in encoded)
                except Exception:
                    translated_items[index]["hex"] = ""
            self.current_sentence_items = translated_items

            self.preview_source = "translation"
            self._refresh_record_list()
            if translated_count != source_count:
                self._warn("数量不一致", "原句子数: " + str(source_count) + "\n翻译行数: " + str(translated_count) + "\n已按顺序应用前 " + str(apply_count) + " 句。")
            else:
                self._info("完成", f"已按顺序导入 {apply_count} 句翻译。")
            self.status_var.set(f"翻译TXT已加载: {os.path.basename(path)} 源={source_count} 译={translated_count} 应用={apply_count}")
        except Exception as exc:
            self._error("鍔犺浇澶辫触", str(exc))

    def export_full_text(self):
        try:
            if not self.current_sentence_items:
                self._warn("警告", "没有可导出的文本。")
                return
            directory = filedialog.askdirectory(title="选择导出目录")
            if not directory:
                return
            path = os.path.join(directory, f"全量文本_{time.strftime('%Y%m%d_%H%M%S')}.txt")
            with open(path, "w", encoding="utf-8") as handle:
                for item in self.current_sentence_items:
                    handle.write(f"{item.get('text', '')}\n")
            self._info("导出完成", path)
        except Exception as exc:
            self._error("导出失败", str(exc))

    def _get_role_block_starts(self):
        full_index_by_addr = {addr: index for index, addr in enumerate(FULL_BLOCK_ADDRS)}
        starts = []
        for role_name in ROLE_CONSTANTS.keys():
            start_addr = ROLE_CONSTANTS[role_name]["block_start"]
            starts.append((role_name, full_index_by_addr[start_addr]))
        return starts

    def export_block_encoding(self):
        try:
            if not self.current_sentence_items:
                self._warn("警告", "没有可导出的文本。")
                return

            directory = filedialog.askdirectory(title="选择导出目录")
            if not directory:
                return

            path = os.path.join(directory, f"文本块编码_{time.strftime('%Y%m%d_%H%M%S')}.txt")
            sentence_items = sorted(self.current_sentence_items, key=lambda item: item.get("seq", 0))
            role_groups = OrderedDict((name, []) for name in ROLE_CONSTANTS.keys())
            for item in sentence_items:
                role_name = item.get("character")
                if role_name in role_groups:
                    role_groups[role_name].append(item)

            with open(path, "w", encoding="utf-8") as handle:
                handle.write("=" * 70 + "\n")
                handle.write("  大航海时代2 - 文本块编码导出\n")
                handle.write("  仅导出句子编码，句间以 00 断句\n")
                handle.write("=" * 70 + "\n\n")

                self._load_role_pointer_entries()
                for role_index, (role_name, start_index) in enumerate(self._get_role_block_starts(), start=1):
                    items = role_groups.get(role_name, [])
                    if not items:
                        continue

                    expected_count = len(self.role_pointer_entries.get(role_name, []))
                    if expected_count and len(items) != expected_count:
                        raise ValueError(f"{role_name} 句数不匹配: 原始 {expected_count} / 当前 {len(items)}")

                    encoded_stream = bytearray()
                    for item in items:
                        encoded, warnings = self._get_item_encoded_bytes(item)
                        if warnings:
                            raise ValueError(f"{role_name} 第 {item.get('seq', '?')} 句存在未识别字符: {warnings[0]}")
                        encoded_stream.extend(encoded)
                        encoded_stream.append(0x00)

                    block_buffers = []
                    cursor = 0
                    block_count = max(1, (len(encoded_stream) + PAGE_SIZE - 1) // PAGE_SIZE)
                    for block_offset in range(block_count):
                        block_addr = FULL_BLOCK_ADDRS[(start_index + block_offset) % len(FULL_BLOCK_ADDRS)]
                        chunk = encoded_stream[cursor:cursor + PAGE_SIZE]
                        block_buffers.append((block_addr, chunk))
                        cursor += len(chunk)

                    if cursor < len(encoded_stream):
                        raise ValueError(f"{role_name} 编码导出未完成: {cursor} / {len(encoded_stream)}")

                    handle.write(f"[Role {role_index:02d}] {role_name}\n")
                    handle.write("=" * 70 + "\n")
                    for block_offset, (block_addr, chunk) in enumerate(block_buffers, start=1):
                        handle.write(f"[Block {block_offset:04d}] 绝对精准 ROM 物理地址: ${block_addr:06X}\n")
                        handle.write("-" * 70 + "\n")
                        if chunk:
                            for offset in range(0, len(chunk), 16):
                                line = chunk[offset:offset + 16]
                                handle.write(" ".join(f"{byte:02X}" for byte in line) + "\n")
                        handle.write("\n")
                    handle.write("\n")

            self._info("导出完成", path)
        except Exception as exc:
            self._error("导出失败", str(exc))

    # ---------------- 鍒楄〃/缂栬緫 ----------------
    def _current_sentence_items(self):
        role = self._current_role()
        if role == "全文本":
            return self.current_sentence_items
        return [item for item in self.current_sentence_items if item.get("character") == role]

    def _refresh_record_list(self):
        shown = self._current_sentence_items()
        self.radar_list.delete(0, tk.END)
        for item in shown:
            text = item.get("text", "")
            if len(text) > 56:
                text = text[:56] + "..."
            self.radar_list.insert(
                tk.END,
                f"{item['seq']:05d}  off={item['offset']:05X}  page={item['page']:03d}  local={item['local']:03X}  {text}",
            )
        if shown:
            self.radar_list.selection_set(0)
            self.radar_list.activate(0)
            self.selected_sentence_index = 0
            self._show_selected_sentence(0)
        else:
            self.selected_sentence_index = None
            self.raw_hex_text.delete("1.0", tk.END)
            self.modify_sentence_var.set("")
            self.live_hex_var.set("")

    def _show_selected_sentence(self, index):
        shown = self._current_sentence_items()
        if not (0 <= index < len(shown)):
            return
        item = shown[index]
        self.selected_sentence_index = index
        self.raw_hex_text.delete("1.0", tk.END)
        self.raw_hex_text.insert(tk.END, item.get("hex", ""))
        self.modify_sentence_var.set(item.get("text", ""))
        self.live_hex_var.set(item.get("hex", ""))

    def _on_record_select(self, _event=None):
        selection = self.radar_list.curselection()
        if not selection:
            return
        self._show_selected_sentence(selection[0])

    def refresh_view_for_role(self, _event=None):
        self._refresh_record_list()

    def _sync_selected_hex_from_editor(self):
        shown = self._current_sentence_items()
        if self.selected_sentence_index is None or not (0 <= self.selected_sentence_index < len(shown)):
            return
        item = shown[self.selected_sentence_index]
        item["hex"] = self.raw_hex_text.get("1.0", tk.END).replace("\r", "").strip()

    def _update_live_hex_preview(self):
        text = self.modify_sentence_var.get()
        if not text:
            self.live_hex_var.set("")
            return
        try:
            encoded, warnings = self._encode_text(text)
            self.live_hex_var.set(" ".join(f"{byte:02X}" for byte in encoded))
            if warnings:
                self.status_var.set(warnings[0])
        except Exception as exc:
            self.live_hex_var.set(f"ERROR: {exc}")

    def _apply_sentence_edit(self):
        shown = self._current_sentence_items()
        if self.selected_sentence_index is None or not (0 <= self.selected_sentence_index < len(shown)):
            return
        item = shown[self.selected_sentence_index]
        text = self.modify_sentence_var.get().strip()
        if not text:
            return
        item["text"] = text
        try:
            encoded, _warnings = self._encode_text(text)
            item["hex"] = " ".join(f"{byte:02X}" for byte in encoded)
            self.raw_hex_text.delete("1.0", tk.END)
            self.raw_hex_text.insert(tk.END, item["hex"])
        except Exception as exc:
            self._error("缂栫爜澶辫触", str(exc))
        self._refresh_record_list()

    # ---------------- 鍏跺畠 ----------------
    def global_charset_check(self):
        try:
            if not self.current_sentence_items:
                self._warn("提示", "当前没有可校验的句子。")
                return

            errors = []
            for item in self.current_sentence_items:
                text = item.get("text", "")
                if not text:
                    continue

                pos = 0
                while pos < len(text):
                    normal_match, _normal_token = self._find_best_match(text, pos, self.reverse_normal_table)
                    kata_match, _kata_token = self._find_best_match(text, pos, self.reverse_katakana_table)
                    if normal_match or kata_match:
                        if normal_match and kata_match:
                            advance = max(len(normal_match), len(kata_match))
                        elif normal_match:
                            advance = len(normal_match)
                        else:
                            advance = len(kata_match)
                        pos += advance
                        continue

                    errors.append(
                        f"{item.get('seq', '?')}句"
                        f"[{item.get('character', '全文本')}]"
                        f" 第{pos + 1}个字符「{text[pos]}」未被码表识别"
                    )
                    pos += 1

            if errors:
                self._error("校验失败", "\n".join(errors[:40]))
            else:
                self._info("校验通过", "全部文本均可被当前字库识别。")
        except Exception as exc:
            self._error("校验失败", str(exc))

    def detect_rom_patch(self):
        rom_path = self._ensure_rom_selected()
        if not rom_path:
            return
        try:
            with open(rom_path, "rb") as handle:
                handle.seek(HOOK_ADDR)
                hook_check = handle.read(4)
            if hook_check != bytes.fromhex("5CE002E0"):
                self._info("检测结果", "未检测到接管钩子。")
                return
            self._info("检测结果", "已检测到接管钩子。")
        except Exception as exc:
            self._error("閿欒", f"妫€娴嬪け璐ワ細{exc}")

    def _parse_hex_addr(self, text, field_name):
        value = text.strip().upper().replace("$", "")
        if not value:
            raise ValueError(f"{field_name} 不能为空。")
        return int(value, 16)

    def get_text_pointer(self):
        if not self.rom_path:
            self._error("错误", "请先选择 ROM。")
            return

        try:
            self._load_role_pointer_entries()
        except Exception as exc:
            self._error("错误", f"读取文本指针失败: {exc}")
            return

        selected_role = self._current_role()
        if selected_role != "全文本":
            count = len(self.role_pointer_entries.get(selected_role, []))
            total_count = sum(len(self.role_pointer_entries.get(role_name, [])) for role_name in ROLE_SIGNATURES.keys())
            self._info("文本指针", f"{selected_role} 共有 {count} 句。\n全部文本合计: {total_count} 句。")
            return

        lines = []
        total_count = 0
        for role_name in ROLE_SIGNATURES.keys():
            count = len(self.role_pointer_entries.get(role_name, []))
            total_count += count
            lines.append(f"{role_name}: {count} 句")
        lines.append(f"全部文本合计: {total_count} 句")
        self._info("文本指针", "\n".join(lines))

    def rewrite_text_pointer(self):
        if not self.rom_path:
            self._error("错误", "请先选择 ROM。")
            return
        if not self.current_sentence_items:
            self._error("错误", "当前没有可写回的句子。")
            return

        try:
            self._load_role_pointer_entries()
        except Exception as exc:
            self._error("错误", f"读取文本指针失败: {exc}")
            return

        role_groups = OrderedDict((name, []) for name in ROLE_SIGNATURES.keys())
        for item in self.current_sentence_items:
            role_name = item.get("character")
            if role_name in role_groups:
                role_groups[role_name].append(item)

        try:
            new_role_offsets = {}
            for role_name, items in role_groups.items():
                expected_count = len(self.role_pointer_entries.get(role_name, []))
                actual_count = len(items)
                if expected_count != actual_count:
                    raise ValueError(f"{role_name} 句数不匹配: 原始 {expected_count} / 当前 {actual_count}")

                offsets = []
                cursor = 0
                for item in items:
                    encoded, warnings = self._get_item_encoded_bytes(item)
                    if warnings:
                        raise ValueError(f"{role_name} 第 {item.get('seq', '?')} 句存在未识别字符: {warnings[0]}")
                    offsets.append(cursor)
                    cursor += len(encoded) + 1

                new_role_offsets[role_name] = offsets

            with open(self.rom_path, "r+b") as rom:
                for role_name, offsets in new_role_offsets.items():
                    start_addr, end_addr = POINTER_RANGES[role_name]
                    expected_count = ((end_addr - start_addr) + 1) // 2
                    if len(offsets) != expected_count:
                        raise ValueError(f"{role_name} 指针数量不匹配: 原始 {expected_count} / 当前 {len(offsets)}")
                    rom.seek(start_addr)
                    for offset in offsets:
                        if offset > 0xFFFF:
                            raise ValueError(f"{role_name} 存在超过 16 位的指针偏移: {offset}")
                        rom.write(offset.to_bytes(2, "little"))

            self.role_pointer_entries = new_role_offsets
            total_count = sum(len(offsets) for offsets in new_role_offsets.values())
            self._info("完成", f"已改写 {len(new_role_offsets)} 个角色的文本指针，共 {total_count} 句。")
        except Exception as exc:
            self._error("改写失败", str(exc))


def main():
    root = tk.Tk()
    app = TextHandoverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
