#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox
import unicodedata

TABLE_RE = re.compile(r"^\s*([0-9A-Fa-f]{2,6})=(.*)\s*$")
ALIAS_RE = re.compile(r"^\s*(.+?)\s*=\s*(.+)\s*$")


def read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "cp936", "big5", "cp932"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def load_table_chars(path: Path):
    text = read_text_auto(path)
    chars = set()
    for ln in text.splitlines():
        m = TABLE_RE.match(ln)
        if not m:
            continue
        rhs = m.group(2)
        if rhs:
            chars.add(rhs)
    return chars


def load_dedup_chars(path: Path):
    text = read_text_auto(path)
    out = []
    seen = set()
    for ln in text.splitlines():
        ch = ln.strip()
        if not ch:
            continue
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


def load_alias_map(path: Path):
    alias = {}
    if not path or not path.exists():
        return alias
    text = read_text_auto(path)
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = ALIAS_RE.match(s)
        if not m:
            continue
        k = m.group(1).strip()
        vals = [x.strip() for x in m.group(2).replace("，", ",").split(",") if x.strip()]
        if not k or not vals:
            continue
        alias.setdefault(k, set()).update(vals)
        for v in vals:
            alias.setdefault(v, set()).add(k)
    return {k: sorted(v) for k, v in alias.items()}


def eq_candidates(ch: str, alias_map: dict):
    c = [ch]
    nfk = unicodedata.normalize("NFKC", ch)
    if nfk not in c:
        c.append(nfk)
    for x in alias_map.get(ch, []):
        if x not in c:
            c.append(x)
    for x in alias_map.get(nfk, []):
        if x not in c:
            c.append(x)
    return c


