import cv2
import numpy as np
import json
import time
import pyttsx3
import os
import re
import threading
from urllib.parse import unquote

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_FILE = os.path.join(SCRIPT_DIR, "current_position.json")

# ===================== TTS =====================
def speak(text, rate=175):
    try:
        eng = pyttsx3.init()
        eng.setProperty("rate", rate)
        eng.say(text)
        eng.runAndWait()
        eng.stop()
    except Exception:
        pass

# ===================== UI helpers =====================
def draw_info_panel(img, info_lines, width=380):
    """Right-side solid panel showing parsed QR payload."""
    h, w = img.shape[:2]
    x1 = w - width
    cv2.rectangle(img, (x1, 0), (w, h), (25, 25, 25), -1)
    y = 30
    for line in info_lines:
        cv2.putText(img, line, (x1 + 16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2, cv2.LINE_AA)
        y += 32

def draw_crosshair(img, cx, cy, size=14, color=(255,255,255)):
    """Center crosshair."""
    cx, cy = int(cx), int(cy)
    cv2.line(img, (cx - size, cy), (cx + size, cy), color, 2, cv2.LINE_AA)
    cv2.line(img, (cx, cy - size), (cx, cy + size), color, 2, cv2.LINE_AA)

def put_status_top(img, text, color=(255,255,255)):
    """Top-left status line. (kept for compatibility, not used)"""
    cv2.putText(img, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)

def draw_hint_box_br(img, lines, w=420, h=120):
    """Bottom-right hint box with instructions (legacy, not used now)."""
    H, W = img.shape[:2]
    x1 = W - w - 10
    y1 = H - h - 10
    cv2.rectangle(img, (x1, y1), (x1 + w, y1 + h), (0, 0, 0), -1)
    cv2.rectangle(img, (x1, y1), (x1 + w, y1 + h), (80, 80, 80), 2)
    y = y1 + 36
    for line in lines[:2]:
        cv2.putText(img, line, (x1 + 14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255,255,255), 2, cv2.LINE_AA)
        y += 34

def draw_hint_box_tl(img, lines, pad=10, font_scale=0.50, thickness=2, line_gap=6):
    """Top-left hint box (black) that auto-sizes to fit up to TWO lines."""
    lines = (lines[:2] if len(lines) > 2 else lines)
    if not lines:
        return
    x1, y1 = 10, 10
    sizes = [cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)[0] for line in lines]
    max_w = max(s[0] for s in sizes)
    total_h = sum(s[1] for s in sizes) + line_gap * (len(sizes) - 1)
    w = max_w + pad * 2
    h = total_h + pad * 2
    cv2.rectangle(img, (x1, y1), (x1 + w, y1 + h), (0, 0, 0), -1)
    cv2.rectangle(img, (x1, y1), (x1 + w, y1 + h), (80, 80, 80), 2)
    y = y1 + pad + sizes[0][1]
    for idx, line in enumerate(lines):
        cv2.putText(img, line, (x1 + pad, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255,255,255), thickness, cv2.LINE_AA)
        if idx < len(lines) - 1:
            y += sizes[idx + 1][1] + line_gap

# ===================== parsing helpers =====================
def try_parse_json_loose(s: str):
    """
    Liberal parsing:
    - URL-decoded first
    - Trim control chars
    - If direct json.loads fails, try substring between first '{' and last '}'
    - Last resort: single quotes -> double quotes
    """
    if not s:
        return None
    t = unquote(s).strip().strip("\x00\r\n\t ")
    try:
        return json.loads(t)
    except Exception:
        pass
    m1 = t.find("{"); m2 = t.rfind("}")
    if m1 != -1 and m2 != -1 and m2 > m1:
        core = t[m1:m2+1]
        try:
            return json.loads(core)
        except Exception:
            core2 = re.sub(r"'", r'"', core)
            try:
                return json.loads(core2)
            except Exception:
                return None
    return None

