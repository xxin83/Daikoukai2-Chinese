import os
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


KATAKANA_ON = b"\x1B\x4B"
KATAKANA_OFF = b"\x1B\x48"
END_BYTE = 0x00


@dataclass
class SentenceEntry:
    index: int
    start: int
    end: int
    slot_len: int
    gap_len: int
    raw_bytes: bytes
    raw_hex: str
    text: str
    original_text: str


def load_tbl(path: str) -> dict[bytes, str]:
    table: dict[bytes, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        left, right = line.split("=", 1)
        left = left.strip().replace(" ", "")
        if len(left) % 2 != 0:
            continue
        try:
            key = bytes.fromhex(left)
        except ValueError:
            continue
        table[key] = right
    return table


def load_alias_map(path: str) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    if not path:
        return mapping

    for raw_line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, aliases = line.split("=", 1)
        key = key.strip()
        values = [key] + [item.strip() for item in aliases.split(",") if item.strip()]
        bucket = set(values)
        for value in bucket:
            mapping.setdefault(value, set()).update(bucket)
    return mapping


def reverse_tbl(tbl: dict[bytes, str]) -> dict[str, list[bytes]]:
    rev: dict[str, list[bytes]] = {}
    for key, value in tbl.items():
        rev.setdefault(value, []).append(key)
    for key in rev:
        rev[key].sort(key=len)
    return rev


def build_token_lengths(*tables: dict[bytes, str]) -> list[int]:
    return sorted({len(key) for table in tables for key in table}, reverse=True)


def parse_address(value: str) -> int:
    text = value.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    if any(ch in text.lower() for ch in "abcdef"):
        return int(text, 16)
    return int(text)


def decode_bytes(data: bytes, normal_tbl: dict[bytes, str], kata_tbl: dict[bytes, str]) -> str:
    lengths = build_token_lengths(normal_tbl, kata_tbl)
    pos = 0
    use_kata = False
    out: list[str] = []

    while pos < len(data):
        if data[pos:pos + 2] == KATAKANA_ON:
            out.append(normal_tbl.get(KATAKANA_ON, "[片假名开]"))
            use_kata = True
            pos += 2
            continue
        if data[pos:pos + 2] == KATAKANA_OFF:
            out.append(normal_tbl.get(KATAKANA_OFF, "[片假名关]"))
            use_kata = False
            pos += 2
            continue

        table = kata_tbl if use_kata else normal_tbl
        matched = False
        for length in lengths:
            chunk = data[pos:pos + length]
            if chunk in table:
                out.append(table[chunk])
                pos += length
                matched = True
                break
        if matched:
            continue

        out.append(f"[{data[pos]:02X}]")
        pos += 1

    return "".join(out)


def tokenize_text(text: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        if text[pos] == "[":
            end = text.find("]", pos)
            if end != -1:
                tokens.append(text[pos:end + 1])
                pos = end + 1
                continue
        tokens.append(text[pos])
        pos += 1
    return tokens


def lookup_token_bytes(
    token: str,
    active_reverse: dict[str, list[bytes]],
    alias_map: dict[str, set[str]],
) -> bytes | None:
    candidates = [token]
    if token in alias_map:
        candidates.extend(sorted(alias_map[token]))

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate in active_reverse:
            return active_reverse[candidate][0]
    return None


def encode_text(
    text: str,
    normal_reverse: dict[str, list[bytes]],
    kata_reverse: dict[str, list[bytes]],
    alias_map: dict[str, set[str]],
) -> bytes:
    tokens = tokenize_text(text)
    use_kata = False
    encoded = bytearray()

    for token in tokens:
        if token == "[片假名开]":
            encoded.extend(KATAKANA_ON)
            use_kata = True
            continue
        if token == "[片假名关]":
            encoded.extend(KATAKANA_OFF)
            use_kata = False
            continue

        active_reverse = kata_reverse if use_kata else normal_reverse
        raw = lookup_token_bytes(token, active_reverse, alias_map)
        if raw is None:
            raise ValueError(f"无法编码字符或标记: {token}")
        encoded.extend(raw)

    encoded.append(END_BYTE)
    return bytes(encoded)


def format_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def analyze_text_encoding(
    text: str,
    normal_reverse: dict[str, list[bytes]],
    kata_reverse: dict[str, list[bytes]],
    alias_map: dict[str, set[str]],
) -> tuple[bytes | None, list[str]]:
    tokens = tokenize_text(text)
    use_kata = False
    encoded = bytearray()
    unknown_tokens: list[str] = []

    for token in tokens:
        if token == "[片假名开]":
            encoded.extend(KATAKANA_ON)
            use_kata = True
            continue
        if token == "[片假名关]":
            encoded.extend(KATAKANA_OFF)
            use_kata = False
            continue

        active_reverse = kata_reverse if use_kata else normal_reverse
        raw = lookup_token_bytes(token, active_reverse, alias_map)
        if raw is None:
            if token not in unknown_tokens:
                unknown_tokens.append(token)
            continue
        encoded.extend(raw)

    if unknown_tokens:
        return None, unknown_tokens

    encoded.append(END_BYTE)
    return bytes(encoded), []


def read_entries(
    rom_path: str,
    start_addr: int,
    count: int,
    gap_len: int,
    normal_tbl: dict[bytes, str],
    kata_tbl: dict[bytes, str],
) -> list[SentenceEntry]:
    rom = Path(rom_path).read_bytes()
    if start_addr < 0 or start_addr >= len(rom):
        raise ValueError("起始地址超出 ROM 范围。")

    pos = start_addr
    entries: list[SentenceEntry] = []

    index = 0
    while pos < len(rom) and index < count:
        start = rom.find(KATAKANA_ON, pos)
        if start < 0:
            break
        pos = start
        buf = bytearray()
        while pos < len(rom):
            value = rom[pos]
            buf.append(value)
            pos += 1
            if value == END_BYTE:
                break
        if not buf:
            break

        raw_bytes = bytes(buf)
        entry = SentenceEntry(
            index=index,
            start=start,
            end=pos - 1,
            slot_len=len(raw_bytes),
            gap_len=gap_len,
            raw_bytes=raw_bytes,
            raw_hex=" ".join(f"{b:02X}" for b in raw_bytes),
            text=decode_bytes(raw_bytes[:-1], normal_tbl, kata_tbl),
            original_text=decode_bytes(raw_bytes[:-1], normal_tbl, kata_tbl),
        )
        entries.append(entry)
        index += 1

    return entries


def parse_profile_log(path: str) -> list[dict[str, str]]:
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]") and line[1:-1].isdigit():
            if current:
                records.append(current)
            current = {"index": line[1:-1]}
            continue
        if "=" not in line or current is None:
            continue
        key, value = line.split("=", 1)
        current[key.strip()] = value

    if current:
        records.append(current)

    return records


def build_entries_from_records(
    records: list[dict[str, str]],
    normal_tbl: dict[bytes, str],
    kata_tbl: dict[bytes, str],
) -> list[SentenceEntry]:
    entries: list[SentenceEntry] = []

    for idx, record in enumerate(records):
        start_text = record.get("start")
        if not start_text:
            continue

        raw_hex = record.get("raw_hex", "").strip()
        raw_bytes = bytes.fromhex(raw_hex) if raw_hex else b""
        slot_len_text = record.get("slot_len")
        slot_len = int(slot_len_text) if slot_len_text else len(raw_bytes)
        gap_len_text = record.get("gap_len")
        gap_len = int(gap_len_text) if gap_len_text else 0
        start = parse_address(start_text)
        end_text = record.get("end")
        end = parse_address(end_text) if end_text else start + max(slot_len - 1, 0)

        if not raw_hex and raw_bytes:
            raw_hex = format_hex(raw_bytes)

        decoded_text = ""
        if raw_bytes:
            body = raw_bytes[:-1] if raw_bytes[-1:] == bytes([END_BYTE]) else raw_bytes
            decoded_text = decode_bytes(body, normal_tbl, kata_tbl)

        original_text = record.get("orig_text") or decoded_text
        current_text = record.get("new_text")
        if current_text is None:
            current_text = record.get("text")
        if current_text is None:
            current_text = original_text

        entry_index_text = record.get("index")
        entry_index = int(entry_index_text) if entry_index_text and entry_index_text.isdigit() else idx

        entries.append(
            SentenceEntry(
                index=entry_index,
                start=start,
                end=end,
                slot_len=slot_len,
                gap_len=gap_len,
                raw_bytes=raw_bytes,
                raw_hex=raw_hex,
                text=current_text,
                original_text=original_text,
            )
        )

    return entries


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ROM 句子提取与回写工具")
        self.root.geometry("1300x860")

        self.rom_path = tk.StringVar()
        self.normal_tbl_path = tk.StringVar()
        self.kata_tbl_path = tk.StringVar()
        self.alias_path = tk.StringVar()
        self.profile_path = tk.StringVar()
        self.export_path = tk.StringVar(value=os.path.abspath("sentence_export.txt"))
        self.write_path = tk.StringVar(value=os.path.abspath("patched_rom.sfc"))

        self.start_addr = tk.StringVar(value="0x0")
        self.count_var = tk.StringVar(value="10")
        self.gap_len = tk.StringVar(value="0")

        self.entries: list[SentenceEntry] = []
        self.normal_tbl: dict[bytes, str] = {}
        self.kata_tbl: dict[bytes, str] = {}
        self.alias_map: dict[str, set[str]] = {}
        self.normal_reverse: dict[str, list[bytes]] = {}
        self.kata_reverse: dict[str, list[bytes]] = {}
        self.current_encoded: bytes | None = None
        self.current_index: int | None = None
        self.suspend_select_event = False

        self._build_ui()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)

        self._path_row(frame, 0, "ROM 文件", self.rom_path, self.pick_rom)
        self._path_row(frame, 1, "普通码表", self.normal_tbl_path, self.pick_normal_tbl)
        self._path_row(frame, 2, "片假名码表", self.kata_tbl_path, self.pick_kata_tbl)
        self._path_row(frame, 3, "繁简对照", self.alias_path, self.pick_alias)
        self._path_row(frame, 4, "修改记录", self.profile_path, self.pick_profile)
        self._path_row(frame, 5, "导出 TXT", self.export_path, self.pick_export)
        self._path_row(frame, 6, "回写 ROM", self.write_path, self.pick_write_path)

        ttk.Label(frame, text="起始地址").grid(row=7, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.start_addr, width=20).grid(row=7, column=1, sticky="w", pady=6)

        ttk.Label(frame, text="句数").grid(row=7, column=2, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.count_var, width=12).grid(row=7, column=3, sticky="w", pady=6)

        ttk.Label(frame, text="扫描起点后按 1B 4B 找句").grid(row=7, column=4, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.gap_len, width=12).grid(row=7, column=5, sticky="w", pady=6)

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=8, column=0, columnspan=6, sticky="w", pady=(8, 10))
        ttk.Button(button_bar, text="读取", command=self.load_entries).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="加载翻译TXT", command=self.load_translation_txt).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="加载记录", command=self.load_profile_log).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="应用修改", command=self.apply_edit).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="导出 TXT", command=self.export_txt).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="回写 ROM", command=self.write_rom).pack(side="left")

        columns = ("idx", "start", "end", "slot", "raw_hex", "text")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        self.tree.grid(row=9, column=0, columnspan=6, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        headings = {
            "idx": "序号",
            "start": "起始",
            "end": "结束",
            "slot": "槽位",
            "raw_hex": "原始编码",
            "text": "句子",
        }
        widths = {
            "idx": 60,
            "start": 90,
            "end": 90,
            "slot": 70,
            "raw_hex": 430,
            "text": 470,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")

        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        ybar.grid(row=9, column=6, sticky="ns")
        self.tree.configure(yscrollcommand=ybar.set)

        editor = ttk.LabelFrame(frame, text="编辑")
        editor.grid(row=10, column=0, columnspan=7, sticky="nsew", pady=(12, 0))
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(1, weight=1)
        editor.rowconfigure(3, weight=1)

        self.info_var = tk.StringVar(value="未选择条目")
        ttk.Label(editor, textvariable=self.info_var).grid(row=0, column=0, sticky="w", padx=8, pady=6)

        orig_frame = ttk.LabelFrame(editor, text="原始内容")
        orig_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        orig_frame.columnconfigure(0, weight=1)
        orig_frame.rowconfigure(1, weight=1)

        self.orig_bytes_var = tk.StringVar(value="原始字节数: -")
        self.orig_hex_var = tk.StringVar(value="原始编码: -")
        ttk.Label(orig_frame, textvariable=self.orig_bytes_var).grid(row=0, column=0, sticky="w", padx=6, pady=(6, 2))
        ttk.Label(orig_frame, textvariable=self.orig_hex_var, wraplength=1180, justify="left").grid(
            row=1, column=0, sticky="ew", padx=6, pady=(0, 6)
        )
        self.orig_box = tk.Text(orig_frame, height=5, wrap="word")
        self.orig_box.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.orig_box.configure(state="disabled")

        mod_frame = ttk.LabelFrame(editor, text="修改内容")
        mod_frame.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
        mod_frame.columnconfigure(0, weight=1)
        mod_frame.rowconfigure(3, weight=1)

        self.mod_bytes_var = tk.StringVar(value="修改字节数: -")
        self.mod_hex_var = tk.StringVar(value="修改编码: -")
        self.unknown_var = tk.StringVar(value="未识别文字: 无")
        ttk.Label(mod_frame, textvariable=self.mod_bytes_var).grid(row=0, column=0, sticky="w", padx=6, pady=(6, 2))
        ttk.Label(mod_frame, textvariable=self.mod_hex_var, wraplength=1180, justify="left").grid(
            row=1, column=0, sticky="ew", padx=6, pady=(0, 2)
        )
        ttk.Label(mod_frame, textvariable=self.unknown_var, wraplength=1180, justify="left").grid(
            row=2, column=0, sticky="ew", padx=6, pady=(0, 4)
        )
        self.edit_box = tk.Text(mod_frame, height=8, wrap="word")
        self.edit_box.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.edit_box.bind("<KeyRelease>", self.on_edit_change)

        self.status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.status_var).grid(row=11, column=0, columnspan=7, sticky="w", pady=(8, 0))

        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        frame.columnconfigure(5, weight=1)
        frame.rowconfigure(9, weight=1)
        frame.rowconfigure(10, weight=1)

    def _path_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, columnspan=4, sticky="ew", padx=(0, 8), pady=5)
        ttk.Button(parent, text="选择", command=command).grid(row=row, column=5, sticky="ew", pady=5)

    def pick_rom(self) -> None:
        path = filedialog.askopenfilename(title="选择 ROM 文件")
        if path:
            self.rom_path.set(path)

    def pick_normal_tbl(self) -> None:
        path = filedialog.askopenfilename(title="选择普通码表")
        if path:
            self.normal_tbl_path.set(path)
            self.reload_tables_after_pick()

    def pick_kata_tbl(self) -> None:
        path = filedialog.askopenfilename(title="选择片假名码表")
        if path:
            self.kata_tbl_path.set(path)
            self.reload_tables_after_pick()

    def pick_alias(self) -> None:
        path = filedialog.askopenfilename(title="选择繁简对照表")
        if path:
            self.alias_path.set(path)
            self.reload_tables_after_pick()

    def pick_profile(self) -> None:
        initial_dir = Path(__file__).resolve().parent / "profiles"
        path = filedialog.askopenfilename(
            title="选择修改记录",
            initialdir=str(initial_dir) if initial_dir.exists() else "",
            filetypes=[("TXT", "*.txt"), ("All Files", "*.*")],
        )
        if path:
            self.profile_path.set(path)

    def pick_export(self) -> None:
        path = filedialog.asksaveasfilename(title="导出 TXT", defaultextension=".txt")
        if path:
            self.export_path.set(path)

    def pick_write_path(self) -> None:
        path = filedialog.asksaveasfilename(title="回写 ROM", defaultextension=".sfc")
        if path:
            self.write_path.set(path)

    def ensure_tables_loaded(self) -> None:
        if not self.normal_tbl_path.get().strip() or not self.kata_tbl_path.get().strip():
            raise ValueError("请选择普通码表和片假名码表。")

        self.normal_tbl = load_tbl(self.normal_tbl_path.get().strip())
        self.kata_tbl = load_tbl(self.kata_tbl_path.get().strip())
        self.alias_map = load_alias_map(self.alias_path.get().strip())
        self.normal_reverse = reverse_tbl(self.normal_tbl)
        self.kata_reverse = reverse_tbl(self.kata_tbl)

    def reload_tables_after_pick(self) -> None:
        try:
            if not self.normal_tbl_path.get().strip() or not self.kata_tbl_path.get().strip():
                return
            self.ensure_tables_loaded()
            self.status_var.set("码表已重新加载。")

            if self.current_index is not None and self.entries:
                entry = self.entries[self.current_index]
                self.update_modified_preview(self.edit_box.get("1.0", tk.END).rstrip("\n"), entry)
        except Exception as exc:
            messagebox.showerror("码表加载失败", str(exc))

    def load_resources(self) -> None:
        if not self.rom_path.get().strip():
            raise ValueError("请选择 ROM 文件。")
        self.ensure_tables_loaded()

    def load_entries(self) -> None:
        try:
            self.load_resources()
            start = parse_address(self.start_addr.get())
            count = int(self.count_var.get().strip())
            gap = int(self.gap_len.get().strip())
            if count <= 0:
                raise ValueError("句数必须大于 0。")
            if gap < 0:
                raise ValueError("该字段不能小于 0。")

            self.entries = read_entries(
                rom_path=self.rom_path.get().strip(),
                start_addr=start,
                count=count,
                gap_len=gap,
                normal_tbl=self.normal_tbl,
                kata_tbl=self.kata_tbl,
            )
            self.current_index = None
            self.refresh_tree()
            if self.entries:
                self.suspend_select_event = True
                self.tree.selection_set("0")
                self.tree.focus("0")
                self.suspend_select_event = False
                self.on_select()
            self.status_var.set(f"已读取 {len(self.entries)} 句。")
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))

    def refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for entry in self.entries:
            self.tree.insert(
                "",
                tk.END,
                iid=str(entry.index),
                values=(
                    entry.index,
                    f"0x{entry.start:06X}",
                    f"0x{entry.end:06X}",
                    entry.slot_len,
                    entry.raw_hex,
                    entry.text,
                ),
            )

    def on_select(self, _event=None) -> None:
        if self.suspend_select_event:
            return
        selected = self.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        if self.current_index is not None and self.current_index != index:
            if not self.commit_current_edit():
                self.suspend_select_event = True
                self.tree.selection_set(str(self.current_index))
                self.tree.focus(str(self.current_index))
                self.suspend_select_event = False
                return

        self.current_index = index
        self.populate_editor(self.entries[index])

    def populate_editor(self, entry: SentenceEntry) -> None:
        self.orig_box.configure(state="normal")
        self.orig_box.delete("1.0", tk.END)
        self.orig_box.insert("1.0", entry.original_text)
        self.orig_box.configure(state="disabled")
        self.edit_box.delete("1.0", tk.END)
        self.edit_box.insert("1.0", entry.text)
        self.info_var.set(
            f"序号 {entry.index} | 地址 0x{entry.start:06X}-0x{entry.end:06X} | 槽位 {entry.slot_len} 字节"
        )
        self.orig_bytes_var.set(f"原始字节数: {entry.slot_len} / 槽位 {entry.slot_len}")
        self.orig_hex_var.set(f"原始编码: {entry.raw_hex}")
        self.update_modified_preview(entry.text, entry)

    def commit_current_edit(self) -> bool:
        if self.current_index is None:
            return True
        if not self.entries:
            return True

        entry = self.entries[self.current_index]
        new_text = self.edit_box.get("1.0", tk.END).rstrip("\n")
        encoded, unknown_tokens = analyze_text_encoding(
            new_text,
            self.normal_reverse,
            self.kata_reverse,
            self.alias_map,
        )
        if unknown_tokens:
            messagebox.showerror("编码失败", f"存在未识别文字: {' '.join(unknown_tokens)}")
            return False
        if encoded is None:
            messagebox.showerror("编码失败", "无法生成完整编码。")
            return False
        if len(encoded) > entry.slot_len:
            messagebox.showerror(
                "长度超限",
                f"当前编码长度 {len(encoded)} 字节，超过槽位 {entry.slot_len} 字节。",
            )
            return False

        entry.text = new_text
        self.tree.set(str(entry.index), "text", new_text)
        self.update_modified_preview(new_text, entry)
        return True

    def on_edit_change(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        entry = self.entries[int(selected[0])]
        new_text = self.edit_box.get("1.0", tk.END).rstrip("\n")
        self.update_modified_preview(new_text, entry)

    def update_modified_preview(self, text: str, entry: SentenceEntry) -> None:
        encoded, unknown_tokens = analyze_text_encoding(
            text,
            self.normal_reverse,
            self.kata_reverse,
            self.alias_map,
        )
        self.current_encoded = encoded
        if unknown_tokens:
            self.mod_bytes_var.set(f"修改字节数: 未完成 / 槽位 {entry.slot_len}")
            self.mod_hex_var.set("修改编码: 存在未识别文字，无法生成完整编码")
            self.unknown_var.set(f"未识别文字: {' '.join(unknown_tokens)}")
            self.status_var.set("编码失败: 存在码表未收录文字")
            return

        used = len(encoded) if encoded is not None else 0
        self.mod_bytes_var.set(f"修改字节数: {used} / 槽位 {entry.slot_len}")
        self.mod_hex_var.set(f"修改编码: {format_hex(encoded or b'')}")
        self.unknown_var.set("未识别文字: 无")
        if used > entry.slot_len:
            self.status_var.set(f"超长: 当前 {used} 字节 / 槽位 {entry.slot_len} 字节")
        else:
            self.status_var.set(f"可写回: 当前 {used} 字节 / 槽位 {entry.slot_len} 字节")

    def apply_edit(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("未选择", "请先选择一条句子。")
            return

        if self.commit_current_edit():
            messagebox.showinfo("应用完成", "当前句子的修改已保存。")

    def export_txt(self) -> None:
        try:
            if not self.entries:
                raise ValueError("没有可导出的句子。")
            lines: list[str] = []
            for entry in self.entries:
                lines.append(f"[{entry.index}]")
                lines.append(f"start=0x{entry.start:06X}")
                lines.append(f"end=0x{entry.end:06X}")
                lines.append(f"slot_len={entry.slot_len}")
                lines.append(f"gap_len={entry.gap_len}")
                lines.append(f"raw_hex={entry.raw_hex}")
                lines.append(f"orig_text={entry.original_text}")
                lines.append(f"text={entry.text}")
                lines.append("")
            Path(self.export_path.get().strip()).write_text("\n".join(lines), encoding="utf-8-sig")
            messagebox.showinfo("导出完成", self.export_path.get().strip())
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    def load_translation_txt(self) -> None:
        try:
            if not self.entries:
                raise ValueError("请先读取句子或加载记录，再加载翻译 TXT。")

            path = filedialog.askopenfilename(
                title="选择翻译 TXT",
                filetypes=[("TXT", "*.txt"), ("All Files", "*.*")],
            )
            if not path:
                return

            records = parse_profile_log(path)
            if not records:
                raise ValueError("该翻译文件中没有可用的 text 内容。")

            entry_by_index = {entry.index: entry for entry in self.entries}
            entry_by_start = {entry.start: entry for entry in self.entries}
            loaded = 0
            skipped = 0

            for record in records:
                target_text = record.get("text")
                if target_text is None:
                    skipped += 1
                    continue

                entry = None
                index_text = record.get("index")
                start_text = record.get("start")
                if index_text and index_text.isdigit():
                    entry = entry_by_index.get(int(index_text))
                if entry is None and start_text:
                    entry = entry_by_start.get(parse_address(start_text))
                if entry is None:
                    skipped += 1
                    continue

                encoded, unknown_tokens = analyze_text_encoding(
                    target_text,
                    self.normal_reverse,
                    self.kata_reverse,
                    self.alias_map,
                )
                if unknown_tokens:
                    raise ValueError(
                        f"翻译 TXT 存在未识别文字: 序号 {entry.index} -> {' '.join(unknown_tokens)}"
                    )
                if encoded is None:
                    raise ValueError(f"翻译 TXT 无法编码: 序号 {entry.index}")
                if len(encoded) > entry.slot_len:
                    raise ValueError(
                        f"翻译 TXT 超长: 序号 {entry.index} 当前 {len(encoded)} / 槽位 {entry.slot_len}"
                    )

                entry.text = target_text
                loaded += 1

            self.refresh_tree()
            if self.current_index is not None and str(self.current_index) in self.tree.get_children():
                self.suspend_select_event = True
                self.tree.selection_set(str(self.current_index))
                self.tree.focus(str(self.current_index))
                self.suspend_select_event = False
                self.populate_editor(self.entries[self.current_index])
            self.status_var.set(f"已加载翻译 TXT {loaded} 条，跳过 {skipped} 条。")
            messagebox.showinfo("加载完成", f"已加载翻译 TXT {loaded} 条，跳过 {skipped} 条。")
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))

    def load_profile_log(self) -> None:
        try:
            self.ensure_tables_loaded()

            profile_path = self.profile_path.get().strip()
            if not profile_path:
                self.pick_profile()
                profile_path = self.profile_path.get().strip()
            if not profile_path:
                return

            records = parse_profile_log(profile_path)
            if not records:
                raise ValueError("该记录文件中没有可用的修改内容。")

            self.entries = build_entries_from_records(records, self.normal_tbl, self.kata_tbl)
            if not self.entries:
                raise ValueError("该记录文件无法重建可编辑句子。")

            self.current_index = None
            self.refresh_tree()
            self.suspend_select_event = True
            self.tree.selection_set(str(self.entries[0].index))
            self.tree.focus(str(self.entries[0].index))
            self.suspend_select_event = False
            self.on_select()
            changed_count = sum(1 for entry in self.entries if entry.text != entry.original_text)
            self.status_var.set(f"已加载记录 {len(self.entries)} 条，其中已修改 {changed_count} 条。")
            messagebox.showinfo(
                "加载完成",
                f"已直接从记录载入 {len(self.entries)} 条句子，其中已修改 {changed_count} 条。",
            )
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))

    def write_rom(self) -> None:
        try:
            if not self.entries:
                raise ValueError("没有可回写的句子。")
            if not self.rom_path.get().strip():
                raise ValueError("请选择 ROM 文件。")

            if self.current_index is not None:
                if not self.commit_current_edit():
                    return

            rom_path = self.rom_path.get().strip()
            out_path = self.write_path.get().strip()
            rom = bytearray(Path(rom_path).read_bytes())

            for entry in self.entries:
                encoded = encode_text(entry.text, self.normal_reverse, self.kata_reverse, self.alias_map)
                if len(encoded) > entry.slot_len:
                    raise ValueError(f"序号 {entry.index} 超长，无法回写。")
                padded = encoded + (b"\x00" * (entry.slot_len - len(encoded)))
                rom[entry.start:entry.start + entry.slot_len] = padded

            Path(out_path).write_bytes(rom)
            profile_path = self.save_profile_log()
            message = f"已回写 ROM:\n{out_path}"
            if profile_path:
                message += f"\n\n已保存修改记录:\n{profile_path}"
            messagebox.showinfo("回写完成", message)
        except Exception as exc:
            messagebox.showerror("回写失败", str(exc))

    def save_profile_log(self) -> str | None:
        changed = [entry for entry in self.entries if entry.text != entry.original_text]
        if not changed:
            return None

        script_dir = Path(__file__).resolve().parent
        profiles_dir = script_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)

        start_addr = min(entry.start for entry in changed)
        end_addr = max(entry.end for entry in changed)
        out_path = profiles_dir / f"{start_addr:06X}-{end_addr:06X}.txt"

        lines: list[str] = []
        lines.append(f"修改地址范围: 0x{start_addr:06X}-0x{end_addr:06X}")
        lines.append(f"记录条数: {len(changed)}")
        lines.append("")
        for entry in changed:
            lines.append(f"[{entry.index}]")
            lines.append(f"start=0x{entry.start:06X}")
            lines.append(f"end=0x{entry.end:06X}")
            lines.append(f"raw_hex={entry.raw_hex}")
            lines.append(f"orig_text={entry.original_text}")
            lines.append(f"new_text={entry.text}")
            lines.append("")

        out_path.write_text("\n".join(lines), encoding="utf-8-sig")
        return str(out_path)

def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
