import os, sys, json, math, heapq, re, threading, queue, time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk, ImageDraw

# ---------- Config paths ----------
GROUND_PATH = r"C:\Users\User\OneDrive\Desktop\MP code\map\ground_floor.png"
FIRST_PATH  = r"C:\Users\User\OneDrive\Desktop\MP code\map\first_floor.png"
JSON_NAME   = "nodes_map.json"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CURPOS_FILE = os.path.join(SCRIPT_DIR, "current_position.json")  # written by qrReader.py

# ---------- Draw constants ----------
COLOR_BG_EDGE = "#8c8c8c"
COLOR_NODE    = "#303030"
COLOR_ROUTE   = "#1976d2"
COLOR_CURR    = "#ffcc00"
COLOR_DEST    = "#ff4081"
COLOR_LABEL   = "#ffffff"
NODE_RADIUS   = 6
RING_R        = 14

# Keep a stable default zoom/pan; no auto-recenter
DEFAULT_ZOOM = 1.0

# ---------- Turn thresholds & knobs ----------
STRAIGHT_DEG     = 25.0
BACK_DEG         = 155.0
MERGE_DIR_TOL    = 25.0
PIXELS_PER_STEP  = 25.0
INVERT_LR        = True

# One-shot voice input window (seconds). We only record once for exactly this duration, then recognize.
INPUT_WINDOW_SECONDS = 5

# TTS timing
GAP_SECONDS = 6.0
SPEAK_RATE  = 150
DEBUG_TTS   = False

# ---------- Stair exit facing map ----------
STAIR_FACING_TURNS = {
    "stair1_ff": {"N104": "right", "N103": "left", "P001": "straight"},
    "stair2_ff": {"P003": "straight", "NFT1": "left"},
    "stair3_ff": {"P002": "straight", "P004": "left", "P005": "right"},
    "stair4_ff": {"P006": "straight"},
    "stair1_gf": {"P010": "straight", "P009": "left"},
    "stair2_gf": {"NGT1": "left", "P008": "straight"},
    "stair3_gf": {"NG001": "left", "P013": "right", "PB ATM": "straight"},
    "stair4_gf": {"P015": "straight"},
}

# ---------- TTS ----------
class TTSSpeaker:
    def __init__(self, rate=SPEAK_RATE):
        self.q = queue.Queue()
        self.stop_evt = threading.Event()
        self.rate = rate
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def _loop(self):
        try:
            import pythoncom
        except Exception:
            pythoncom = None

        while not self.stop_evt.is_set():
            try:
                item = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                continue

            text, gap = item

            if pythoncom:
                try:
                    pythoncom.CoInitialize()
                except Exception:
                    pass

            engine = None
            try:
                try:
                    import pyttsx3
                    engine = pyttsx3.init()
                    engine.setProperty('rate', self.rate)
                except Exception:
                    engine = None

                if DEBUG_TTS:
                    print("🔊 Speaking:", text)

                if engine:
                    engine.say(text)
                    engine.runAndWait()
                    try:
                        engine.stop()
                    except Exception:
                        pass
                    del engine
                    engine = None
                else:
                    print("[Speak]", text)

                time.sleep(0.3)

                end_t = time.time() + float(gap)
                while not self.stop_evt.is_set() and time.time() < end_t:
                    time.sleep(0.1)

            except Exception:
                pass
            finally:
                if pythoncom:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

    def stop(self):
        self.stop_evt.set()
        try:
            while not self.q.empty():
                self.q.get_nowait()
        except Exception:
            pass

    def reset(self):
        try:
            while not self.q.empty():
                self.q.get_nowait()
        except Exception:
            pass

    def enqueue_lines(self, lines, gap_seconds=GAP_SECONDS):
        for i, line in enumerate(lines):
            self.q.put((line, gap_seconds if i < len(lines) - 1 else 0.0))