def compare_and_write(dedup_txt: Path, table_paths, out_path: Path, alias_path: Path | None = None):
    src_chars = load_dedup_chars(dedup_txt)
    table_chars = set()
    for t in table_paths:
        table_chars |= load_table_chars(Path(t))
    alias_map = load_alias_map(alias_path) if alias_path else {}

    missing = []
    for c in src_chars:
        if c in table_chars:
            continue
        cands = eq_candidates(c, alias_map)
        if any(x in table_chars for x in cands):
            continue
        missing.append(c)
    out_path.write_text("\n".join(missing) + ("\n" if missing else ""), encoding="utf-8")
    return len(src_chars), len(missing)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("汉化比对工具")
        self.root.geometry("820x420")

        self.dedup_var = tk.StringVar()
        self.out_var = tk.StringVar(value="追加文字.txt")
        self.alias_var = tk.StringVar(value=r"E:\sfc\Roms\字库\别名字典_auto.txt")
        self.status_var = tk.StringVar(value="就绪")
        self.table_paths = []

        self._build()

    def _pick_dedup(self):
        p = filedialog.askopenfilename(title="选择去重文字TXT", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if p:
            self.dedup_var.set(p)
            d = Path(p).parent
            self.out_var.set(str(d / "追加文字.txt"))

    def _add_tables(self):
        ps = filedialog.askopenfilenames(title="选择一个或多个码表", filetypes=[("Text", "*.txt *.tbl"), ("All", "*.*")])
        for p in ps:
            if p not in self.table_paths:
                self.table_paths.append(p)
                self.tbl_list.insert("end", p)

    def _remove_selected(self):
        sel = list(self.tbl_list.curselection())
        if not sel:
            return
        for idx in reversed(sel):
            p = self.tbl_list.get(idx)
            self.tbl_list.delete(idx)
            self.table_paths = [x for x in self.table_paths if x != p]

    def _clear_tables(self):
        self.table_paths = []
        self.tbl_list.delete(0, "end")

    def _pick_out(self):
        p = filedialog.asksaveasfilename(title="保存追加文字", defaultextension=".txt", filetypes=[("Text", "*.txt")], initialfile="追加文字.txt")
        if p:
            self.out_var.set(p)

    def _pick_alias(self):
        p = filedialog.askopenfilename(title="选择别名字典(可选)", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if p:
            self.alias_var.set(p)

    def _run(self):
        dedup = self.dedup_var.get().strip()
        out = self.out_var.get().strip()
        if not dedup:
            messagebox.showerror("错误", "请选择去重文字TXT")
            return
        if not self.table_paths:
            messagebox.showerror("错误", "请至少添加一个码表")
            return
        try:
            ap = self.alias_var.get().strip()
            total, missing = compare_and_write(Path(dedup), self.table_paths, Path(out), Path(ap) if ap else None)
            self.status_var.set(f"完成: 输入 {total} 字，需追加 {missing} 字 -> {out}")
            messagebox.showinfo("完成", f"输入字符数: {total}\n需追加字符数: {missing}\n输出: {out}")
        except Exception as ex:
            self.status_var.set("失败")
            messagebox.showerror("错误", str(ex))

    def _build(self):
        frm = tk.Frame(self.root)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(frm, text="去重TXT", width=10, anchor="w").grid(row=0, column=0, sticky="w", pady=6)
        tk.Entry(frm, textvariable=self.dedup_var).grid(row=0, column=1, sticky="we", pady=6)
        tk.Button(frm, text="选择", command=self._pick_dedup, width=10).grid(row=0, column=2, padx=6, pady=6)

        tk.Label(frm, text="码表列表", width=10, anchor="nw").grid(row=1, column=0, sticky="nw", pady=6)
        self.tbl_list = tk.Listbox(frm, height=10)
        self.tbl_list.grid(row=1, column=1, sticky="nsew", pady=6)

        btn_col = tk.Frame(frm)
        btn_col.grid(row=1, column=2, sticky="n", padx=6, pady=6)
        tk.Button(btn_col, text="添加码表", command=self._add_tables, width=10).pack(pady=2)
        tk.Button(btn_col, text="移除选中", command=self._remove_selected, width=10).pack(pady=2)
        tk.Button(btn_col, text="清空", command=self._clear_tables, width=10).pack(pady=2)

        tk.Label(frm, text="输出TXT", width=10, anchor="w").grid(row=2, column=0, sticky="w", pady=6)
        tk.Entry(frm, textvariable=self.out_var).grid(row=2, column=1, sticky="we", pady=6)
        tk.Button(frm, text="保存为", command=self._pick_out, width=10).grid(row=2, column=2, padx=6, pady=6)

        tk.Label(frm, text="别名字典", width=10, anchor="w").grid(row=3, column=0, sticky="w", pady=6)
        tk.Entry(frm, textvariable=self.alias_var).grid(row=3, column=1, sticky="we", pady=6)
        tk.Button(frm, text="选择", command=self._pick_alias, width=10).grid(row=3, column=2, padx=6, pady=6)

        tk.Button(frm, text="开始比对", command=self._run, width=12).grid(row=4, column=1, sticky="w", pady=10)
        tk.Label(frm, textvariable=self.status_var, anchor="w", fg="blue").grid(row=5, column=0, columnspan=3, sticky="we", pady=8)

        frm.grid_columnconfigure(1, weight=1)
        frm.grid_rowconfigure(1, weight=1)


def cli_main():
    p = argparse.ArgumentParser(description="对比去重文字与码表，输出需追加字符")
    p.add_argument("dedup_txt", nargs="?", help="去重TXT（每行1字符）")
    p.add_argument("tables", nargs="*", help="一个或多个码表")
    p.add_argument("--out", default="追加文字.txt", help="输出文件")
    p.add_argument("--alias", default=r"E:\sfc\Roms\字库\别名字典_auto.txt", help="别名字典(可选)")
    p.add_argument("--ui", action="store_true", help="强制使用图形界面")
    args = p.parse_args()

    if args.ui or not args.dedup_txt:
        root = tk.Tk()
        App(root)
        root.mainloop()
        return

    if not args.tables:
        raise SystemExit("命令行模式下至少提供一个码表")

    alias_path = Path(args.alias) if args.alias else None
    if alias_path and not alias_path.exists():
        alias_path = None
    total, missing = compare_and_write(Path(args.dedup_txt), args.tables, Path(args.out), alias_path)
    print(f"去重输入字符数: {total}")
    print(f"需追加字符数: {missing}")
    print(f"输出: {args.out}")


if __name__ == "__main__":
    cli_main()
