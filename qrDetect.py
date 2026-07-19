import cv2
import numpy as np
import time
import threading
import pyttsx3
from ultralytics import YOLO

DEBUG = False

# ====== TTS (Thread-Safe Speaker) ======
class Speaker:
    def __init__(self, interval=1.8, rate=150):
        self.text = "move closer"
        self.interval = interval
        self.rate = rate
        self.stop_flag = False
        self.lock = threading.Lock()
        self._next_speak_time = time.time() + interval
        self._speak_now_event = threading.Event()
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def set_text(self, t):
        with self.lock:
            if self.text != t:
                self.text = t
                # Signal the loop to speak immediately instead of blocking the main thread
                self._speak_now_event.set()

    def _loop(self):
        # Initialize engine once inside its dedicated thread
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
        except Exception as e:
            print(f"Failed to initialize TTS engine: {e}")
            return

        while not self.stop_flag:
            # Wait for up to 100ms for an immediate speak request
            speak_now = self._speak_now_event.wait(timeout=0.1)
            
            # Speak if requested immediately OR if the regular interval has passed
            if speak_now or time.time() >= self._next_speak_time:
                if speak_now:
                    self._speak_now_event.clear() # Reset the event

                with self.lock:
                    text_to_say = self.text
                
                try:
                    if DEBUG: print("[Speak]", text_to_say)
                    engine.say(text_to_say)
                    engine.runAndWait()
                except Exception:
                    pass # Should probably log this
                
                # Reset the timer for the next scheduled announcement
                self._next_speak_time = time.time() + self.interval

    def stop(self):
        self.stop_flag = True
        # Give the thread a moment to finish cleanly
        self.th.join(timeout=2.0)

# ====== Image Enhancement ======
def enhance_image(frame):
    """Sharpen + brighten + upscale image."""
    kernel = np.array([[0, -1, 0],
                       [-1, 5, -1],
                       [0, -1, 0]])
    sharp = cv2.filter2D(frame, -1, kernel)

    lab = cv2.cvtColor(sharp, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.equalizeHist(l)
    lab = cv2.merge((l, a, b))
    bright = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    sr = cv2.resize(bright, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    return sr

# ====== Color Detection ======
color_ranges = {
    "Red": [(0, 100, 100), (10, 255, 255)],
    "Green": [(40, 40, 40), (90, 255, 255)],
    "Blue": [(100, 150, 0), (140, 255, 255)]
}

def detect_colored_qr(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    for color, (lower, upper) in color_ranges.items():
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        if cv2.countNonZero(mask) > 500:  # if enough pixels of that color
            return color, mask
    return None, None

# ====== Traditional QR Detection ======
def try_traditional_qr(frame, bw=False):
    """Try QR detection using OpenCV. If bw=True, threshold the image first."""
    detector = cv2.QRCodeDetector()
    if bw:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, frame = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)

    data, points, _ = detector.detectAndDecode(frame)
    if points is not None and data:
        return data, points, frame
    return None, None, frame

# ====== YOLO Detection ======
def try_yolo_qr(frame, model):
    results = model.predict(frame, conf=0.4, verbose=False)
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cropped = frame[y1:y2, x1:x2]
            data, _, _ = cv2.QRCodeDetector().detectAndDecode(cropped)
            if data:
                return data, (x1, y1, x2, y2)
    return None, None

# ====== Fallback: Largest Square-ish Contour ======
def find_square_like(bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # contrast boost for colored QR
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        gray = clahe.apply(gray)
    except Exception:
        pass
    gray = cv2.GaussianBlur(gray, (3,3), 0)
    edges = cv2.Canny(gray, 60, 160)
    k = np.ones((3,3), np.uint8)
    edges = cv2.dilate(edges, k, iterations=1)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k, iterations=1)

    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, best_score = None, 0.0
    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04*peri, True)
        if len(approx) != 4: 
            continue
        area = cv2.contourArea(approx)
        if area < 400:
            continue
        rect = cv2.minAreaRect(approx)
        w,h = rect[1]
        if w < 1 or h < 1: 
            continue
        aspect = min(w,h)/max(w,h)
        score = area * (0.5 + 0.5*aspect)
        if score > best_score:
            best_score = score
            best = approx.reshape(-1,2).astype(np.float32)
    if best is None:
        return None
    return order_quad(best[:4])

# ====== Helper Functions ======
def rotate90(frame, k):
    k %= 4
    if k == 0: return frame
    if k == 1: return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if k == 2: return cv2.rotate(frame, cv2.ROTATE_180)
    return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

def order_quad(pts):
    pts = np.array(pts, dtype=np.float32).reshape(4, 2)
    idx = np.lexsort((pts[:,0], pts[:,1]))   # by y then x
    top2 = pts[idx[:2]]
    bot2 = pts[idx[2:]]
    tl, tr = (top2[0], top2[1]) if top2[0,0] <= top2[1,0] else (top2[1], top2[0])
    bl, br = (bot2[0], bot2[1]) if bot2[0,0] <= bot2[1,0] else (bot2[1], bot2[0])
    return np.array([tl, tr, br, bl], dtype=np.float32)

def center_of(pts):
    c = np.mean(pts, axis=0)
    return int(c[0]), int(c[1])

def angle_deg(p1, p2):
    dy = p2[1] - p1[1]
    dx = p2[0] - p1[0]
    return np.degrees(np.arctan2(dy, dx + 1e-6))

def draw_text_with_bg(img, text, org, font_scale=0.85, thickness=2,
                      text_color=(255,255,0), bg_color=(0,0,0), alpha=0.6, pad=6):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    x, y = org
    x1, y1 = x - pad, y - th - pad
    x2, y2 = x + tw + pad, y + pad
    overlay = img.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), bg_color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_color, thickness, cv2.LINE_AA)

