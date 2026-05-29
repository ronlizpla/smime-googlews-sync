#!/usr/bin/env python3
"""
S/MIME Google Workspace Sync - Desktop GUI Interface
Provides a modern desktop application wrapper for the sync_smime utility.
Uses CustomTkinter for high-DPI scaling and dark mode aesthetics.
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
    print("Missing dependency: 'customtkinter'. Please run 'pip install -r requirements.txt'")
    sys.exit(1)

# Import backend elements
try:
    import sync_smime
except ImportError:
    # If launched from another context, ensure current dir is in path
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    import sync_smime

# Appearance settings
ctk.set_appearance_mode("Dark")  # System, Light, Dark
ctk.set_default_color_theme("blue")  # Themes: blue, green, dark-blue

class TkinterLoggingHandler(logging.Handler):
    """
    Redirects python logging records to a CustomTkinter Scrollable Text Box.
    Ensures thread-safe updates to the Tkinter main loop.
    """
    def __init__(self, textbox):
        super().__init__()
        self.textbox = textbox

    def emit(self, record):
        msg = self.format(record)
        # Use after() to schedule insertion safely from background threads
        self.textbox.after(0, self.append_text, msg + "\n")

    def append_text(self, text):
        self.textbox.configure(state="normal")
        self.textbox.insert("end", text)
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

class SMIMEGuiApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window settings
        self.title("S/MIME Google Workspace Loader")
        self.geometry("750x650")
        self.minsize(650, 550)

        # Title Label
        self.title_label = ctk.CTkLabel(
            self, 
            text="S/MIME Workspace Cert Sync", 
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.title_label.pack(pady=(20, 10))

        self.subtitle_label = ctk.CTkLabel(
            self, 
            text="Automated 3rd Party S/MIME Upload and Default Configuration Tool", 
            font=ctk.CTkFont(size=12, slant="italic")
        )
        self.subtitle_label.pack(pady=(0, 20))

        # Main Layout Frame
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # Row 1: Credentials File
        self.creds_label = ctk.CTkLabel(self.main_frame, text="Service Account Credentials (JSON):", anchor="w")
        self.creds_label.grid(row=0, column=0, columnspan=2, padx=15, pady=(15, 2), sticky="w")

        self.creds_entry = ctk.CTkEntry(self.main_frame, placeholder_text="C:\\path\\to\\credentials.json", width=480)
        self.creds_entry.grid(row=1, column=0, padx=(15, 10), pady=(0, 15), sticky="ew")

        self.creds_btn = ctk.CTkButton(self.main_frame, text="Browse File", width=120, command=self.browse_creds)
        self.creds_btn.grid(row=1, column=1, padx=(0, 15), pady=(0, 15), sticky="w")

        # Row 2: Certificates Folder
        self.dir_label = ctk.CTkLabel(self.main_frame, text="S/MIME Certificates Folder:", anchor="w")
        self.dir_label.grid(row=2, column=0, columnspan=2, padx=15, pady=(0, 2), sticky="w")

        self.dir_entry = ctk.CTkEntry(self.main_frame, placeholder_text="C:\\path\\to\\certificates", width=480)
        self.dir_entry.grid(row=3, column=0, padx=(15, 10), pady=(0, 15), sticky="ew")

        self.dir_btn = ctk.CTkButton(self.main_frame, text="Browse Folder", width=120, command=self.browse_directory)
        self.dir_btn.grid(row=3, column=1, padx=(0, 15), pady=(0, 15), sticky="w")

        # Row 3: Password
        self.pass_label = ctk.CTkLabel(self.main_frame, text="PKCS#12 File Decryption Password:", anchor="w")
        self.pass_label.grid(row=4, column=0, columnspan=2, padx=15, pady=(0, 2), sticky="w")

        self.pass_entry = ctk.CTkEntry(self.main_frame, placeholder_text="Enter password (leave blank if unencrypted)", show="*", width=480)
        self.pass_entry.grid(row=5, column=0, padx=(15, 10), pady=(0, 15), sticky="ew")
        
        self.show_pass_var = tk.BooleanVar(value=False)
        self.show_pass_cb = ctk.CTkCheckBox(self.main_frame, text="Show Password", variable=self.show_pass_var, command=self.toggle_password_visibility, font=ctk.CTkFont(size=11))
        self.show_pass_cb.grid(row=5, column=1, padx=(0, 15), pady=(0, 15), sticky="w")

        # Row 4: Config Options
        self.options_label = ctk.CTkLabel(self.main_frame, text="Options:", anchor="w")
        self.options_label.grid(row=6, column=0, columnspan=2, padx=15, pady=(0, 2), sticky="w")

        self.default_var = tk.BooleanVar(value=True)
        self.default_cb = ctk.CTkCheckBox(self.main_frame, text="Set uploaded certificates as default", variable=self.default_var)
        self.default_cb.grid(row=7, column=0, columnspan=2, padx=25, pady=(0, 8), sticky="w")

        self.dry_run_var = tk.BooleanVar(value=True)
        self.dry_run_cb = ctk.CTkCheckBox(self.main_frame, text="Dry-run (Local verification only; do not upload to Gmail)", variable=self.dry_run_var)
        self.dry_run_cb.grid(row=8, column=0, columnspan=2, padx=25, pady=(0, 15), sticky="w")

        # Row 5: Action Button
        self.sync_btn = ctk.CTkButton(
            self.main_frame, 
            text="Start S/MIME Sync Process", 
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40,
            command=self.start_sync
        )
        self.sync_btn.grid(row=9, column=0, columnspan=2, padx=15, pady=(5, 15), sticky="ew")

        # Grid Scaling Configuration
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=0)

        # Log frame & text box
        self.log_frame = ctk.CTkFrame(self)
        self.log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.log_title = ctk.CTkLabel(self.log_frame, text="Execution Logs & Output Console:", font=ctk.CTkFont(weight="bold"))
        self.log_title.pack(anchor="w", padx=15, pady=(10, 5))

        self.log_textbox = ctk.CTkTextbox(self.log_frame, height=180, font=("Consolas", 11))
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.log_textbox.configure(state="disabled")

        # Setup Logging redirection
        self.setup_logging()

    def setup_logging(self):
        # Configure logging redirection to the textbox UI widget
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        self.gui_log_handler = TkinterLoggingHandler(self.log_textbox)
        self.gui_log_handler.setFormatter(formatter)
        
        # Attach to the main sync_smime logger
        sync_smime.logger.addHandler(self.gui_log_handler)
        sync_smime.logger.setLevel(logging.INFO)

    def toggle_password_visibility(self):
        if self.show_pass_var.get():
            self.pass_entry.configure(show="")
        else:
            self.pass_entry.configure(show="*")

    def browse_creds(self):
        file_path = filedialog.askopenfilename(
            title="Select Service Account JSON Credentials",
            filetypes=[("JSON Files", "*.json")]
        )
        if file_path:
            self.creds_entry.delete(0, "end")
            self.creds_entry.insert(0, file_path)

    def browse_directory(self):
        dir_path = filedialog.askdirectory(title="Select S/MIME Certificates Folder")
        if dir_path:
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, dir_path)

    def start_sync(self):
        # Retrieve input settings
        creds_path = self.creds_entry.get().strip()
        certs_dir = self.dir_entry.get().strip()
        password = self.pass_entry.get()
        set_default = self.default_var.get()
        dry_run = self.dry_run_var.get()

        # Input validations
        if not certs_dir:
            self.append_log("[ERROR] Please select a certificates folder.\n")
            return
            
        if not dry_run and not creds_path:
            self.append_log("[ERROR] Please select your Google Cloud Service Account credentials JSON file.\n")
            return

        certs_path_obj = Path(certs_dir)
        if not certs_path_obj.exists() or not certs_path_obj.is_dir():
            self.append_log(f"[ERROR] Certificates folder not found: {certs_dir}\n")
            return

        if not dry_run:
            creds_path_obj = Path(creds_path)
            if not creds_path_obj.exists():
                self.append_log(f"[ERROR] Credentials file not found: {creds_path}\n")
                return

        # Disable button during run to avoid dual clicks
        self.sync_btn.configure(state="disabled", text="Running Sync Task...")
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

        # Launch the synchronization worker in a daemon background thread
        threading.Thread(
            target=self.run_sync_worker,
            args=(certs_path_obj, creds_path, password, dry_run, set_default),
            daemon=True
        ).start()

    def run_sync_worker(self, certs_dir, creds_path, password, dry_run, set_default):
        sync_smime.logger.info("==================================================")
        sync_smime.logger.info("Starting S/MIME Google Workspace Sync GUI Worker")
        sync_smime.logger.info(f"Directory: {certs_dir.resolve()}")
        if dry_run:
            sync_smime.logger.info("MODE: DRY-RUN (Local validations only)")
        else:
            sync_smime.logger.info(f"Credentials: {Path(creds_path).resolve()}")
        sync_smime.logger.info("==================================================")

        # Scan for certificate files
        extensions = ("*.p12", "*.pfx")
        cert_files = []
        for ext in extensions:
            cert_files.extend(certs_dir.glob(ext))

        if not cert_files:
            sync_smime.logger.warning(f"No .p12 or .pfx files found in {certs_dir.resolve()}")
            self.finalize_sync(0, 0)
            return

        sync_smime.logger.info(f"Found {len(cert_files)} certificate file(s).")

        results = []
        success_count = 0
        fail_count = 0
        already_count = 0

        for file_path in cert_files:
            result = sync_smime.process_certificate_file(
                file_path=file_path,
                password=password,
                credentials_path=creds_path,
                dry_run=dry_run,
                set_default=set_default
            )
            results.append(result)
            if result["status"] in ("SUCCESS", "DRY-RUN", "ALREADY_EXISTS"):
                success_count += 1
                if result["status"] == "ALREADY_EXISTS":
                    already_count += 1
            else:
                fail_count += 1

        sync_smime.logger.info("==================================================")
        sync_smime.logger.info("Sync Execution Report:")
        sync_smime.logger.info(f"  Total Processed: {len(cert_files)}")
        sync_smime.logger.info(f"  Successful:      {success_count}" + (f" ({already_count} already existed)" if already_count else ""))
        sync_smime.logger.info(f"  Failed:          {fail_count}")
        for r in results:
            icon = "\u2713" if r["status"] in ("SUCCESS", "ALREADY_EXISTS") else ("~" if r["status"] == "DRY-RUN" else "\u2717")
            sync_smime.logger.info(f"  [{icon}] {r['email'] or r['file']:40s}  {r['status']}  {r['reason']}")
        sync_smime.logger.info("==================================================")

        # Write CSV report
        if not dry_run:
            csv_path = sync_smime.write_csv_report(results, certs_dir)
            sync_smime.logger.info(f"  Report saved: {csv_path}")

        self.finalize_sync(success_count, fail_count, already_count, results)

    def finalize_sync(self, success, failed, already=0, results=None):
        def cb():
            self.sync_btn.configure(state="normal", text="Start S/MIME Sync Process")

            # Build per-user summary table
            lines = []
            if results:
                lines.append(f"{'Email':<38} {'Status':<16} Notes")
                lines.append("-" * 80)
                for r in results:
                    icon = "\u2713" if r["status"] in ("SUCCESS", "ALREADY_EXISTS") else ("~" if r["status"] == "DRY-RUN" else "\u2717")
                    email = r["email"] or r["file"]
                    lines.append(f"[{icon}] {email:<36} {r['status']:<16} {r['reason']}")
                lines.append("")

            summary = "\n".join(lines)
            summary += f"Total: {success + failed}  |  ✓ Success: {success}" 
            if already:
                summary += f" ({already} already existed)"
            summary += f"  |  \u2717 Failed: {failed}"
            if not any(r.get("status") == "DRY-RUN" for r in (results or [])):
                summary += "\n\nA CSV report has been saved in the certificates folder."

            messagebox.showinfo("Sync Complete", summary)

        self.sync_btn.after(0, cb)

    def append_log(self, text):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", text)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

def main():
    app = SMIMEGuiApp()
    app.mainloop()

if __name__ == "__main__":
    main()
