#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "cp936", "big5", "cp932"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def dedup_chars(text: str, sort_mode: str = "unicode"):
    seen = set()
    chars = []
    for ch in text:
        if ch in ("\r", "\n", "\t"):
            continue
        if ch.isspace():
            continue
        if ch not in seen:
            seen.add(ch)
            chars.append(ch)
    if sort_mode == "unicode":
        chars = sorted(chars, key=lambda c: ord(c))
    return chars


def run_dedup(txt_path: Path, out_path: Path, sort_mode: str = "unicode"):
    text = read_text_auto(txt_path)
    chars = dedup_chars(text, sort_mode)
    out_path.write_text("\n".join(chars) + ("\n" if chars else ""), encoding="utf-8")
    return len(chars)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("TXT 去重脚本")
        self.root.geometry("760x220")

        self.txt_var = tk.StringVar()
        self.out_var = tk.StringVar(value="去重文字.txt")
        self.sort_var = tk.StringVar(value="unicode")
        self.status_var = tk.StringVar(value="就绪")

        self._build()

    def _pick_txt(self):
        p = filedialog.askopenfilename(title="选择输入TXT", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if p:
            self.txt_var.set(p)
            d = Path(p).parent
            self.out_var.set(str(d / "去重文字.txt"))

    def _pick_out(self):
        p = filedialog.asksaveasfilename(title="保存去重结果", defaultextension=".txt", filetypes=[("Text", "*.txt")], initialfile="去重文字.txt")
        if p:
            self.out_var.set(p)

    def _run(self):
        src = self.txt_var.get().strip()
        out = self.out_var.get().strip()
        if not src:
            messagebox.showerror("错误", "请选择输入TXT")
            return
        try:
            n = run_dedup(Path(src), Path(out), self.sort_var.get())
            self.status_var.set(f"完成: 去重字符 {n} 个 -> {out}")
            messagebox.showinfo("完成", f"去重字符数: {n}\n输出: {out}")
        except Exception as ex:
            self.status_var.set("失败")
            messagebox.showerror("错误", str(ex))

    def _build(self):
        frm = tk.Frame(self.root)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(frm, text="输入TXT", width=10, anchor="w").grid(row=0, column=0, sticky="w", pady=6)
        tk.Entry(frm, textvariable=self.txt_var).grid(row=0, column=1, sticky="we", pady=6)
        tk.Button(frm, text="选择", command=self._pick_txt, width=10).grid(row=0, column=2, padx=6, pady=6)

        tk.Label(frm, text="输出TXT", width=10, anchor="w").grid(row=1, column=0, sticky="w", pady=6)
        tk.Entry(frm, textvariable=self.out_var).grid(row=1, column=1, sticky="we", pady=6)
        tk.Button(frm, text="保存为", command=self._pick_out, width=10).grid(row=1, column=2, padx=6, pady=6)

        tk.Label(frm, text="排序", width=10, anchor="w").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Combobox(frm, textvariable=self.sort_var, values=["unicode", "none"], state="readonly", width=12).grid(row=2, column=1, sticky="w", pady=6)

        tk.Button(frm, text="开始去重", command=self._run, width=12).grid(row=3, column=1, sticky="w", pady=10)
        tk.Label(frm, textvariable=self.status_var, anchor="w", fg="blue").grid(row=4, column=0, columnspan=3, sticky="we", pady=8)

        frm.grid_columnconfigure(1, weight=1)


def cli_main():
    p = argparse.ArgumentParser(description="提取TXT所用字符（去重）")
    p.add_argument("txt", nargs="?", help="输入TXT文件")
    p.add_argument("--out", default="去重文字.txt", help="输出文件，默认: 去重文字.txt")
    p.add_argument("--sort", choices=["none", "unicode"], default="unicode", help="排序方式")
    p.add_argument("--ui", action="store_true", help="强制使用图形界面")
    args = p.parse_args()

    if args.ui or not args.txt:
        root = tk.Tk()
        App(root)
        root.mainloop()
        return

    src = Path(args.txt)
    out = Path(args.out)
    n = run_dedup(src, out, args.sort)
    print(f"输入: {src}")
    print(f"去重字符数: {n}")
    print(f"输出: {out}")


if __name__ == "__main__":
    cli_main()