def draw_panel_br(img, lines, margin=12, alpha=0.6):
    if not lines: return
    h, w = img.shape[:2]
    sizes = [cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)[0] for s in lines]
    width = max(s[0] for s in sizes) + 2*margin
    height = sum(s[1] + 8 for s in sizes) + 2*margin
    x1, y1 = w - width - 10, h - height - 10
    x2, y2 = w - 10, h - 10
    overlay = img.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0,0,0), -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
    y = y1 + margin + sizes[0][1]
    for s in lines:
        cv2.putText(img, s, (x1 + margin, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255,255,255), 2, cv2.LINE_AA)
        y += sizes[0][1] + 8

# ====== Hybrid Detection ======
def hybrid_qr_detection(frame, yolo_model):
    # Step 1: Enhance frame
    enhanced = enhance_image(frame)

    # Step 2: Try color-based ROI (for Red, Green, Blue QR codes)
    color, mask = detect_colored_qr(enhanced)

    # Step 3: Try traditional OpenCV first (grayscale threshold version)
    data, points, processed = try_traditional_qr(enhanced, bw=True)
    if data:
        return data, points, "Traditional (B/W)", processed, color

    # Step 4: Try traditional (raw enhanced frame)
    data, points, processed = try_traditional_qr(enhanced)
    if data:
        return data, points, "Traditional", processed, color

    # Step 5: YOLO fallback if OpenCV fails
    data, bbox = try_yolo_qr(enhanced, yolo_model)
    if data:
        return data, bbox, "YOLO", enhanced, color

    # Step 6: Fallback to contour detection
    poly = find_square_like(enhanced)
    if poly is not None:
        return None, poly, "Pattern", enhanced, color

    return None, None, None, enhanced, color

