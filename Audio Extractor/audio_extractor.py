"""
Audio Extractor — standalone app.

Turns WAV/audio files (or the audio track of a video) into a 16x16 black
HAP .mov with 48 kHz stereo PCM audio, at a selectable frame rate.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import extractor
from extractor import FRAME_RATES, SUPPORTED_EXTS

# Drag-and-drop is optional: works if tkinterdnd2 is installed.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND = True
except Exception:  # pragma: no cover
    _DND = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_NAME = "Audio Extractor"
_Base = (ctk.CTk, TkinterDnD.DnDWrapper) if _DND else (ctk.CTk,)


class App(*_Base):
    def __init__(self):
        super().__init__()
        if _DND:
            self.TkdndVersion = TkinterDnD._require(self)

        self.title(APP_NAME)
        self.geometry("760x620")
        self.minsize(620, 520)

        self.files: list[str] = []
        self.out_dir: str | None = None
        self.last_output: str | None = None
        self.msgs: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()

        self._build()
        self.after(100, self._check_ffmpeg)
        self.after(100, self._poll)

    # ---------------------------------------------------------------- UI
    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        ctk.CTkLabel(head, text=APP_NAME, font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        self.ff_label = ctk.CTkLabel(head, text="checking ffmpeg…", text_color="gray60",
                                     font=ctk.CTkFont(size=11))
        self.ff_label.pack(side="right")

        # File list
        listf = ctk.CTkFrame(self)
        listf.grid(row=1, column=0, sticky="nsew", padx=16, pady=6)
        listf.grid_columnconfigure(0, weight=1)
        listf.grid_rowconfigure(1, weight=1)

        hint = "Drop audio or video files here, or use Add Files" if _DND else "Add audio or video files"
        self.list_title = ctk.CTkLabel(listf, text=hint, anchor="w", text_color="gray70")
        self.list_title.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 4))

        self.listbox = tk.Listbox(listf, selectmode="extended", activestyle="none",
                                  bg="#1d1e1e", fg="#dce4ee", selectbackground="#1f6aa5",
                                  highlightthickness=0, borderwidth=0, font=("Menlo", 12)
                                  if sys.platform == "darwin" else ("Consolas", 10))
        self.listbox.grid(row=1, column=0, sticky="nsew", padx=(10, 0), pady=(0, 8))
        sb = ctk.CTkScrollbar(listf, command=self.listbox.yview)
        sb.grid(row=1, column=1, sticky="ns", padx=(0, 6), pady=(0, 8))
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.bind("<Delete>", lambda e: self._remove_selected())
        self.listbox.bind("<BackSpace>", lambda e: self._remove_selected())
        if _DND:
            for w in (self.listbox, listf):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

        btns = ctk.CTkFrame(listf, fg_color="transparent")
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkButton(btns, text="Add Files…", width=110, command=self._add_files).pack(side="left")
        ctk.CTkButton(btns, text="Add Folder…", width=110, command=self._add_folder).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Remove", width=90, fg_color="gray30", hover_color="gray40",
                      command=self._remove_selected).pack(side="left")
        ctk.CTkButton(btns, text="Clear", width=80, fg_color="gray30", hover_color="gray40",
                      command=self._clear).pack(side="left", padx=6)

        # Settings
        sett = ctk.CTkFrame(self)
        sett.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
        sett.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(sett, text="Frame rate").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.fps_var = ctk.StringVar(value=FRAME_RATES[0].label)
        ctk.CTkOptionMenu(sett, variable=self.fps_var, width=160,
                          values=[f.label for f in FRAME_RATES]).grid(
            row=0, column=1, sticky="w", padx=10, pady=(10, 4))
        ctk.CTkLabel(sett, text="Match source uses the video's rate; audio-only falls back to 30.",
                     text_color="gray60", font=ctk.CTkFont(size=11)).grid(
            row=0, column=2, sticky="w", padx=(0, 10), pady=(10, 4))

        ctk.CTkLabel(sett, text="Output").grid(row=1, column=0, sticky="w", padx=10, pady=(4, 10))
        self.out_label = ctk.CTkLabel(sett, text="Same folder as each source", anchor="w",
                                      text_color="gray80")
        self.out_label.grid(row=1, column=1, columnspan=1, sticky="ew", padx=10, pady=(4, 10))
        ob = ctk.CTkFrame(sett, fg_color="transparent")
        ob.grid(row=1, column=2, sticky="e", padx=10, pady=(4, 10))
        ctk.CTkButton(ob, text="Choose…", width=90, command=self._choose_out).pack(side="left")
        ctk.CTkButton(ob, text="Reset", width=70, fg_color="gray30", hover_color="gray40",
                      command=self._reset_out).pack(side="left", padx=(6, 0))

        # Run + progress
        run = ctk.CTkFrame(self, fg_color="transparent")
        run.grid(row=3, column=0, sticky="ew", padx=16, pady=6)
        run.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(run)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.reveal_btn = ctk.CTkButton(run, text="Show Output", width=110, state="disabled",
                                        fg_color="gray30", hover_color="gray40", command=self._reveal)
        self.reveal_btn.grid(row=0, column=1, padx=(0, 6))
        self.run_btn = ctk.CTkButton(run, text="Extract", width=120, height=34,
                                     font=ctk.CTkFont(weight="bold"), command=self._start)
        self.run_btn.grid(row=0, column=2)

        self.log = ctk.CTkTextbox(self, height=120, font=ctk.CTkFont(family="Menlo", size=11))
        self.log.grid(row=4, column=0, sticky="ew", padx=16, pady=(6, 14))
        self.log.configure(state="disabled")

    # ---------------------------------------------------------- file list
    def _add_paths(self, paths):
        added = 0
        for p in paths:
            p = os.path.abspath(p)
            if os.path.isdir(p):
                for root, dirs, names in os.walk(p):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    self._add_paths(os.path.join(root, n) for n in sorted(names)
                                    if not n.startswith("."))
                continue
            if Path(p).suffix.lower() not in SUPPORTED_EXTS:
                continue
            if "_hapaudio" in Path(p).stem or p in self.files:
                continue
            self.files.append(p)
            self.listbox.insert("end", p)
            added += 1
        self._update_title()
        return added

    def _update_title(self):
        n = len(self.files)
        if n:
            self.list_title.configure(text=f"{n} file{'s' if n != 1 else ''} queued")
        else:
            self.list_title.configure(text="Drop audio or video files here, or use Add Files"
                                      if _DND else "Add audio or video files")

    def _on_drop(self, event):
        self._add_paths(self.tk.splitlist(event.data))

    def _add_files(self):
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS))
        paths = filedialog.askopenfilenames(
            title="Choose audio or video files",
            filetypes=[("Audio / Video", exts), ("All files", "*.*")])
        if paths:
            self._add_paths(paths)

    def _add_folder(self):
        d = filedialog.askdirectory(title="Add all audio/video in folder")
        if d:
            self._add_paths([d])

    def _remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)
            del self.files[i]
        self._update_title()

    def _clear(self):
        if self._busy():
            return
        self.listbox.delete(0, "end")
        self.files.clear()
        self._update_title()

    def _choose_out(self):
        d = filedialog.askdirectory(title="Output folder")
        if d:
            self.out_dir = d
            self.out_label.configure(text=d)

    def _reset_out(self):
        self.out_dir = None
        self.out_label.configure(text="Same folder as each source")

    # ------------------------------------------------------------- run
    def _busy(self):
        return self.worker is not None and self.worker.is_alive()

    def _check_ffmpeg(self):
        try:
            self.ff_label.configure(text=extractor.check_ffmpeg(), text_color="gray60")
        except Exception as e:
            self.ff_label.configure(text="ffmpeg not ready", text_color="#e05252")
            self.run_btn.configure(state="disabled")
            self._log(f"⚠ {e}")

    def _start(self):
        if self._busy():
            self.cancel.set()
            self.run_btn.configure(text="Stopping…", state="disabled")
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Add some files first.")
            return
        fr = next(f for f in FRAME_RATES if f.label == self.fps_var.get())
        jobs = list(self.files)
        self.cancel.clear()
        self.progress.set(0)
        self.run_btn.configure(text="Stop")
        self._log(f"— {len(jobs)} file(s) @ {fr.label} —")
        self.worker = threading.Thread(target=self._work, args=(jobs, fr, self.out_dir), daemon=True)
        self.worker.start()

    def _work(self, jobs, fr, out_dir):
        ok = fail = 0
        for i, src in enumerate(jobs, 1):
            if self.cancel.is_set():
                self.msgs.put(("log", "Stopped."))
                break
            self.msgs.put(("log", f"[{i}/{len(jobs)}] {Path(src).name}"))
            try:
                out = extractor.extract_audio(src, fr, out_dir)
                ok += 1
                self.msgs.put(("done", src, out))
            except Exception as e:
                fail += 1
                self.msgs.put(("log", f"   ✗ {e}"))
            self.msgs.put(("progress", i / len(jobs)))
        self.msgs.put(("finished", ok, fail))

    def _poll(self):
        try:
            while True:
                m = self.msgs.get_nowait()
                kind = m[0]
                if kind == "log":
                    self._log(m[1])
                elif kind == "progress":
                    self.progress.set(m[1])
                elif kind == "done":
                    _, src, out = m
                    self._log(f"   ✓ {Path(out).name}")
                    self.last_output = out
                    self.reveal_btn.configure(state="normal")
                    if src in self.files:  # drop finished items from the queue
                        idx = self.files.index(src)
                        self.files.pop(idx)
                        self.listbox.delete(idx)
                        self._update_title()
                elif kind == "finished":
                    _, ok, fail = m
                    self._log(f"Done: {ok} succeeded" + (f", {fail} failed" if fail else "") + ".")
                    self.run_btn.configure(text="Extract", state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _reveal(self):
        p = self.last_output
        if not p or not os.path.exists(p):
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", p])
        elif os.name == "nt":
            subprocess.run(["explorer", "/select,", os.path.normpath(p)])
        else:
            subprocess.run(["xdg-open", os.path.dirname(p)])


def main():
    app = App()
    # Files passed on the command line (or dropped onto the app icon on Windows)
    if len(sys.argv) > 1:
        app._add_paths(sys.argv[1:])
    app.mainloop()


if __name__ == "__main__":
    main()