# ---------- Data store ----------
class MapStore:
    def __init__(self, json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.nodes = {}
        for n in data.get("nodes", []):
            nid = n.get("node")
            if not nid:
                continue
            n["neighbours"] = n.get("neighbours", []) or []
            n["actions"]    = n.get("actions", {}) or {}
            if not isinstance(n.get("action"), dict):
                n["action"] = {"label": "", "tts": str(n.get("action") or "")}
            self.nodes[nid] = n

        # Pair stairs gf <-> ff
        self.stair_pair = {}
        groups = {}
        stair_re = re.compile(r"^(stair\d+)_(gf|ff)$", re.IGNORECASE)
        for nid, n in self.nodes.items():
            if (n.get("type") or "").lower() != "stair":
                continue
            m = stair_re.match(nid)
            if not m:
                continue
            base, which = m.group(1).lower(), m.group(2).lower()
            groups.setdefault(base, {})[which] = nid
        for base, d in groups.items():
            if "gf" in d and "ff" in d:
                a, b = d["gf"], d["ff"]
                self.stair_pair[a] = b
                self.stair_pair[b] = a

    def exists(self, nid): return nid in self.nodes
    def neighbors_json(self, nid): return self.nodes.get(nid, {}).get("neighbours", [])
    def neighbors_augmented(self, nid):
        ns = list(self.neighbors_json(nid))
        pair = self.stair_pair.get(nid)
        if pair and pair not in ns:
            ns.append(pair)
        return ns
    def node_type(self, nid): return (self.nodes.get(nid, {}).get("type") or "").lower()
    def floor_of(self, nid): return int(self.nodes[nid]["coordinate"]["floor"])
    def xy(self, nid):
        c = self.nodes[nid]["coordinate"]
        return float(c["x"]), float(c["y"])
    def on_floor(self, f): return [n for n in self.nodes.values() if int(n["coordinate"]["floor"]) == int(f)]
    def action_to(self, a, b): return (self.nodes[a].get("actions") or {}).get(b, {})
    def action_tts(self, nid): return (self.nodes.get(nid, {}).get("action") or {}).get("tts", "").strip()

# ---------- A* path ----------
def a_star(store, start, goal):
    if not (store.exists(start) and store.exists(goal)):
        return None

    def dist(a, b):
        ax, ay = store.xy(a); bx, by = store.xy(b)
        return math.hypot(ax - bx, ay - by)

    def h(nid):
        base = dist(nid, goal)
        gap  = abs(store.floor_of(nid) - store.floor_of(goal)) * 1000.0
        return base + gap

    openh = [(h(start), 0.0, start)]
    came  = {start: None}
    g     = {start: 0.0}

    while openh:
        _, gc, u = heapq.heappop(openh)
        if u == goal:
            path = [u]
            while came[u] is not None:
                u = came[u]
                path.append(u)
            return list(reversed(path))
        for v in store.neighbors_augmented(u):
            base = dist(u, v)
            stair_pen = 400.0 if (store.node_type(u) == "stair" and store.node_type(v) == "stair" and store.floor_of(u) != store.floor_of(v)) else 0.0
            cost = gc + base + stair_pen
            if cost < g.get(v, 1e18):
                g[v] = cost
                came[v] = u
                heapq.heappush(openh, (cost + h(v), cost, v))
    return None

# ---------- Geometry helpers ----------
def heading_deg(ax, ay, bx, by):
    return math.degrees(math.atan2(-(by - ay), (bx - ax))) % 360.0
def delta_angle(a, b):
    return (b - a + 180.0) % 360.0 - 180.0
def _maybe_invert(word, apply_inversion):
    if not apply_inversion: return word
    if word == "left": return "right"
    if word == "right": return "left"
    return word
def dir_word_from_delta(d, apply_inversion=True):
    ad = abs(d)
    if ad <= STRAIGHT_DEG: return "straight"
    if ad >= BACK_DEG:     return "back"
    base = "left" if d < 0 else "right"
    return _maybe_invert(base, apply_inversion)
def segment_steps(store, u, v):
    act = store.action_to(u, v)
    if "steps" in act and isinstance(act["steps"], list) and len(act["steps"]) == 2:
        try:
            return int(act["steps"][0]), int(act["steps"][1])
        except Exception:
            pass
    ax, ay = store.xy(u); bx, by = store.xy(v)
    est = max(1, int(round(math.hypot(bx - ax, by - ay) / PIXELS_PER_STEP)))
    return est, est
def corridor_line_for_path(store, nid):
    if store.node_type(nid) != "path": return None
    tts = store.action_tts(nid)
    if not tts: return None
    m = re.search(r"corridor of\s+(.+)", tts, re.I)
    desc = f'corridor of {m.group(1).strip()}' if m else tts.strip()
    return f'{nid} is "{desc}"'

# ---------- Build instructions ----------
def build_instructions(store, path):
    if not path or len(path) < 2:
        # If path is empty or only one node, directly say destination reached
        return ["Your Destination is reached."]

    segs = []
    prev_head = None
    prev_was_vertical = False
    last_stair_node_after_vertical = None

    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        fu, fv = store.floor_of(u), store.floor_of(v)
        ax, ay = store.xy(u); bx, by = store.xy(v)
        head = heading_deg(ax, ay, bx, by)
        smin, smax = segment_steps(store, u, v)

        if fu != fv:
            # Handle upstairs/downstairs
            turn = "upstairs" if fv > fu else "downstairs"
            segs.append(dict(src=u, dst=v, head=head, turn=turn,
                             smin=smin, smax=smax, vertical=True))
            prev_was_vertical = True
            last_stair_node_after_vertical = v
            continue

        if i == 0:
            # First segment
            act = store.action_to(u, v)
            json_dir = str(act.get("dir") or "").strip().lower()
            if json_dir in ("left", "right", "straight", "back"):
                turn = json_dir
            else:
                if prev_head is None:
                    turn = "straight"
                else:
                    d = delta_angle(prev_head, head)
                    turn = dir_word_from_delta(d, apply_inversion=INVERT_LR)
        else:
            # Subsequent segments
            if prev_was_vertical and last_stair_node_after_vertical and last_stair_node_after_vertical == u:
                forced = STAIR_FACING_TURNS.get(u, {}).get(v)
                if forced in ("left", "right", "straight", "back"):
                    turn = forced
                else:
                    d = delta_angle(prev_head, head) if prev_head is not None else 0.0
                    turn = dir_word_from_delta(d, apply_inversion=INVERT_LR)
            else:
                d = delta_angle(prev_head, head) if prev_head is not None else 0.0
                turn = dir_word_from_delta(d, apply_inversion=INVERT_LR)

        segs.append(dict(src=u, dst=v, head=head, turn=turn,
                         smin=smin, smax=smax, vertical=False))
        prev_head = head
        prev_was_vertical = False
        last_stair_node_after_vertical = None

    # Merge segments with similar direction
    merged = []
    for sg in segs:
        if not merged:
            merged.append(sg.copy())
            continue
        last = merged[-1]
        dtheta = abs(delta_angle(last["head"], sg["head"]))
        if (not sg["vertical"]) and (not last.get("vertical")) and dtheta <= MERGE_DIR_TOL and sg["turn"] == last["turn"]:
            last["dst"]  = sg["dst"]
            last["smin"] += sg["smin"]
            last["smax"] += sg["smax"]
            last["head"]  = sg["head"]
        else:
            merged.append(sg.copy())

    # Build final instruction lines
    lines = []
    for m in merged:
        if m.get("vertical"):
            lines.append(f"go {m['turn']} to {m['dst']}")
        else:
            verb = "go straight" if m["turn"] == "straight" else f"turn {m['turn']}"
            line = f"{verb} and walk {m['smin']} to {m['smax']} steps to {m['dst']}"
            extra = corridor_line_for_path(store, m["dst"])
            if extra:
                line += f". {extra}"
            lines.append(line)

    # Always end with unified message
    lines.append("Your Destination is reached.")

    return lines

# ---------- UI ----------
class App:
    def __init__(self, root):
        self.root = root
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), JSON_NAME)
        if not os.path.exists(json_path):
            messagebox.showerror("Missing file", f"{JSON_NAME} not found:\n{json_path}")
            sys.exit(1)
        if not (os.path.exists(GROUND_PATH) and os.path.exists(FIRST_PATH)):
            messagebox.showerror("Missing map image", "Check ground_floor.png and first_floor.png paths.")
            sys.exit(1)

        self.store = MapStore(json_path)
        try:
            self.images = {
                0: Image.open(GROUND_PATH).convert("RGB"),
                1: Image.open(FIRST_PATH).convert("RGB")
            }
        except Exception as e:
            messagebox.showerror("Image error", str(e))
            sys.exit(1)

        # state
        self.current_floor = 1  # 1 = first, 0 = ground
        self.current_node  = None
        self.dest_node     = None
        self.path          = None

        # TTS
        self.speaker = TTSSpeaker(rate=SPEAK_RATE)

        # view transform (stable, no auto-recenter)
        self.zoom  = DEFAULT_ZOOM
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.dragging = False
        self.drag_last = (0, 0)

        # UI
        root.title("Route Guide — QR-driven")
        root.geometry("1100x780")
        root.minsize(960, 640)

        top = ttk.Frame(root); top.pack(fill="x", padx=10, pady=10)
        self.btn_switch = ttk.Button(top, text="Switch map floor (Ground)", command=self._switch_floor)
        self.btn_goto_text = ttk.Button(top, text="Go to… (text)", command=self._goto_text)
        self.btn_goto_voice = ttk.Button(top, text="Go to… (voice)", command=self._goto_voice)
        self.btn_stop   = ttk.Button(top, text="Stop voice", command=self._stop_voice)
        for b in (self.btn_switch, self.btn_goto_text, self.btn_goto_voice, self.btn_stop):
            b.pack(side="left", padx=(0, 10))

        self.status = ttk.Label(top, text="", anchor="w")
        self.status.pack(side="left", padx=16)

        self.canvas = tk.Canvas(root, bg="#111", highlightthickness=0, cursor="arrow")
        self.canvas.pack(fill="both", expand=True)

        bottom = ttk.Frame(root); bottom.pack(fill="x", padx=10, pady=8)
        ttk.Label(bottom, text="Instructions:", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.txt = tk.Text(bottom, height=6, wrap="word", font=("Segoe UI", 16, "bold"))
        self.txt.pack(fill="x", expand=False); self.txt.configure(state="disabled")

        style = ttk.Style()
        try:
            if "vista" in style.theme_names():
                style.theme_use("vista")
        except Exception:
            pass
        style.configure("TButton", padding=8)

        # bindings
        root.bind("<Configure>", lambda e: self._render())
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.1))    # Linux
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1/1.1))  # Linux
        self.canvas.bind("<ButtonPress-1>", self._on_ldown)
        self.canvas.bind("<B1-Motion>", self._on_ldrag)
        self.canvas.bind("<ButtonRelease-1>", self._on_lup)

        # bootstrap current position + poll
        self._last_scan_raw = None
        nid, raw = self._read_current_position()
        if nid:
            self._apply_current_position(nid)
            self._last_scan_raw = raw
        else:
            self._ensure_default_current()
            self._render()

        self._poll_current_position()

    # ---------- current position I/O ----------
    def _read_current_position(self):
        """Return (mapped_node, raw_text) from current_position.json; None if invalid/missing."""
        try:
            with open(CURPOS_FILE, "r", encoding="utf-8") as f:
                raw = f.read()
            data = json.loads(raw)
        except Exception:
            return None, None

        node = data.get("Node") or data.get("node") or data.get("NODE")
        if not node:
            return None, raw
        node = str(node).strip()

        if self.store.exists(node):
            return node, raw
        for nid in self.store.nodes.keys():
            if nid.lower() == node.lower():
                return nid, raw
        return None, raw

    def _poll_current_position(self):
        """Every 600ms: read file; if content or node changed, apply (no recenter)."""
        try:
            nid, raw = self._read_current_position()
            if nid:
                if (raw != self._last_scan_raw) or (nid != self.current_node):
                    self._last_scan_raw = raw
                    self._apply_current_position(nid)
        except Exception:
            pass
        finally:
            self.root.after(600, self._poll_current_position)

    def _apply_current_position(self, nid):
        """Set current node/floor and clear route. No recenter."""
        self.current_node  = nid
        self.current_floor = self.store.floor_of(nid)
        self._update_switch_button_text()
        self.dest_node = None
        self.path = None
        self._write_instructions([])
        self._set_status(f"Current position set to {nid} (from QR).")
        self._render()

    # ---------- helpers ----------
    def _on_close(self):
        try:
            self.speaker.stop()
        except Exception:
            pass
        self.root.destroy()
        sys.exit(0)

    def _ensure_default_current(self):
        if self.store.exists("N001"):
            self.current_node = "N001"
            self.current_floor = self.store.floor_of("N001")
            self._update_switch_button_text()
            return
        arr = self.store.on_floor(self.current_floor)
        self.current_node = (arr[0]["node"] if arr else None)

    def _set_status(self, s):
        self.status.config(text=s)

    def _update_switch_button_text(self):
        self.btn_switch.config(
            text=("Switch map floor (Ground)" if self.current_floor == 1 else "Switch map floor (First)")
        )

    def _switch_floor(self):
        """Toggle floor and redraw immediately. No centering."""
        self.current_floor = 1 - self.current_floor
        self._update_switch_button_text()
        self._render()

    # ---------- Go To (TEXT) ----------
    def _goto_text(self):
        self._stop_voice()
        dst = simpledialog.askstring("Go to (text)", "Enter destination node (e.g., N003, NFT2, FGO):")
        if not dst:
            return
        self._goto_to_node_id(dst)

    # ---------- Go To (VOICE) ----------
    def _goto_voice(self):
        # Popup UI
        win = tk.Toplevel(self.root)
        win.title("Voice destination")
        win.geometry("380x170")
        win.transient(self.root)
        win.grab_set()

        lbl = ttk.Label(win, text="Where do you want to go?", font=("Segoe UI", 12, "bold"))
        lbl.pack(pady=(14, 8))
        status = ttk.Label(win, text="Listening...", font=("Segoe UI", 11))
        status.pack(pady=(0, 12))

        btn_frame = ttk.Frame(win)
        btn_frame.pack(pady=(0, 10))
        stop_flag = {"stop": False}

        def on_cancel():
            stop_flag["stop"] = True
            try:
                win.destroy()
            except Exception:
                pass

        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack()

        # Speak the prompt once
        self.speaker.enqueue_lines(["Where do you want to go?"], gap_seconds=0.0)

        # One-shot recognition worker: countdown → record fixed window → recognize once
        def worker():
            try:
                import speech_recognition as sr
            except Exception:
                self.root.after(0, lambda: status.config(text="speech_recognition not installed."))
                return

            r = sr.Recognizer()
            r.dynamic_energy_threshold = True
            r.pause_threshold = 0.6
            try:
                with sr.Microphone() as mic:
                    # ambient noise calibration
                    r.adjust_for_ambient_noise(mic, duration=0.7)

                    # countdown: show "Ready to Speak 3..1"
                    for i in range(3, 0, -1):
                        if stop_flag["stop"]:
                            return
                        self.root.after(0, lambda i=i: status.config(text=f"Ready to Speak {i}"))
                        time.sleep(1)

                    if stop_flag["stop"]:
                        return

                    # record exactly INPUT_WINDOW_SECONDS seconds once
                    self.root.after(0, lambda: status.config(text=f"Recording… {INPUT_WINDOW_SECONDS}s"))
                    audio = r.record(mic, duration=INPUT_WINDOW_SECONDS)

                    if stop_flag["stop"]:
                        return

                    # recognize once
                    try:
                        text = r.recognize_google(audio, language="en-US")
                    except sr.UnknownValueError:
                        self.root.after(0, lambda: status.config(text="Didn't catch that."))
                        self.speaker.enqueue_lines(["Voice not clear, please try again."], gap_seconds=0.0)
                        return
                    except sr.RequestError as e:
                        self.root.after(0, lambda: status.config(text=f"Recognizer error: {e}"))
                        return

                    if not text or not text.strip():
                        self.root.after(0, lambda: status.config(text="Empty speech."))
                        self.speaker.enqueue_lines(["No speech detected."], gap_seconds=0.0)
                        return

                    resolved = self._resolve_spoken_destination(text)
                    if resolved:
                        self.root.after(0, lambda: status.config(text=f"Heard: {text} → {resolved}"))
                        self.root.after(150, lambda: (on_cancel(), self._goto_to_node_id(resolved)))
                    else:
                        self.root.after(0, lambda: status.config(text=f"Heard: {text} (no match)"))
                        self.speaker.enqueue_lines(["Destination not recognized."], gap_seconds=0.0)

            except Exception as e:
                self.root.after(0, lambda: status.config(text=f"Mic error: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _speak_unclear(self, status_label):
        msg = "Voice not clear, please speak again."
        self.root.after(0, lambda: status_label.config(text=msg))
        self.speaker.enqueue_lines([msg], gap_seconds=0.0)

    # ---------- Spoken phrase → destination resolver ----------
    def _resolve_spoken_destination(self, phrase: str):
        """
        Rules:
        - FGO / F G O → FGO（若不存在则回退 NF022）
        - PANAS → PANAS
        - PB ATM / ATM → PB ATM
        - THE OLIVE / OLIVE → The Olive
        - Toilet → nearest NGT*/NFT* from current node
        - Also accepts raw node ids or spelled letters+digits (e.g., "N zero zero one" → N001).
        """
        if not phrase:
            return None

        raw = phrase.strip()
        up = raw.upper()

        # FGO first (supports "F G O")
        if "FGO" in up or "F G O" in up:
            if self.store.exists("FGO"):
                return "FGO"
            if self.store.exists("NF022"):
                return "NF022"

        # PANAS
        if "PANAS" in up:
            return "PANAS" if self.store.exists("PANAS") else None

        # Other fixed places
        specials = {
            "PB ATM": "PB ATM",
            "ATM": "PB ATM",
            "THE OLIVE": "The Olive",
            "OLIVE": "The Olive",
        }
        for key, node in specials.items():
            if key in up and self.store.exists(node):
                return node

        # Toilet handling
        if "TOILET" in up or "RESTROOM" in up or "BATHROOM" in up:
            return self._nearest_toilet_node()

        # Try explicit node id contained in phrase (handles "F G O" → "FGO" by stripping spaces)
        nid = self._find_node_from_text(up)
        if nid:
            return nid

        # Try letter+number spelling
        spelled = self._parse_spelled_node(up)
        if spelled and self.store.exists(spelled):
            return spelled

        return None

    def _nearest_toilet_node(self):
        cand = [nid for nid in self.store.nodes.keys() if nid.upper().startswith(("NGT", "NFT"))]
        if not cand:
            cand = [nid for nid, n in self.store.nodes.items() if (n.get("type") or "").lower() == "toilet"]
        if not cand or not self.current_node:
            return None

        best = None
        best_cost = 1e18
        for t in cand:
            p = a_star(self.store, self.current_node, t)
            if p:
                cost = len(p)
            else:
                ax, ay = self.store.xy(self.current_node); bx, by = self.store.xy(t)
                cost = math.hypot(ax - bx, ay - by) + 10000.0
            if cost < best_cost:
                best_cost = cost
                best = t
        return best

    def _find_node_from_text(self, up_text: str):
        compact = up_text.replace(" ", "")
        for nid in self.store.nodes.keys():
            U = nid.upper()
            if U in up_text or U in compact:
                return nid
        for tok in up_text.split():
            for nid in self.store.nodes.keys():
                if tok == nid.upper():
                    return nid
        return None

    def _parse_spelled_node(self, up_text: str):
        word_to_digit = {
            "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
            "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9"
        }
        tokens = re.findall(r"[A-Z]+|\d+", up_text)

        letters = []
        digits  = []
        for t in tokens:
            if re.fullmatch(r"[A-Z]+", t):
                if t in word_to_digit:
                    digits.append(word_to_digit[t])
                else:
                    letters.extend(list(t))
            else:
                digits.append(t)

        if not letters:
            return None

        for w, d in word_to_digit.items():
            up_text = up_text.replace(w, d)
        more_digits = re.findall(r"\d", up_text)
        if len(more_digits) > len(digits):
            digits = more_digits

        prefix = "".join(letters)
        num = "".join(digits)
        if len(num) == 1:
            num = "00" + num
        elif len(num) == 2:
            num = "0" + num
        num = num[:4]
        candidate = prefix + num if num else prefix

        if self.store.exists(candidate):
            return candidate
        for nid in self.store.nodes.keys():
            if nid.upper() == candidate.upper():
                return nid
        return None

    # ---------- route helpers ----------
    def _goto_to_node_id(self, dst_input: str):
        dst = str(dst_input).strip()
        if not self.store.exists(dst):
            found = None
            for nid in self.store.nodes.keys():
                if nid.lower() == dst.lower():
                    found = nid
                    break
            if not found:
                messagebox.showwarning("Not found", f"Node not found: {dst_input}")
                return
            dst = found

        self._stop_voice()
        self.dest_node = dst
        if not self.current_node:
            messagebox.showwarning("No current", "Current node is unknown.")
            return

        self.path = a_star(self.store, self.current_node, self.dest_node)
        if not self.path:
            messagebox.showwarning("No route", f"No path from {self.current_node} to {self.dest_node}.")
            self._write_instructions(["No route found."])
            self._render()
            return

        lines = build_instructions(self.store, self.path)
        self._write_instructions(lines)
        self.speaker.reset()
        self.speaker.enqueue_lines(lines, gap_seconds=GAP_SECONDS)
        self._render()

    def _stop_voice(self):
        try:
            self.speaker.reset()
        except Exception:
            pass

    # ---------- instructions ----------
    def _write_instructions(self, lines):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        if lines:
            self.txt.insert("end", "\n".join(lines))
        self.txt.configure(state="disabled")

    # ---------- view & input ----------
    def _on_wheel(self, e):
        self._zoom_at(e.x, e.y, 1.12 if e.delta > 0 else 1/1.12)

    def _zoom_at(self, x, y, factor):
        img = self.images.get(self.current_floor)
        if not img:
            return
        cw = max(100, self.canvas.winfo_width()); ch = max(100, self.canvas.winfo_height())
        iw, ih = img.size
        s_fit = min(cw / iw, ch / ih)
        s_old = s_fit * self.zoom
        cx, cy = cw // 2, ch // 2
        left_old = cx - (iw * s_old) / 2 + self.pan_x
        top_old  = cy - (ih * s_old) / 2 + self.pan_y
        ix = (x - left_old) / max(1e-6, s_old)
        iy = (y - top_old)  / max(1e-6, s_old)
        self.zoom = max(0.4, min(6.0, self.zoom * factor))
        s_new = s_fit * self.zoom
        left_new = x - ix * s_new
        top_new  = y - iy * s_new
        self.pan_x = left_new - (cx - (iw * s_new) / 2)
        self.pan_y = top_new  - (cy - (ih * s_new) / 2)
        self._render()

    def _on_ldown(self, e):
        self.dragging = True
        self.drag_last = (e.x, e.y)
        self.canvas.config(cursor="hand2")

    def _on_ldrag(self, e):
        if not self.dragging:
            return
        dx = e.x - self.drag_last[0]; dy = e.y - self.drag_last[1]
        self.drag_last = (e.x, e.y)
        self.pan_x += dx; self.pan_y += dy
        self._render()

    def _on_lup(self, e):
        self.dragging = False
        self.canvas.config(cursor="arrow")

    # ---------- drawing ----------
    def _compose(self, floor):
        base = self.images.get(floor)
        if base is None:
            base = Image.new("RGB", (1000, 800), (248, 249, 251))
        im = base.copy()
        dr = ImageDraw.Draw(im, "RGBA")

        # edges
        for nid, n in self.store.nodes.items():
            for nb in self.store.neighbors_json(nid):
                if nid < nb and self.store.floor_of(nid) == floor and self.store.floor_of(nb) == floor:
                    ax, ay = self.xy_safe(nid); bx, by = self.xy_safe(nb)
                    dr.line([(ax, ay), (bx, by)], fill=COLOR_BG_EDGE, width=2)

        # route on current floor
        if self.path and len(self.path) >= 2:
            for i in range(len(self.path) - 1):
                u, v = self.path[i], self.path[i + 1]
                if self.store.floor_of(u) == floor and self.store.floor_of(v) == floor:
                    ux, uy = self.store.xy(u); vx, vy = self.store.xy(v)
                    dr.line([(ux, uy), (vx, vy)], fill=COLOR_ROUTE, width=6)

        # nodes
        for n in self.store.on_floor(floor):
            x, y = n["coordinate"]["x"], n["coordinate"]["y"]
            dr.ellipse((x - NODE_RADIUS, y - NODE_RADIUS, x + NODE_RADIUS, y + NODE_RADIUS),
                       fill=COLOR_NODE, outline="white", width=2)

        # rings + labels
        def ring(nid, color, with_label=False):
            if not nid or self.store.floor_of(nid) != floor:
                return
            x, y = self.store.xy(nid)
            dr.ellipse((x - RING_R, y - RING_R, x + RING_R, y + RING_R), outline=color, width=5)
            if with_label:
                label = str(nid)
                tx, ty = x + RING_R + 6, y - RING_R - 6
                dr.rectangle((tx - 3, ty - 18, tx + 8*len(label) + 6, ty + 4), fill=(0, 0, 0, 160))
                dr.text((tx, ty - 14), label, fill=COLOR_LABEL)

        ring(self.current_node, COLOR_CURR, with_label=True)
        ring(self.dest_node, COLOR_DEST, with_label=True)
        return im

    # safe xy for edges drawing when node may be missing coordinates
    def xy_safe(self, nid):
        try:
            return self.store.xy(nid)
        except Exception:
            return (0, 0)

    def _render(self):
        im = self._compose(self.current_floor)
        cw = max(100, self.canvas.winfo_width()); ch = max(100, self.canvas.winfo_height())
        iw, ih = im.size
        s_fit = min(cw / iw, ch / ih)
        s = s_fit * self.zoom
        tw, th = int(round(iw * s)), int(round(ih * s))
        cx, cy = cw // 2, ch // 2
        left = cx - tw // 2 + int(self.pan_x)
        top  = cy - th // 2 + int(self.pan_y)
        disp = im.resize((max(1, tw), max(1, th)), Image.LANCZOS)
        ph = ImageTk.PhotoImage(disp)
        if not hasattr(self, "_img_id"):
            self._img_id = self.canvas.create_image(left, top, image=ph, anchor="nw")
        else:
            self.canvas.coords(self._img_id, left, top)
            self.canvas.itemconfig(self._img_id, image=ph)
        self.canvas.image = ph

# ---------- main ----------
def main():
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
