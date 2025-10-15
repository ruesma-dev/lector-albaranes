# interface_adapters/gui/gui_tk.py
from __future__ import annotations
# interface_adapters/gui/gui_tk.py

import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from application.services.batch_runner import run_batch
from config.settings import settings


class TextHandler(logging.Handler):
    """Handler de logging que envía los logs a un Text widget."""
    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg: str) -> None:
        self.text_widget.insert(tk.END, msg)
        self.text_widget.see(tk.END)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Lector de Albaranes (Gemini)")
        self.geometry("900x600")

        # Estado
        self.input_dir = tk.StringVar(value=str(Path("input").resolve()))
        self.output_dir = tk.StringVar(value=str(Path(settings.output_dir).resolve()))

        # UI
        self._build_ui()

        # Logger → Text
        self.logger = logging.getLogger("gui")
        self.logger.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        self.text_handler = TextHandler(self.txt_log)
        self.text_handler.setFormatter(fmt)
        logging.getLogger().addHandler(self.text_handler)      # root
        logging.getLogger("extract").addHandler(self.text_handler)
        logging.getLogger("main").addHandler(self.text_handler)

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 6}

        frm = ttk.Frame(self)
        frm.pack(fill=tk.X, **pad)

        # Input
        ttk.Label(frm, text="Carpeta de entrada:").grid(row=0, column=0, sticky="w")
        self.ent_input = ttk.Entry(frm, textvariable=self.input_dir, width=80)
        self.ent_input.grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Seleccionar…", command=self._choose_input).grid(row=0, column=2, **pad)

        # Output
        ttk.Label(frm, text="Carpeta de salida:").grid(row=1, column=0, sticky="w")
        self.ent_output = ttk.Entry(frm, textvariable=self.output_dir, width=80)
        self.ent_output.grid(row=1, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Seleccionar…", command=self._choose_output).grid(row=1, column=2, **pad)

        # Acción
        self.btn_run = ttk.Button(frm, text="Leer albaranes", command=self._run_clicked)
        self.btn_run.grid(row=2, column=1, sticky="e", **pad)

        frm.columnconfigure(1, weight=1)

        # Log area
        frm_log = ttk.LabelFrame(self, text="Ejecución / Log")
        frm_log.pack(fill=tk.BOTH, expand=True, **pad)

        self.txt_log = tk.Text(frm_log, height=20, wrap="word")
        self.txt_log.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        scroll = ttk.Scrollbar(frm_log, command=self.txt_log.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_log["yscrollcommand"] = scroll.set

    def _choose_input(self) -> None:
        d = filedialog.askdirectory(initialdir=self.input_dir.get(), title="Selecciona carpeta de entrada")
        if d:
            self.input_dir.set(d)

    def _choose_output(self) -> None:
        d = filedialog.askdirectory(initialdir=self.output_dir.get(), title="Selecciona carpeta de salida")
        if d:
            self.output_dir.set(d)

    def _run_clicked(self) -> None:
        try:
            in_dir = Path(self.input_dir.get())
            out_dir = Path(self.output_dir.get())
            if not in_dir.exists():
                messagebox.showerror("Error", f"La carpeta de entrada no existe:\n{in_dir}")
                return
            # actualiza el output en settings dinámicamente (para esta sesión)
            settings.output_dir = str(out_dir)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        self.btn_run.config(state=tk.DISABLED)
        threading.Thread(target=self._run_batch_thread, daemon=True).start()

    def _run_batch_thread(self) -> None:
        try:
            res = run_batch(self.input_dir.get(), print_json=False, logger=logging.getLogger("extract"))
            messagebox.showinfo(
                "Terminado",
                f"Procesados: {res['count']}\n"
                f"Cabeceras: {res['cabecera_batch_path']}\n"
                f"Líneas: {res['lineas_batch_path']}\n"
                f"Excel: {res['excel_batch_path']}"
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.btn_run.config(state=tk.NORMAL)


def run_gui() -> None:
    # Configura logging básico si no lo había
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = App()
    app.mainloop()