# ====== Main Function ======
def main():
    # Load YOLO model
    yolo_model = YOLO("yolov8n.pt")
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Camera not available")
        return

    rotation = 0
    speaker = Speaker(interval=1.8, rate=150)

    # thresholds
    center_tol = 0.05      # center offset tolerance
    min_area_ratio = 0.002 # minimum area ratio for "move closer"
    angle_tol = 6.5        # top edge angle tolerance
    height_diff_ratio = 0.12

    try:
        last_inst = ""  # to avoid frequent set_text
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = rotate90(frame, rotation)
            H, W = frame.shape[:2]
            cx, cy = W//2, H//2

            # Hybrid detection
            data, loc, method, display_frame, color = hybrid_qr_detection(frame, yolo_model)
            
            # Default values
            status = "no QR code detected"
            status_color = (255,255,255)
            instruction = "move closer"
            decoded = bool(data)
            
            # Process detection results
            if loc is not None:
                if method.startswith("Traditional"):
                    # Traditional QR detection
                    pts = loc[0].astype(int)
                    for i in range(len(pts)):
                        cv2.line(display_frame, tuple(pts[i]), tuple(pts[(i+1) % len(pts)]), (0, 255, 0), 2)
                    
                    # Calculate metrics for guidance
                    poly = order_quad(pts[:4])
                    x,y,bw,bh = cv2.boundingRect(poly.astype(int))
                    area_ratio = (bw*bh)/float(W*H)
                    pcx,pcy = center_of(poly)
                    
                    status = "QR code detected"
                    status_color = (0,255,255)
                    
                elif method == "YOLO":
                    # YOLO detection
                    x1, y1, x2, y2 = loc
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                    
                    # Calculate metrics for guidance
                    bw, bh = x2-x1, y2-y1
                    area_ratio = (bw*bh)/float(W*H)
                    pcx, pcy = (x1+x2)//2, (y1+y2)//2
                    
                    status = "QR code detected (YOLO)"
                    status_color = (0,255,255)
                    
                elif method == "Pattern":
                    # Pattern detection
                    poly = loc
                    cv2.polylines(display_frame, [poly.astype(int)], True, (160,160,160), 2)
                    
                    # Calculate metrics for guidance
                    x,y,bw,bh = cv2.boundingRect(poly.astype(int))
                    area_ratio = (bw*bh)/float(W*H)
                    pcx,pcy = center_of(poly)
                    
                    status = "QR pattern found"
                    status_color = (180,180,180)
                
                # Generate guidance instructions
                if decoded:
                    instruction = "hold steady"
                else:
                    dx = (pcx - cx)/float(W)
                    dy = (pcy - cy)/float(H)
                    
                    # Center alignment first
                    if abs(dx) > center_tol:
                        instruction = "move camera left" if dx < 0 else "move camera right"
                    elif abs(dy) > center_tol:
                        instruction = "move camera up" if dy < 0 else "move camera down"
                    else:
                        # Check size
                        if area_ratio < min_area_ratio:
                            instruction = "move closer"
                        else:
                            # Check tilt
                            if method != "YOLO":  # For YOLO we don't have polygon points
                                p = poly.reshape(-1,2)
                                top_angle = angle_deg(p[0], p[1])  # TL->TR
                                if abs(top_angle) > angle_tol:
                                    instruction = "tilt camera left" if top_angle > 0 else "tilt camera right"
                                else:
                                    lh = np.linalg.norm(p[3]-p[0])
                                    rh = np.linalg.norm(p[2]-p[1])
                                    if abs(lh - rh)/max(lh, rh, 1e-6) > height_diff_ratio:
                                        instruction = "tilt camera up" if lh < rh else "tilt camera down"
                                    else:
                                        instruction = "hold steady"
                            else:
                                instruction = "hold steady"
            
            # Display status and data
            draw_text_with_bg(display_frame, status, (10, 32),
                              font_scale=0.85, thickness=2,
                              text_color=status_color, bg_color=(0,0,0), alpha=0.6, pad=6)
            
            if data:
                label = f"{data} ({method})"
                if color:
                    label += f" | Color: {color}"
                draw_text_with_bg(display_frame, label, (10, 70),
                                  font_scale=0.7, thickness=2,
                                  text_color=(0,255,0), bg_color=(0,0,0), alpha=0.6, pad=6)
            
            # Draw center marker
            cv2.drawMarker(display_frame, (cx, cy), (210,210,210), cv2.MARKER_CROSS, 22, 2)
            
            # Display instruction
            draw_panel_br(display_frame, [instruction], alpha=0.6)
            
            # TTS: speak instruction when it changes
            if instruction != last_inst:
                speaker.set_text(instruction)
                last_inst = instruction
            
            # Show the frame
            cv2.imshow("Hybrid QR Detection (R rotate, Q quit)", display_frame)
            
            # Handle key presses
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q')): break
            if key in (ord('r'), ord('R')): rotation = (rotation + 1) % 4

    finally:
        speaker.stop()
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
