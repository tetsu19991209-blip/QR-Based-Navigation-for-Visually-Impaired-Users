import os, json, datetime, random
from typing import Dict, Any, List

try:
    import qrcode
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:
    print("Please install dependencies:\n  pip install qrcode[pil] pillow")
    raise

# ---- Paths ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CANDIDATE_JSON = [
    os.path.join(SCRIPT_DIR, "nodes_map.json"),
    os.path.join(SCRIPT_DIR, "map", "nodes_map.json"),
]
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "qr_codes_colored")

# ---- Config ----
RENDER_LABEL_UNDER_QR = True
LABEL_FONT_SIZE = 28

# Allowed node categories (case-insensitive)
ALLOW_SET = {
    "fgo",
    "panas",
    "the olive",
    "pb atm",
    "lecturer_office",
    "lab_classroom",
}

# Random colors to pick from
COLOR_POOL = ["red", "green", "blue"]


def find_nodes_json() -> str:
    """Locate the nodes_map.json file from candidate paths."""
    for p in CANDIDATE_JSON:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("nodes_map.json not found in candidate paths.")


def want_qr(node: Dict[str, Any]) -> bool:
    """
    Decide whether to generate a QR code for a node:
    - Skip if type is 'stair' or 'path'
    - Accept if node type or node name matches ALLOW_SET
    """
    ntype = (node.get("type") or "").strip().lower()
    if ntype in ("stair", "path"):
        return False

    nid = str(node.get("node", "")).strip().lower()
    if ntype in ALLOW_SET or nid in ALLOW_SET:
        return True

    for token in ALLOW_SET:
        if token and (token in nid or token in ntype):
            return True
    return False


def build_payload(node: Dict[str, Any]) -> Dict[str, Any]:
    """Build the JSON payload to embed into the QR code."""
    nid = str(node.get("node", "Unknown"))
    coord = node.get("coordinate", {}) or {}
    x = coord.get("x", 0)
    y = coord.get("y", 0)
    floor = coord.get("floor", 0)
    neis = node.get("neighbours", []) or []

    meta = {}
    if node.get("type") is not None:
        meta["type"] = node.get("type")
    meta["floor"] = floor
    if node.get("color") is not None:
        meta["color"] = node.get("color")

    return {
        "Node": nid,
        "Coordinate": {"x": x, "y": y},
        "Neigbours": list(neis),
        "Action": "Current Position",
        "meta": meta,
    }


def make_qr_image(data_str: str, fill_color: str, box_size: int = 10, border: int = 4) -> Image.Image:
    """Create a QR code image with the given fill color."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill_color, back_color="white").convert("RGB")
    return img


def load_label_font():
    """Try to load a TTF font; fallback to default if not available."""
    candidates = [
        "arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, LABEL_FONT_SIZE)
        except Exception:
            pass
    return ImageFont.load_default()


def measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    """Measure text size in Pillow 10+ compatible way."""
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return (max(0, r - l), max(0, b - t))
    except Exception:
        try:
            l, t, r, b = font.getbbox(text)
            return (max(0, r - l), max(0, b - t))
        except Exception:
            return (len(text) * LABEL_FONT_SIZE // 2, LABEL_FONT_SIZE)


def add_label_below(qr_img: Image.Image, text: str) -> Image.Image:
    """Add a text label below the QR code image."""
    W, H = qr_img.size
    pad = 16
    label_h = 56
    new_img = Image.new("RGB", (W, H + label_h + pad), "white")
    new_img.paste(qr_img, (0, 0))
    draw = ImageDraw.Draw(new_img)
    font = load_label_font()
    tw, th = measure_text(draw, text, font)
    tx = max(0, (W - tw) // 2)
    ty = H + (label_h - th) // 2
    draw.text((tx, ty), text, fill="black", font=font)
    return new_img


def main():
    json_path = find_nodes_json()
    data = json.load(open(json_path, "r", encoding="utf-8"))
    nodes: List[Dict[str, Any]] = data.get("nodes", [])
    if not nodes:
        print("No nodes in JSON. Nothing to do.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_count = 0

    for node in nodes:
        if not want_qr(node):
            continue

        nid = str(node.get("node", "Unknown")).strip()
        if not nid:
            continue

        payload = build_payload(node)
        payload_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        color = random.choice(COLOR_POOL)
        img = make_qr_image(payload_str, fill_color=color, box_size=10, border=4)

        if RENDER_LABEL_UNDER_QR:
            label = f"{nid}  [{color}]"
            img = add_label_below(img, label)

        safe = "".join(c if c not in r'\/:*?"<>|' else "_" for c in nid)
        out_path = os.path.join(OUTPUT_DIR, f"{safe}.png")
        img.save(out_path)
        out_count += 1

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] Done. Generated {out_count} colored QR PNG(s) in:\n{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
