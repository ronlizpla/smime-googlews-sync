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
        self.geometry("760x780")
        self.minsize(660, 680)

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

        # Per-certificate password CSV (optional override)
        ctk.CTkLabel(self.main_frame, text="Per-Certificate Password CSV (optional):",
                     anchor="w").grid(row=6, column=0, columnspan=2, padx=15, pady=(0, 2), sticky="w")
        self.pwcsv_entry = ctk.CTkEntry(
            self.main_frame,
            placeholder_text="Overrides passwords.csv; columns: file/email, password",
            width=480)
        self.pwcsv_entry.grid(row=7, column=0, padx=(15, 8), pady=(0, 12), sticky="ew")
        ctk.CTkButton(self.main_frame, text="Browse CSV", width=120,
                      command=self._browse_password_csv).grid(row=7, column=1, padx=(0, 15), pady=(0, 12))

        # Options
        ctk.CTkLabel(self.main_frame, text="Options:", anchor="w").grid(
            row=8, column=0, columnspan=2, padx=15, pady=(0, 2), sticky="w")
        self._default_var = tk.BooleanVar(value=False)   # off by default — intentional
        ctk.CTkCheckBox(self.main_frame, text="Set uploaded certificates as default",
                        variable=self._default_var).grid(
            row=9, column=0, columnspan=2, padx=25, pady=(0, 6), sticky="w")
        self._dry_run_var = tk.BooleanVar(value=True)    # safe default
        ctk.CTkCheckBox(self.main_frame,
                        text="Dry-run (local validation only — no upload to Gmail)",
                        variable=self._dry_run_var).grid(
            row=10, column=0, columnspan=2, padx=25, pady=(0, 12), sticky="w")

        # Setup GCP button
        self.setup_btn = ctk.CTkButton(
            self.main_frame,
            text="Setup GCP Project & Permissions",
            font=ctk.CTkFont(size=13),
            height=36,
            fg_color="#2b6cb0",
            hover_color="#2c5282",
            command=self._open_setup_dialog,
        )
        self.setup_btn.grid(row=11, column=0, columnspan=2, padx=15, pady=(0, 6), sticky="ew")

        # Start button
        self.sync_btn = ctk.CTkButton(
            self.main_frame,
            text="Start S/MIME Sync Process",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40,
            command=self._start_sync,
        )
        self.sync_btn.grid(row=12, column=0, columnspan=2, padx=15, pady=(4, 14), sticky="ew")

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

    def _browse_password_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Per-Certificate Password CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if path:
            self.pwcsv_entry.delete(0, "end")
            self.pwcsv_entry.insert(0, path)

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
        password_csv_str = self.pwcsv_entry.get().strip()
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

        password_csv_obj = Path(password_csv_str) if password_csv_str else None
        if password_csv_obj and not password_csv_obj.exists():
            self._log(f"[ERROR] Password CSV not found: {password_csv_str}\n")
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
            args=(certs_path_obj, creds_path, password, dry_run, set_default, password_csv_obj),
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
        password_csv: Path | None = None,
    ) -> None:
        try:
            summary = sync_smime.run_sync(
                certs_dir=certs_dir,
                credentials_path=creds_path or None,
                password=password,
                dry_run=dry_run,
                set_default=set_default,
                password_csv=password_csv,
            )
            self._finalize_sync(
                summary["success"], summary["failed"], summary["already"], summary["results"]
            )
        except Exception as e:
            sync_smime.logger.error("Sync aborted: %s", e)
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

    # ── GCP project & permissions setup ──────────────────────────────────────────

    def _open_setup_dialog(self) -> None:
        """Collects GCP parameters then runs the parameterized setup_gcp.ps1."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Setup GCP Project & Permissions")
        dialog.geometry("560x430")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Provision Google Cloud Service Account",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(15, 2))
        ctk.CTkLabel(
            dialog,
            text="Creates the service account + key used to upload S/MIME certs.\n"
                 "Requires the gcloud CLI installed and 'gcloud auth login' completed.",
            font=ctk.CTkFont(size=11), justify="center").pack(pady=(0, 12))

        frm = ctk.CTkFrame(dialog)
        frm.pack(fill="x", padx=20)
        frm.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frm, text="GCP Project ID:", anchor="w").grid(
            row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        proj_entry = ctk.CTkEntry(frm, placeholder_text="e.g. acme-smime-12345", width=320)
        proj_entry.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")

        ctk.CTkLabel(frm, text="Service Account Name:", anchor="w").grid(
            row=2, column=0, padx=12, pady=(0, 2), sticky="w")
        sa_entry = ctk.CTkEntry(frm, width=320)
        sa_entry.insert(0, "smime-sync-bot")
        sa_entry.grid(row=3, column=0, padx=12, pady=(0, 10), sticky="ew")

        ctk.CTkLabel(frm, text="Output Key File:", anchor="w").grid(
            row=4, column=0, padx=12, pady=(0, 2), sticky="w")
        key_entry = ctk.CTkEntry(frm, width=320)
        key_entry.insert(0, "credentials.json")
        key_entry.grid(row=5, column=0, padx=12, pady=(0, 10), sticky="ew")

        create_proj_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(frm, text="Create a new GCP project (otherwise use existing)",
                        variable=create_proj_var).grid(
            row=6, column=0, padx=12, pady=(0, 12), sticky="w")

        def on_run():
            project_id = proj_entry.get().strip()
            sa_name = sa_entry.get().strip() or "smime-sync-bot"
            out_key = key_entry.get().strip() or "credentials.json"
            create_proj = create_proj_var.get()
            if not project_id:
                messagebox.showerror("Missing Input", "GCP Project ID is required.", parent=dialog)
                return
            dialog.destroy()
            self.setup_btn.configure(state="disabled", text="Running GCP Setup…")
            self.log_textbox.configure(state="normal")
            self.log_textbox.delete("1.0", "end")
            self.log_textbox.configure(state="disabled")
            threading.Thread(
                target=self._run_setup_worker,
                args=(project_id, sa_name, out_key, create_proj),
                daemon=True,
            ).start()

        ctk.CTkButton(dialog, text="Run Setup", height=38, command=on_run).pack(
            pady=15, padx=20, fill="x")

    def _run_setup_worker(self, project_id: str, sa_name: str, out_key: str,
                          create_proj: bool) -> None:
        """Runs setup_gcp.ps1 and streams output to the log console."""
        import subprocess
        import shutil

        script_path = Path(__file__).resolve().parent / "setup_gcp.ps1"
        sync_smime.logger.info("=" * 50)
        sync_smime.logger.info("Running GCP Project & Permissions Setup")
        sync_smime.logger.info("  Project ID      : %s", project_id)
        sync_smime.logger.info("  Service Account : %s", sa_name)
        sync_smime.logger.info("  Output Key      : %s", out_key)
        sync_smime.logger.info("  Create Project  : %s", create_proj)
        sync_smime.logger.info("=" * 50)

        if not script_path.exists():
            sync_smime.logger.error("Setup script not found: %s", script_path)
            self._finalize_setup(False, out_key)
            return

        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            sync_smime.logger.error("Could not find 'pwsh' or 'powershell' on PATH.")
            self._finalize_setup(False, out_key)
            return

        cmd = [
            powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script_path),
            "-ProjectId", project_id,
            "-ServiceAccountName", sa_name,
            "-KeyOutputPath", out_key,
        ]
        if create_proj:
            cmd.append("-CreateProject")

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=str(script_path.parent))
            for line in proc.stdout:
                sync_smime.logger.info(line.rstrip())
            proc.wait()
            success = proc.returncode == 0
        except Exception as e:
            sync_smime.logger.error("Setup execution failed: %s", e)
            success = False

        self._finalize_setup(success, out_key)

    def _finalize_setup(self, success: bool, out_key: str) -> None:
        def cb():
            self.setup_btn.configure(state="normal", text="Setup GCP Project & Permissions")
            if success:
                key_path = Path(out_key)
                if not key_path.is_absolute():
                    key_path = Path(__file__).resolve().parent / out_key
                if key_path.exists():
                    self.creds_entry.delete(0, "end")
                    self.creds_entry.insert(0, str(key_path))
                messagebox.showinfo(
                    "Setup Complete",
                    "GCP setup finished successfully.\n\n"
                    "The credentials path has been filled in for you.\n\n"
                    "Don't forget the one-time Domain-Wide Delegation step shown in the "
                    "log (authorize the Client ID + scopes in the Google Admin Console).")
            else:
                messagebox.showerror(
                    "Setup Failed",
                    "GCP setup did not complete successfully. Review the log for details.")

        self.setup_btn.after(0, cb)


def main():
    app = SMIMEGuiApp()
    app.mainloop()


if __name__ == "__main__":
    main()
