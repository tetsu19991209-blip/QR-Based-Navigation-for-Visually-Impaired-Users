import os, sys, json, subprocess, tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageOps  # pip install pillow

APP_TITLE = "Mini Project - QR code Indoor Navigation System for VI user"
FOOTER = (
    "CopyRight by UCCC2513 MP students (P9_G3)\n"
    "Chan Yi Hen 2305700\nChong Zhi Cong 2300083\n"
    "Shak Yong Sim 2400233\nYap Ern Ru 2400070"
)

DIR = os.path.dirname(os.path.abspath(__file__))
CUR = os.path.join(DIR, "current_position.json")

# ---------- background image resolver ----------
def resolve_bg():
    """
    Return a background image path:
    1) Preferred path under OneDrive (file or first image file in that folder)
    2) Fallback: background_image.(jpeg|jpg|png) next to this script
    """
    user_path = os.path.join
    (
        DIR,
        "project_images",
        "Homepage_background.jpeg"
    )
    if os.path.exists(user_path):
        if os.path.isfile(user_path):
            return user_path
        if os.path.isdir(user_path):
            exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
            files = [f for f in os.listdir(user_path) if f.lower().endswith(exts)]
            if files:
                files.sort()
                return os.path.join(user_path, files[0])
    for name in ("background_image.jpeg", "background_image.jpg", "background_image.png"):
        p = os.path.join(DIR, name)
        if os.path.exists(p):
            return p
    return os.path.join(DIR, "background_image.jpeg")

BG_PATH = resolve_bg()

def run_py(name):
    """Run a Python script in this folder as a subprocess."""
    path = os.path.join(DIR, name)
    if not os.path.exists(path):
        messagebox.showerror("Missing file", path)
        return
    try:
        subprocess.run([sys.executable, path], cwd=DIR)
    except Exception as e:
        messagebox.showerror("Error running script", f"{name}\n\n{e}")

def scan_then_map():
    """
    Run QR scanner first. After it exits (and writes current_position.json),
    open the routeGuide script. RouteGuide will load the scanned position.
    """
    run_py("qrReader.py")
    run_py("routeGuide.py")

def ui():
    root = tk.Tk()
    root.title(APP_TITLE)
    # Phone-like window size (slightly shorter since one less button)
    root.geometry("480x740")
    root.minsize(360, 600)
    root.maxsize(540, 960)

    # Layout: header, body, footer
    root.grid_rowconfigure(1, weight=1)
    root.grid_columnconfigure(0, weight=1)

    # Styles
    style = ttk.Style()
    try:
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    style.configure("BigBold.TButton", font=("Segoe UI", 16, "bold"), padding=14)

    # ----- Header -----
    header = tk.Frame(root, bg="#111")
    header.grid(row=0, column=0, sticky="nsew")
    tk.Label(
        header, text=APP_TITLE, fg="white", bg="#111",
        font=("Segoe UI", 18, "bold"), pady=12, wraplength=460, justify="center"
    ).pack(fill="x")

    # ----- Body (background image behind content) -----
    body = tk.Frame(root, bg="#000")
    body.grid(row=1, column=0, sticky="nsew")
    body.grid_rowconfigure(1, weight=1)
    body.grid_columnconfigure(0, weight=1)

    # Background image
    bg_label = tk.Label(body, bd=0)
    bg_label.place(relx=0, rely=0, relwidth=1, relheight=1)
    bg_cache = {"img": None, "ph": None}

    def update_body_bg():
        """Resize and dim background image."""
        if not os.path.exists(BG_PATH):
            bg_label.config(image="", text="")
            return
        try:
            if bg_cache["img"] is None:
                bg_cache["img"] = Image.open(BG_PATH).convert("RGB")
        except Exception as e:
            bg_label.config(text=f"BG load error: {e}", image="")
            return

        W = max(body.winfo_width(), 10)
        H = max(body.winfo_height(), 10)
        if W < 10 or H < 10:
            return

        img = bg_cache["img"]
        r_img = ImageOps.fit(img, (W, H), method=Image.LANCZOS)

        overlay = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * 0.70)))
        r_img = r_img.convert("RGBA")
        composed = Image.alpha_composite(r_img, overlay)

        ph = ImageTk.PhotoImage(composed)
        bg_cache["ph"] = ph
        bg_label.config(image=ph)
        bg_label.lower()

    # Buttons (trimmed: removed "QR code detection test")
    btns = tk.Frame(body, bg="", padx=12, pady=10)
    btns.grid(row=0, column=0, sticky="ew")
    for txt, cmd in [
        ("Scan and Read QR code", scan_then_map),   # scan first, then open map
        ("Go to ...", lambda: run_py("routeGuide.py")),
        ("Exit", root.destroy),
    ]:
        ttk.Button(btns, text=txt, style="BigBold.TButton", command=cmd).pack(fill="x", pady=6)

    # Current position panel
    box = tk.LabelFrame(
        body, text="Current Position", padx=10, pady=8,
        font=("Segoe UI", 12, "bold"), bg="#000", fg="white"
    )
    box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 10))

    f = ("Segoe UI", 13)
    lbl_node = tk.Label(box, text="Node: —", font=f, anchor="w", bg="#000", fg="white"); lbl_node.pack(anchor="w", pady=2)
    lbl_xy   = tk.Label(box, text="Coordinate: —", font=f, anchor="w", bg="#000", fg="white"); lbl_xy.pack(anchor="w", pady=2)
    lbl_nb   = tk.Label(box, text="Neighbours: —", font=f, anchor="w", bg="#000", fg="white", wraplength=440, justify="left"); lbl_nb.pack(anchor="w", pady=2)
    lbl_act  = tk.Label(box, text="Action: —", font=f, anchor="w", bg="#000", fg="white"); lbl_act.pack(anchor="w", pady=2)
    lbl_st   = tk.Label(box, text="Waiting for scan...", font=("Segoe UI", 11), fg="#cccccc", bg="#000", anchor="w")
    lbl_st.pack(anchor="w", pady=(6, 0))

    # ----- Footer -----
    footer = tk.Frame(root, bg="#111")
    footer.grid(row=2, column=0, sticky="ew")
    tk.Label(
        footer, text=FOOTER, justify="center", anchor="center",
        font=("Segoe UI", 10), wraplength=460, fg="white", bg="#111"
    ).pack(fill="x", pady=10)

    # Background update on resize
    root.bind("<Configure>", lambda e: update_body_bg())
    root.after(150, update_body_bg)

    # Poll current_position.json
    last = {"t": 0.0}

    def poll():
        try:
            if os.path.exists(CUR):
                m = os.path.getmtime(CUR)
                if m != last["t"]:
                    last["t"] = m
                    with open(CUR, "r", encoding="utf-8") as fp:
                        d = json.load(fp)
                    node = d.get("Node") or "Unknown"
                    coord = d.get("Coordinate") or {}
                    x = coord.get("x", 0)
                    y = coord.get("y", 0)
                    nb = d.get("Neigbours") or []
                    lbl_node.config(text=f"Node: {node}")
                    lbl_xy.config(text=f"Coordinate: {x},{y}")
                    lbl_nb.config(text=f"Neighbours: {', '.join(map(str, nb)) if nb else '-'}")
                    lbl_act.config(text="Action: Current Position")
                    lbl_st.config(text="Updated from scan.")
        except Exception as e:
            lbl_st.config(text=f"Read error: {e}")
        finally:
            root.after(500, poll)  # refresh every 500ms

    root.after(500, poll)
    return root

if __name__ == "__main__":
    ui().mainloop()
