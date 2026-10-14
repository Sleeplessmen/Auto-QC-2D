import tkinter as tk
from tkinter import ttk, messagebox
import os
import sys

# Luu .env canh file exe (khong phu thuoc thu muc dang dung khi mo bang shortcut)
BASE = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))

def load_env(filepath):
    data = {"CVAT_URL": "", "CVAT_TOKEN": "", "CVAT_TASK_ID": "", "CVAT_JOB_ID": ""}
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k in data:
                        data[k] = v
    return data

def save_env(filepath, entries):
    lines = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    new_data = {
        "CVAT_URL": entries['url'].get().strip(),
        "CVAT_TOKEN": entries['token'].get().strip(),
        "CVAT_TASK_ID": entries['task'].get().strip(),
        "CVAT_JOB_ID": entries['job'].get().strip(),
    }
    
    # Update lines
    for i in range(len(lines)):
        line = lines[i].strip()
        if line and not line.startswith("#") and "=" in line:
            k = line.split("=", 1)[0]
            if k in new_data:
                lines[i] = f"{k}={new_data[k]}\n"
                del new_data[k]
    
    # Add remaining
    for k, v in new_data.items():
        lines.append(f"{k}={v}\n")
        
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)

def save_all():
    save_env(os.path.join(BASE, ".env"), tabs_entries[0])
    save_env(os.path.join(BASE, ".env.class"), tabs_entries[1])
    messagebox.showinfo("Thành công", "Đã lưu CẢ 2 CẤU HÌNH thành công!\nKhi mở phần mềm, nó sẽ tự hỏi bạn muốn chạy cái nào.")
    root.destroy()

root = tk.Tk()
root.title("Cài Đặt Thông Tin CVAT (Đa Cấu Hình)")
root.geometry("500x350")
root.resizable(False, False)

tk.Label(root, text="Nhập thông tin cho các hệ thống CVAT:", font=("Arial", 11, "bold")).pack(pady=5)

notebook = ttk.Notebook(root)
notebook.pack(pady=5, padx=10, fill="both", expand=True)

tabs_entries = []
configs = [
    {"name": "Server CVAT (Online)", "file": ".env", "default_url": "https://cvat.note.transformerlabs.ai"},
    {"name": "Localhost (Trên lớp)", "file": ".env.class", "default_url": "http://localhost:8080"}
]

for cfg in configs:
    frame = ttk.Frame(notebook)
    notebook.add(frame, text=cfg["name"])
    
    env_data = load_env(os.path.join(BASE, cfg["file"]))
    
    entries = {}
    tk.Label(frame, text="CVAT URL:").grid(row=0, column=0, sticky="w", pady=10, padx=10)
    entries['url'] = tk.Entry(frame, width=45)
    entries['url'].grid(row=0, column=1, pady=10)
    entries['url'].insert(0, env_data.get("CVAT_URL") or cfg["default_url"])
    
    tk.Label(frame, text="API TOKEN:").grid(row=1, column=0, sticky="w", pady=10, padx=10)
    entries['token'] = tk.Entry(frame, width=45)
    entries['token'].grid(row=1, column=1, pady=10)
    entries['token'].insert(0, env_data.get("CVAT_TOKEN", ""))
    
    tk.Label(frame, text="TASK ID:").grid(row=2, column=0, sticky="w", pady=10, padx=10)
    entries['task'] = tk.Entry(frame, width=45)
    entries['task'].grid(row=2, column=1, pady=10)
    entries['task'].insert(0, env_data.get("CVAT_TASK_ID", ""))
    
    tk.Label(frame, text="JOB ID:").grid(row=3, column=0, sticky="w", pady=10, padx=10)
    entries['job'] = tk.Entry(frame, width=45)
    entries['job'].grid(row=3, column=1, pady=10)
    entries['job'].insert(0, env_data.get("CVAT_JOB_ID", ""))
    
    tabs_entries.append(entries)

tk.Button(root, text="Lưu Lại Tất Cả", bg="#4CAF50", fg="white", font=("Arial", 11, "bold"), command=save_all).pack(pady=10)

root.mainloop()
