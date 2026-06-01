#!/usr/bin/env python3
"""
S/MIME Google Workspace Sync — Desktop GUI
A CustomTkinter wrapper around sync_smime.py.
"""

import os
import sys
import logging
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError:
    print("Missing dependency: 'customtkinter'. Run: pip install -r requirements.txt")
    sys.exit(1)

# Ensure sync_smime is importable from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import sync_smime
except ImportError as e:
    print(f"Cannot import sync_smime: {e}")
    sys.exit(1)

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class TkinterLoggingHandler(logging.Handler):
    """Thread-safe logging handler that appends to a CTkTextbox."""

    def __init__(self, textbox: ctk.CTkTextbox):
        super().__init__()
        self.textbox = textbox

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.textbox.after(0, self._append, msg + "\n")

    def _append(self, text: str) -> None:
        self.textbox.configure(state="normal")
        self.textbox.insert("end", text)
        self.textbox.see("end")
        self.textbox.configure(state="disabled")


class SMIMEGuiApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("S/MIME Google Workspace Loader")
        self.geometry("760x680")
        self.minsize(660, 560)

        # ── Title ──────────────────────────────────────────────────────────────
        ctk.CTkLabel(self, text="S/MIME Workspace Cert Sync",
                     font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(20, 4))
        ctk.CTkLabel(self, text="Automated S/MIME Upload and Default Configuration Tool",
                     font=ctk.CTkFont(size=12, slant="italic")).pack(pady=(0, 16))

        # ── Input frame ────────────────────────────────────────────────────────
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=False, padx=20, pady=4)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=0)

        # Credentials
        ctk.CTkLabel(self.main_frame, text="Service Account Credentials (JSON):",
                     anchor="w").grid(row=0, column=0, columnspan=2, padx=15, pady=(14, 2), sticky="w")
        self.creds_entry = ctk.CTkEntry(self.main_frame,
                                        placeholder_text="C:\\path\\to\\credentials.json", width=480)
        self.creds_entry.grid(row=1, column=0, padx=(15, 8), pady=(0, 12), sticky="ew")
        ctk.CTkButton(self.main_frame, text="Browse File", width=120,
                      command=self._browse_creds).grid(row=1, column=1, padx=(0, 15), pady=(0, 12))

        # Certificates folder
        ctk.CTkLabel(self.main_frame, text="S/MIME Certificates Folder:",
                     anchor="w").grid(row=2, column=0, columnspan=2, padx=15, pady=(0, 2), sticky="w")
        self.dir_entry = ctk.CTkEntry(self.main_frame,
                                      placeholder_text="C:\\path\\to\\certificates", width=480)
        self.dir_entry.grid(row=3, column=0, padx=(15, 8), pady=(0, 12), sticky="ew")
        ctk.CTkButton(self.main_frame, text="Browse Folder", width=120,
                      command=self._browse_directory).grid(row=3, column=1, padx=(0, 15), pady=(0, 12))

        # Password
        ctk.CTkLabel(self.main_frame, text="PKCS#12 Decryption Password:",
                     anchor="w").grid(row=4, column=0, columnspan=2, padx=15, pady=(0, 2), sticky="w")
        self.pass_entry = ctk.CTkEntry(self.main_frame,
                                       placeholder_text="Leave blank if unencrypted",
                                       show="*", width=480)
        self.pass_entry.grid(row=5, column=0, padx=(15, 8), pady=(0, 12), sticky="ew")
        self._show_pass_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.main_frame, text="Show Password",
                        variable=self._show_pass_var,
                        command=self._toggle_password,
                        font=ctk.CTkFont(size=11)).grid(row=5, column=1, padx=(0, 15), pady=(0, 12))

        # Options
        ctk.CTkLabel(self.main_frame, text="Options:", anchor="w").grid(
            row=6, column=0, columnspan=2, padx=15, pady=(0, 2), sticky="w")
        self._default_var = tk.BooleanVar(value=False)   # off by default — intentional
        ctk.CTkCheckBox(self.main_frame, text="Set uploaded certificates as default",
                        variable=self._default_var).grid(
            row=7, column=0, columnspan=2, padx=25, pady=(0, 6), sticky="w")
        self._dry_run_var = tk.BooleanVar(value=True)    # safe default
        ctk.CTkCheckBox(self.main_frame,
                        text="Dry-run (local validation only — no upload to Gmail)",
                        variable=self._dry_run_var).grid(
            row=8, column=0, columnspan=2, padx=25, pady=(0, 12), sticky="w")

        # Start button
        self.sync_btn = ctk.CTkButton(
            self.main_frame,
            text="Start S/MIME Sync Process",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40,
            command=self._start_sync,
        )
        self.sync_btn.grid(row=9, column=0, columnspan=2, padx=15, pady=(4, 14), sticky="ew")

        # ── Log frame ──────────────────────────────────────────────────────────
        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        ctk.CTkLabel(log_frame, text="Execution Log:",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=15, pady=(10, 4))

        self.log_textbox = ctk.CTkTextbox(log_frame, height=200, font=("Consolas", 11))
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 14))
        self.log_textbox.configure(state="disabled")

        self._setup_logging()
        self._worker_thread: threading.Thread | None = None

    # ── Logging ────────────────────────────────────────────────────────────────

    def _setup_logging(self) -> None:
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                      datefmt="%H:%M:%S")
        self._log_handler = TkinterLoggingHandler(self.log_textbox)
        self._log_handler.setFormatter(formatter)
        # Avoid duplicate handlers if somehow called twice
        if self._log_handler not in sync_smime.logger.handlers:
            sync_smime.logger.addHandler(self._log_handler)
        sync_smime.logger.setLevel(logging.INFO)

    def destroy(self) -> None:
        """Remove log handler on close to avoid dangling references."""
        sync_smime.logger.removeHandler(self._log_handler)
        super().destroy()

    # ── UI helpers ─────────────────────────────────────────────────────────────

    def _toggle_password(self) -> None:
        self.pass_entry.configure(show="" if self._show_pass_var.get() else "*")

    def _browse_creds(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Service Account JSON Credentials",
            filetypes=[("JSON Files", "*.json")])
        if path:
            self.creds_entry.delete(0, "end")
            self.creds_entry.insert(0, path)

    def _browse_directory(self) -> None:
        path = filedialog.askdirectory(title="Select S/MIME Certificates Folder")
        if path:
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, path)

    def _log(self, text: str) -> None:
        """Append a message to the log textbox from the main thread."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", text)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    # ── Sync orchestration ─────────────────────────────────────────────────────

    def _start_sync(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showwarning("Busy", "A sync is already running.")
            return

        creds_path = self.creds_entry.get().strip()
        certs_dir_str = self.dir_entry.get().strip()
        password = self.pass_entry.get()
        set_default = self._default_var.get()
        dry_run = self._dry_run_var.get()

        # Input validation
        if not certs_dir_str:
            self._log("[ERROR] Please select a certificates folder.\n")
            return
        if not dry_run and not creds_path:
            self._log("[ERROR] Please select the credentials JSON file.\n")
            return

        certs_path_obj = Path(certs_dir_str)
        if not certs_path_obj.exists() or not certs_path_obj.is_dir():
            self._log(f"[ERROR] Certificates folder not found: {certs_dir_str}\n")
            return

        if not dry_run:
            creds_path_obj = Path(creds_path)
            if not creds_path_obj.exists():
                self._log(f"[ERROR] Credentials file not found: {creds_path}\n")
                return

        # Clear log and disable button
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        self.sync_btn.configure(state="disabled", text="Running Sync…")

        self._worker_thread = threading.Thread(
            target=self._run_worker,
            args=(certs_path_obj, creds_path, password, dry_run, set_default),
            daemon=True,
        )
        self._worker_thread.start()

    def _run_worker(
        self,
        certs_dir: Path,
        creds_path: str,
        password: str,
        dry_run: bool,
        set_default: bool,
    ) -> None:
        try:
            sync_smime.logger.info("=" * 50)
            sync_smime.logger.info("Starting S/MIME Workspace Sync GUI Worker")
            sync_smime.logger.info("Directory   : %s", certs_dir.resolve())
            if dry_run:
                sync_smime.logger.info("MODE        : DRY-RUN (local validation only)")
            else:
                sync_smime.logger.info("Credentials : %s", Path(creds_path).resolve())
            sync_smime.logger.info("=" * 50)

            # Scan for certificate files
            cert_files = []
            for ext in ("*.p12", "*.pfx"):
                cert_files.extend(certs_dir.glob(ext))

            if not cert_files:
                sync_smime.logger.warning("No .p12 or .pfx files found in: %s", certs_dir.resolve())
                self._finalize_sync(0, 0, 0, [])
                return

            sync_smime.logger.info("Found %d certificate file(s).", len(cert_files))

            results = []
            success_count = 0
            fail_count = 0
            already_count = 0

            for file_path in sorted(cert_files):
                result = sync_smime.process_certificate_file(
                    file_path=file_path,
                    password=password,
                    credentials_path=creds_path,
                    dry_run=dry_run,
                    set_default=set_default,
                )
                results.append(result)

                if result["status"] in ("SUCCESS", "DRY-RUN"):
                    success_count += 1
                elif result["status"] == "ALREADY_EXISTS":
                    already_count += 1
                    success_count += 1
                else:
                    fail_count += 1

            sync_smime.logger.info("=" * 50)
            sync_smime.logger.info("Sync Execution Report:")
            sync_smime.logger.info("  Total Processed : %d", len(cert_files))
            already_note = f" ({already_count} already existed)" if already_count else ""
            sync_smime.logger.info("  Successful      : %d%s", success_count, already_note)
            sync_smime.logger.info("  Failed          : %d", fail_count)
            for r in results:
                icon = "+" if r["status"] in ("SUCCESS", "ALREADY_EXISTS") else ("~" if r["status"] == "DRY-RUN" else "x")
                sync_smime.logger.info("  [%s] %-40s %s  %s", icon, r["email"] or r["file"], r["status"], r["reason"])
            sync_smime.logger.info("=" * 50)

            if not dry_run:
                sync_smime.write_csv_report(results, certs_dir)

            self._finalize_sync(success_count, fail_count, already_count, results)

        except Exception as e:
            sync_smime.logger.error("An unexpected error occurred in the worker thread: %s", e)
            self._finalize_sync(0, 0, 0, [])

    def _finalize_sync(self, success: int, failed: int, already: int, results: list) -> None:
        def cb():
            self.sync_btn.configure(state="normal", text="Start S/MIME Sync Process")

            lines = []
            if results:
                lines.append(f"{'Email / File':<38} {'Status':<16} Notes")
                lines.append("-" * 80)
                for r in results:
                    icon = "+" if r["status"] in ("SUCCESS", "ALREADY_EXISTS") else ("~" if r["status"] == "DRY-RUN" else "x")
                    email = r["email"] or r["file"]
                    lines.append(f"[{icon}] {email:<36} {r['status']:<16} {r['reason']}")
                lines.append("")

            summary = "\n".join(lines)
            summary += f"Total: {success + failed}  |  Success: {success}" 
            if already:
                summary += f" ({already} already existed)"
            summary += f"  |  Failed: {failed}"
            
            # Show popup
            messagebox.showinfo("Sync Complete", summary)

        self.sync_btn.after(0, cb)


def main():
    app = SMIMEGuiApp()
    app.mainloop()


if __name__ == "__main__":
    main()