def normalize_payload(p: dict):
    """
    Normalize to:
      Node: str
      Coordinate: {"x":..,"y":..}
      Neigbours: list[str]
      Action: str
      meta: dict (optional)
    """
    if not isinstance(p, dict):
        return {"Node": "Unknown", "Coordinate": {"x": 0, "y": 0}, "Neigbours": [], "Action": "Current Position"}

    lower = {k.lower(): k for k in p.keys()}
    def get_key(*names):
        for name in names:
            k = lower.get(name.lower())
            if k in p:
                return p[k]
        return None

    node = get_key("Node", "node")
    coord = get_key("Coordinate", "coordinate", "coord") or {}
    if not isinstance(coord, dict):
        coord = {}
    if "x" not in coord and "y" not in coord:
        x = get_key("x"); y = get_key("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            coord = {"x": x, "y": y}
    coord = {"x": coord.get("x", 0), "y": coord.get("y", 0)}

    neig = get_key("Neigbours", "neigbours", "neighbours", "neighbors")
    if neig is None:
        neig = []
    if isinstance(neig, str):
        neig = [s for s in re.split(r"[\s,]+", neig) if s]

    action = get_key("Action", "action") or "Current Position"
    meta = get_key("meta")
    if not isinstance(meta, dict):
        meta = {}

    return {
        "Node": str(node) if node is not None else "Unknown",
        "Coordinate": {"x": coord.get("x", 0), "y": coord.get("y", 0)},
        "Neigbours": list(neig) if isinstance(neig, (list, tuple)) else [],
        "Action": str(action),
        "meta": meta
    }

# ===================== geometry & quality =====================
def quad_center(pts):
    """Return center (cx, cy) of 4-point polygon."""
    pts = np.asarray(pts, dtype=np.float32).reshape(-1, 2)
    return np.mean(pts, axis=0)

def edge_lengths(pts):
    """Return lengths of top, right, bottom, left edges (in order)."""
    p = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    top = np.linalg.norm(p[1] - p[0])
    right = np.linalg.norm(p[2] - p[1])
    bottom = np.linalg.norm(p[3] - p[2])
    left = np.linalg.norm(p[0] - p[3])
    return top, right, bottom, left

def quad_rotation_deg(pts):
    """Approximate rotation angle of the QR by top edge vs x-axis."""
    p = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    v = p[1] - p[0]
    ang = np.degrees(np.arctan2(v[1], v[0]))
    return ang

def quality_metrics(pts, img_w, img_h):
    """Compute center offset (pixels & normalized), edge ratios, rotation."""
    cx_img, cy_img = img_w / 2.0, img_h / 2.0
    cqr = quad_center(pts)
    dx, dy = float(cqr[0] - cx_img), float(cqr[1] - cy_img)
    dist_px = np.hypot(dx, dy)
    dist_norm = dist_px / max(img_w, img_h)

    top, right, bottom, left = edge_lengths(pts)
    horiz_ratio = (top + bottom) / max(1e-6, 2.0 * max(top, bottom))
    vert_ratio  = (left + right) / max(1e-6, 2.0 * max(left, right))
    top_vs_bottom = min(top, bottom) / max(1e-6, max(top, bottom))
    left_vs_right = min(left, right) / max(1e-6, max(left, right))
    rot = quad_rotation_deg(pts)
    return {
        "dx": dx, "dy": dy, "dist_px": dist_px, "dist_norm": dist_norm,
        "horiz_ratio": horiz_ratio, "vert_ratio": vert_ratio,
        "top_vs_bottom": top_vs_bottom, "left_vs_right": left_vs_right,
        "rotation_deg": rot
    }

# ===================== color detection =====================
def qr_color_name(frame, pts):
    """
    Determine dominant color inside the QR quad.
    We classify only 'red', 'green', 'blue' based on HSV hue coverage.
    """
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    poly = np.array(pts, dtype=np.int32).reshape(-1, 2)
    cv2.fillPoly(mask, [poly], 255)

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, (0, 80, 60), (10, 255, 255))
    red2 = cv2.inRange(hsv, (170, 80, 60), (180, 255, 255))
    red  = cv2.bitwise_or(red1, red2)
    green = cv2.inRange(hsv, (35, 80, 60), (85, 255, 255))
    blue  = cv2.inRange(hsv, (95, 80, 60), (135, 255, 255))

    r = int(cv2.countNonZero(cv2.bitwise_and(red, red, mask=mask)))
    g = int(cv2.countNonZero(cv2.bitwise_and(green, green, mask=mask)))
    b = int(cv2.countNonZero(cv2.bitwise_and(blue, blue, mask=mask)))

    if max(r, g, b) < 50:
        mean = cv2.mean(frame, mask=mask)[:3]  # B,G,R
        B, G, R = mean
        if R > G and R > B: return "red"
        if G > R and G > B: return "green"
        if B > R and B > G: return "blue"
        return "unknown"

    if r >= g and r >= b: return "red"
    if g >= r and g >= b: return "green"
    if b >= r and b >= g: return "blue"
    return "unknown"

