# interface_adapters/gui/gui_tk.py
from __future__ import annotations
# interface_adapters/gui/gui_tk.py

import sys
import logging
import os
import platform
import subprocess
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

from application.services.batch_runner import run_batch
from config.settings import settings


# ------------------------------ Logging → Text -------------------------------

class TextHandler(logging.Handler):
    """Handler de logging que envía los logs a un Text widget (thread-safe vía .after)."""

    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record) + "\n"
            self.text_widget.after(0, self._append, msg)
        except Exception:
            pass

    def _append(self, msg: str) -> None:
        self.text_widget.insert(tk.END, msg)
        self.text_widget.see(tk.END)


# --------------------------------- App GUI -----------------------------------

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Lector de Albaranes (IA)")
        self.minsize(960, 640)

        # Rutas / refs de imágenes
        self._logo_path: Path | None = None     # icono de ventana (opcional)
        self._banner_path: Path | None = None   # imagen del banner (arriba-dcha, distinta del icono)
        self._icon_ref = None                   # evitar GC
        self._banner_logo_img = None            # evitar GC

        # ---------- Icono de ventana ----------
        self._apply_app_icon()

        # ---------- Tema y estilos ----------
        self._setup_theme_styles()

        # ---------- Estado ----------
        self.input_dir = tk.StringVar(value=str(Path("input").resolve()))
        self.output_dir = tk.StringVar(value=str(Path(settings.output_dir).resolve()))
        self._running = False

        # ---------- UI ----------
        self._build_ui()

        # ---------- Logger → Text ----------
        self._wire_logging()

    # ------------------------- Setup: Icon / Styles / Log ---------------------

    def _apply_app_icon(self) -> None:
        """
        Aplica un icono de ventana y guarda su ruta (solo informativa).
        Busca en:
          - ICON_PATH (.env)
          - assets/icons/app.ico|.png
          - assets/app.ico|.png
          - app.ico|.png
        Soporta ejecución frozen (PyInstaller).
        """
        try:
            logger = logging.getLogger("gui")

            bases: list[Path] = [Path.cwd(), Path(__file__).resolve().parent]
            # raíz del proyecto (~3 niveles arriba)
            if len(bases[1].parents) >= 3:
                bases.append(bases[1].parents[2])
            # PyInstaller base
            if getattr(sys, "_MEIPASS", None):
                bases.append(Path(sys._MEIPASS))  # type: ignore[attr-defined]

            candidates: list[Path] = []
            icon_env = os.getenv("ICON_PATH")
            if icon_env:
                candidates.append(Path(icon_env))

            rels = [
                "assets/icons/app.ico",
                "assets/icons/app.png",
                "assets/app.ico",
                "assets/app.png",
                "app.ico",
                "app.png",
            ]
            for b in bases:
                for r in rels:
                    candidates.append((b / r).resolve())

            existing = [p for p in candidates if p.exists()]
            if not existing:
                logger.info("Icono: no encontrado. GUI continúa sin icono.")
                return

            # Selección
            chosen: Path | None = None
            if platform.system() == "Windows":
                ico_first = [p for p in existing if p.suffix.lower() == ".ico"]
                chosen = ico_first[0] if ico_first else (next((p for p in existing if p.suffix.lower() == ".png"), existing[0]))
            else:
                png_first = [p for p in existing if p.suffix.lower() == ".png"]
                chosen = png_first[0] if png_first else existing[0]

            if not chosen:
                return

            # Aplica icono
            if platform.system() == "Windows" and chosen.suffix.lower() == ".ico":
                self.iconbitmap(chosen.as_posix())
                logger.info("Icono aplicado (.ico): %s", chosen)
            else:
                img = tk.PhotoImage(file=chosen.as_posix())
                self.iconphoto(True, img)
                self._icon_ref = img
                logger.info("Icono aplicado (PhotoImage): %s", chosen)

            self._logo_path = chosen

        except Exception as e:
            logging.getLogger("gui").warning("No se pudo aplicar el icono: %s", e)

    def _setup_theme_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Tipografías base
        self._font_default = ("Segoe UI", 10)
        self._font_header = ("Segoe UI Semibold", 18)
        self._font_subheader = ("Segoe UI", 11)
        btn_font = ("Segoe UI Semibold", 10)

        # Colores
        bg = "#f6f7fb"
        panel_bg = "#ffffff"
        accent = "#2c6bed"
        text_muted = "#5a6570"

        # Guardar para reutilizar
        self._bg_color = bg
        self._panel_bg = panel_bg

        self.configure(bg=bg)

        style.configure("Root.TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel_bg)
        style.configure("Header.TLabel", background=bg, foreground="#1f2937", font=self._font_header)
        style.configure("SubHeader.TLabel", background=bg, foreground=text_muted, font=self._font_subheader)
        style.configure("Label.TLabel", background=panel_bg, foreground="#111827", font=self._font_default)
        style.configure("TEntry", padding=4)
        style.configure("Accent.TButton", foreground="#ffffff", background=accent, font=btn_font, padding=6)
        style.map(
            "Accent.TButton",
            background=[("active", "#1f57cc"), ("disabled", "#93a5c9")],
            foreground=[("disabled", "#f1f5f9")],
        )
        style.configure("TButton", padding=6, font=btn_font)
        style.configure("Log.TLabelframe", background=panel_bg, foreground="#111827", padding=6)
        style.configure("Log.TLabelframe.Label", background=panel_bg, foreground="#111827")

    def _wire_logging(self) -> None:
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        self.text_handler = TextHandler(self.txt_log)
        self.text_handler.setFormatter(fmt)
        root.addHandler(self.text_handler)
        logging.getLogger("extract").addHandler(self.text_handler)
        logging.getLogger("main").addHandler(self.text_handler)
        logging.getLogger("gui").addHandler(self.text_handler)

    # -------------------------------- Layout ----------------------------------

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 10}
        pad_small = {"padx": 8, "pady": 6}

        root = ttk.Frame(self, style="Root.TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        # Banner superior (grid 2 columnas: textos a la izq, banner img a la dcha)
        banner = ttk.Frame(root, style="Root.TFrame")
        banner.pack(fill=tk.X, **pad)

        left = ttk.Frame(banner, style="Root.TFrame")
        left.grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Label(left, text="Lector de Albaranes", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text="Extrae cabecera y líneas con IA, y exporta a JSON / Excel",
            style="SubHeader.TLabel",
        ).pack(anchor="w")

        right = ttk.Frame(banner, style="Root.TFrame")
        right.grid(row=0, column=1, sticky="e")

        # Canvas para banner (fondo suave para que destaque aunque la imagen sea blanca/transparente)
        self.cnv_logo = tk.Canvas(
            right,
            width=10,
            height=10,
            highlightthickness=0,
            bd=0,
            bg="#eef2ff",  # cambia a self._bg_color si prefieres el mismo fondo
        )
        self.cnv_logo.pack(anchor="e", padx=6)

        # Renderizar banner ahora
        self._render_banner_image()

        banner.columnconfigure(0, weight=1)

        # Panel de opciones
        panel = ttk.Frame(root, style="Panel.TFrame")
        panel.pack(fill=tk.X, padx=12, pady=(0, 12))

        # INPUT
        row = 0
        ttk.Label(panel, text="Carpeta de entrada:", style="Label.TLabel").grid(
            row=row, column=0, sticky="w", **pad_small
        )
        self.ent_input = ttk.Entry(panel, textvariable=self.input_dir, width=80)
        self.ent_input.grid(row=row, column=1, sticky="we", **pad_small)
        ttk.Button(panel, text="Seleccionar…", command=self._choose_input).grid(row=row, column=2, **pad_small)

        # OUTPUT
        row += 1
        ttk.Label(panel, text="Carpeta de salida:", style="Label.TLabel").grid(
            row=row, column=0, sticky="w", **pad_small
        )
        self.ent_output = ttk.Entry(panel, textvariable=self.output_dir, width=80)
        self.ent_output.grid(row=row, column=1, sticky="we", **pad_small)
        ttk.Button(panel, text="Seleccionar…", command=self._choose_output).grid(row=row, column=2, **pad_small)

        # Acciones
        row += 1
        btns = ttk.Frame(panel, style="Panel.TFrame")
        btns.grid(row=row, column=1, sticky="e", **pad_small)

        self.btn_run = ttk.Button(btns, text="Leer albaranes", style="Accent.TButton", command=self._run_clicked)
        self.btn_run.grid(row=0, column=0, padx=(0, 8))

        self.btn_open_out = ttk.Button(btns, text="Abrir carpeta de salida", command=self._open_output_folder)
        self.btn_open_out.grid(row=0, column=1)

        panel.columnconfigure(1, weight=1)

        # Log area
        frm_log = ttk.Labelframe(root, text="Ejecución / Log", style="Log.TLabelframe")
        frm_log.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self.txt_log = tk.Text(
            frm_log,
            height=18,
            wrap="word",
            background="#ffffff",
            foreground="#0f172a",
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=6, pady=6)

        scroll = ttk.Scrollbar(frm_log, command=self.txt_log.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_log["yscrollcommand"] = scroll.set

        # Tags para estilos de texto en el log
        self.txt_log.tag_configure("success", foreground="#0d9488", font=("Segoe UI Semibold", 16))
        self.txt_log.tag_configure("strong", font=("Segoe UI Semibold", 10))
        self.txt_log.tag_configure("muted", foreground="#64748b")

    # ------------------------------- Actions ----------------------------------

    def _choose_input(self) -> None:
        d = filedialog.askdirectory(initialdir=self.input_dir.get(), title="Selecciona carpeta de entrada")
        if d:
            self.input_dir.set(d)

    def _choose_output(self) -> None:
        d = filedialog.askdirectory(initialdir=self.output_dir.get(), title="Selecciona carpeta de salida")
        if d:
            self.output_dir.set(d)

    def _open_output_folder(self) -> None:
        try:
            out_dir = Path(self.output_dir.get()).resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            if platform.system() == "Windows":
                os.startfile(out_dir.as_posix())  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", out_dir.as_posix()])
            else:
                subprocess.Popen(["xdg-open", out_dir.as_posix()])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta de salida:\n{e}")

    def _run_clicked(self) -> None:
        if self._running:
            return
        # Limpia el log al arrancar un proceso nuevo
        self._clear_log()
        # Marca ejecución en curso
        self._running = True
        self.btn_run.state(["disabled"])

        # Aplica output dir a settings para esta sesión
        try:
            settings.output_dir = str(Path(self.output_dir.get()).resolve())
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self._running = False
            self.btn_run.state(["!disabled"])
            return

        # Lanza en thread
        threading.Thread(target=self._run_batch_thread, daemon=True).start()

    def _run_batch_thread(self) -> None:
        try:
            res = run_batch(self.input_dir.get(), print_json=False, logger=logging.getLogger("extract"))
            # Marca en el log “TERMINADO” grande y verde
            self._append_success_end(res)
            messagebox.showinfo(
                "Terminado",
                f"Procesados: {res['count']}\n"
                f"Cabeceras: {res['cabecera_batch_path']}\n"
                f"Líneas: {res['lineas_batch_path']}\n"
                f"Excel: {res['excel_batch_path']}",
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self._running = False
            self.btn_run.state(["!disabled"])

    # ------------------------------ Helpers -----------------------------------

    def _clear_log(self) -> None:
        self.txt_log.delete("1.0", tk.END)

    def _append_success_end(self, res: dict) -> None:
        self.txt_log.insert(tk.END, "\n")
        self.txt_log.insert(tk.END, "TERMINADO\n", ("success",))
        msg = (
            f"Procesados: {res.get('count', 0)}\n"
            f"Excel lote: {res.get('excel_batch_path', '')}\n"
        )
        self.txt_log.insert(tk.END, msg, ("strong",))
        self.txt_log.see(tk.END)

    # ------------------------------ Banner image ------------------------------

    def _find_banner_image(self) -> Path | None:
        """
        Devuelve la ruta de la imagen de banner si existe.
        Orden de búsqueda:
          1) BANNER_IMAGE_PATH (env/.env)
          2) assets/banner.(png|jpg|jpeg|gif)
          3) assets/ui/banner.*
          4) assets/images/banner.*
          5) assets/icons/banner.*
        Soporta PyInstaller (sys._MEIPASS).
        """
        exts = (".png", ".jpg", ".jpeg", ".gif")
        env_path = os.getenv("BANNER_IMAGE_PATH")
        if env_path:
            p = Path(env_path).expanduser().resolve()
            if p.exists():
                return p

        bases: list[Path] = [Path.cwd(), Path(__file__).resolve().parent]
        if len(bases[1].parents) >= 3:
            bases.append(bases[1].parents[2])  # raíz proyecto aprox
        if getattr(sys, "_MEIPASS", None):
            bases.append(Path(sys._MEIPASS))   # PyInstaller

        rels = [
            "assets/banner",
            "assets/ui/banner",
            "assets/images/banner",
            "assets/icons/banner",
        ]

        for b in bases:
            for r in rels:
                for ext in exts:
                    p = (b / f"{r}{ext}").resolve()
                    if p.exists():
                        return p
        return None

    def _render_banner_image(self) -> None:
        """Pinta el banner (arriba-dcha) en un Canvas, ajustando altura = título+subtítulo."""
        self._banner_path = self._find_banner_image()
        logger = logging.getLogger("gui")
        if not self._banner_path:
            logger.info("Banner: imagen no encontrada (define BANNER_IMAGE_PATH o assets/banner.png).")
            return
        try:
            # Altura objetivo = suma de alturas de fuentes + pequeño padding
            f_header = tkfont.Font(family=self._font_header[0], size=self._font_header[1], weight="bold")
            f_sub = tkfont.Font(family=self._font_subheader[0], size=self._font_subheader[1])
            target_h = f_header.metrics("linespace") + f_sub.metrics("linespace") + 6

            im = Image.open(self._banner_path.as_posix()).convert("RGBA")
            w, h = im.size
            if h <= 0:
                return
            scale = float(target_h) / float(h)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(target_h))

            # (opcional) limitar ancho máximo del banner
            max_w = int(self.winfo_screenwidth() * 0.25)  # 25% pantalla máx
            if new_w > max_w:
                scale2 = max_w / float(new_w)
                new_w = max_w
                new_h = max(1, int(new_h * scale2))

            im = im.resize((new_w, new_h), Image.LANCZOS)

            self._banner_logo_img = ImageTk.PhotoImage(im)

            # Ajusta canvas y dibuja la imagen anclada a la derecha
            self.cnv_logo.configure(width=new_w, height=new_h)
            self.cnv_logo.delete("all")
            self.cnv_logo.create_image(new_w, new_h // 2, image=self._banner_logo_img, anchor="e")

            logger.info(
                "Banner: %s → %s (%dx%d → %dx%d)",
                self._banner_path.resolve(),
                self._banner_path.name,
                w,
                h,
                new_w,
                new_h,
            )
        except Exception as e:
            logger.warning("Banner: no se pudo renderizar %s: %s", self._banner_path, e)


def run_gui() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = App()
    app.mainloop()