# ===================== safe wrapper for detect/decode =====================
def detect_decode_safe(detector, frame):
    """
    Robust wrapper around OpenCV QR detect/decode that:
      - Attempts detector.detect() and decode(frame, pts)
      - Validates returned pts: must have >=4 points and area > dynamic threshold
      - Falls back to detectAndDecode if needed, but still validates pts/area
    Returns:
      (data: str, pts: np.ndarray or None)
    """
    try:
        h, w = frame.shape[:2]
        min_area = max(100.0, (w * h) * 0.0008)

        # 1) Try detect() + decode(points)
        try:
            ok, pts = detector.detect(frame)
        except Exception:
            ok, pts = False, None

        if ok and pts is not None:
            arr = np.array(pts, dtype=np.float32).reshape(-1, 2)
            if arr.shape[0] >= 4:
                area = float(cv2.contourArea(arr.reshape(-1,1,2)))
                if area >= min_area:
                    try:
                        data, _ = detector.decode(frame, arr)
                        return (data if data else ""), arr
                    except Exception:
                        pass

        # 2) Fallback: detectAndDecode
        try:
            data2, pts2, _ = detector.detectAndDecode(frame)
            pts_arr = None
            if pts2 is not None and len(pts2) > 0:
                pts_arr = np.array(pts2, dtype=np.float32).reshape(-1, 2)
                if pts_arr.shape[0] >= 4:
                    area2 = float(cv2.contourArea(pts_arr.reshape(-1,1,2)))
                    if area2 < min_area:
                        pts_arr = None
            else:
                pts_arr = None
            return (data2 if data2 else ""), pts_arr
        except Exception:
            return "", None

    except Exception:
        return "", None

# ===================== main =====================
def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Camera not available")
        return

    # Startup TTS (async, so it doesn't block the camera loop)
    try:
        threading.Thread(
            target=speak,
            args=("Move camera closer to scan QR code",),
            kwargs={"rate": 175},
            daemon=True
        ).start()
    except Exception:
        pass

    detector = cv2.QRCodeDetector()
    success_frame = None
    show_until = 0
    last_announced_node = None
    last_announcement_time = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        H, W = frame.shape[:2]
        cx_img, cy_img = W / 2.0, H / 2.0

        # Draw center crosshair
        draw_crosshair(frame, cx_img, cy_img, size=14, color=(200, 200, 200))

        # Detect & decode (safe)
        data, pts = detect_decode_safe(detector, frame)

        # Validate polygon presence (explicit)
        poly = None
        poly_valid = False
        if pts is not None and len(pts) >= 4:
            poly = np.array(pts, dtype=np.float32)[:4]
            area = float(cv2.contourArea(poly.reshape(-1,1,2)))
            if area > 0:
                poly_valid = True

        # Draw polygon only if valid
        if poly_valid and poly is not None:
            cv2.polylines(frame, [poly.astype(int)], True, (0, 255, 255), 2)

        # Build top-left TWO-LINE instruction
        if not poly_valid:
            lines = ["No QR code found,", "please scan a QR code"]
        elif poly_valid and not data:
            lines = ["QR pattern found,", "move closer"]
        else:
            if poly is not None:
                color = qr_color_name(frame, poly)
                if color in ("red", "green", "blue"):
                    lines = [f"{color} QR code", "detected"]
                else:
                    lines = ["QR code", "detected"]
            else:
                lines = ["QR code", "detected"]

        # Draw instruction box at top-left
        draw_hint_box_tl(frame, lines)

        # Visual aid only
        if poly_valid and poly is not None:
            cqr = quad_center(poly)
            cv2.circle(frame, (int(cqr[0]), int(cqr[1])), 5, (0, 255, 0), -1, cv2.LINE_AA)
            cv2.line(frame, (int(cx_img), int(cy_img)), (int(cqr[0]), int(cqr[1])), (180, 180, 180), 2, cv2.LINE_AA)

        # If decoded successfully, process payload, save and speak
        if data and poly_valid:
            payload = try_parse_json_loose(data)
            if payload is None:
                normalized = {
                    "Node": "Unknown",
                    "Coordinate": {"x": 0, "y": 0},
                    "Neigbours": [],
                    "Action": "Current Position",
                    "raw": data
                }
            else:
                normalized = normalize_payload(payload)

            try:
                with open(SAVE_FILE, "w", encoding="utf-8") as f:
                    json.dump(normalized, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print("Failed to save current position:", e)

            node_name = normalized.get('Node', 'this location')
            now = time.time()
            if node_name != last_announced_node or (now - last_announcement_time) > 3.0:
                speak(f"You are now in {node_name}")
                last_announced_node = node_name
                last_announcement_time = now

            info_lines = [
                "QR info:",
                f"Node: {normalized['Node']}",
                f"Coordinate: ({normalized['Coordinate']['x']},{normalized['Coordinate']['y']})",
                f"Neigbours: {', '.join(map(str, normalized['Neigbours'])) if normalized['Neigbours'] else '-'}",
                f"Action: Current Position",
            ]
            meta = normalized.get("meta", {})
            if isinstance(meta, dict) and meta:
                info_lines.append(f"Type: {meta.get('type')}  Floor: {meta.get('floor')}  Color: {meta.get('color')}")
            draw_info_panel(frame, info_lines)

            success_frame = frame.copy()
            show_until = time.time() + 3.0

        # Final display
        if success_frame is not None and time.time() < show_until:
            cv2.imshow("QR Reader (Q quit)", success_frame)
        else:
            success_frame = None
            cv2.imshow("QR Reader (Q quit)", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), ord('Q')):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
