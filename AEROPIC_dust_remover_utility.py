###########################################################
#                                                         #
#              AEROPIC dust remover utility               #
#                                                         #
#                        V3.0                             #
#                                                         #
###########################################################

import sys, os, time
import numpy as np
import cv2
from astropy.io import fits
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QLabel, QSlider, QPushButton, QMessageBox, QHBoxLayout, QCheckBox)
from PyQt6.QtCore import Qt, QTimer
from sirilpy import SirilInterface

class AEROPIC(QMainWindow):
    def __init__(self):
        super().__init__()
        self.siril = SirilInterface()
        
        # Display decorated title and version in logs
        self.header_text = (
            "\n###########################################################"
            "\n#              AEROPIC dust remover utility V3.0          #"
            "\n###########################################################"
        )
        try: self.siril.log(self.header_text)
        except: print(self.header_text)     
        
        try:
            self.siril.connect()
            self.current_file = self.siril.get_image_filename()
            raw = self.siril.get_image_pixeldata()
            if raw is None: raise ValueError("Empty image")
            # Image data stored as float32 for processing accuracy
            self.data = raw.astype(np.float32)
            self.header = None
            if self.current_file.lower().endswith(('.fit', '.fits')):
                with fits.open(self.current_file) as hdul: self.header = hdul[0].header
        except Exception as e: print(f"ERROR: {e}"); sys.exit(1)

        # Image properties
        self.c = self.data.shape[0] if self.data.ndim == 3 else 1
        self.h, self.w = self.data.shape[-2:]
        self.min_val, self.max_val = np.nanmin(self.data), np.nanmax(self.data)
        
        # State and Navigation variables
        self.src_pos = None       # Source position (Siril bottom-left coords)
        self.history = []         # Undo buffer
        self.pan_start = None     # Right-click panning start anchor
        self.offset = [0, 0]      # Viewport panning offset
        self.stamp_offset = None  # Distance between source and target for persistent dragging
        self.mouse_pos = (0, 0)   # Current cursor position on UI
        self.vw, self.vh = 1400, 900 # Fixed Viewport dimensions
        
        # Performance Caching
        self._last_r_z = -1       # Tracks if radius or zoom changed to refresh mask
        self._cached_mask = None  # Pre-calculated circular ghost mask

        self.init_ui()
        self.setup_cv()

    def add_sld(self, txt, mi, ma, v, lay):
        """ Adds a formatted slider with real-time value label to the layout """
        h_lay = QHBoxLayout(); lbl_val = QLabel(str(v))
        h_lay.addWidget(QLabel(f"<b>{txt}</b>")); h_lay.addStretch(); h_lay.addWidget(lbl_val); lay.addLayout(h_lay)
        s = QSlider(Qt.Orientation.Horizontal); s.setRange(mi, ma); s.setValue(v)
        s.valueChanged.connect(lambda val: lbl_val.setText(str(val))); lay.addWidget(s)
        return s

    def init_ui(self):
        self.setWindowTitle("AEROPIC dust remover")
        self.setFixedWidth(380)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        central = QWidget(); self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # UI Help Section
        layout.addWidget(QLabel("<b>ALT + LEFT CLIC : define Source</b>"))
        layout.addWidget(QLabel("<b>LEFT CLIC / DRAG : paste Stamp</b>"))
        layout.addWidget(QLabel("<b>RIGHT CLIC / DRAG : pan image</b>"))
        
        # Control Widgets
        self.chk_lock = QCheckBox("Stamp Locked (Fixed Source)"); self.chk_lock.setChecked(False); layout.addWidget(self.chk_lock)
        self.sld_r = self.add_sld("DIAMETER (px)", 10, 500, 150, layout)
        self.sld_h = self.add_sld("HARDNESS (%)", 0, 100, 50, layout)
        self.sld_o = self.add_sld("OPACITY (%)", 5, 100, 100, layout)
        self.sld_s = self.add_sld("DISPLAY STRETCH", 1, 100, 10, layout)
        self.sld_z = self.add_sld("ZOOM (%)", 1, 400, 30, layout)
        
        h_btn = QHBoxLayout()
        btn_u = QPushButton("UNDO"); btn_u.clicked.connect(self.undo); h_btn.addWidget(btn_u)
        btn_save = QPushButton("SAVE"); btn_save.clicked.connect(self.save_auto); h_btn.addWidget(btn_save)
        layout.addLayout(h_btn)

    def setup_cv(self):
        cv2.namedWindow("AEROPIC View", cv2.WINDOW_NORMAL); cv2.resizeWindow("AEROPIC View", self.vw, self.vh)
        cv2.setMouseCallback("AEROPIC View", self.on_mouse)
        self.timer = QTimer(); self.timer.timeout.connect(self.loop)
        # 40ms timer (25 FPS) provides a smoother CPU overhead on non-GPU systems
        self.timer.start(40) 

    def on_mouse(self, event, x, y, flags, param):
        self.mouse_pos = (x, y)
        z = self.sld_z.value() / 100.0
        # Calculate viewport padding and map mouse to real image pixels (rx, ry)
        pad_x, pad_y = max(0, (self.vw-int(self.w*z))//2), max(0, (self.vh-int(self.h*z))//2)
        rx, ry = int((x-pad_x+self.offset[1])/z), self.h-int((y-pad_y+self.offset[0])/z)

        if event == cv2.EVENT_LBUTTONDOWN:
            if flags & cv2.EVENT_FLAG_ALTKEY: 
                # Define cloning source
                self.src_pos = (ry, rx); self.stamp_offset = None 
            elif self.src_pos:
                # Capture initial drag offset if not in 'Locked' mode
                if not self.chk_lock.isChecked() and self.stamp_offset is None:
                    self.stamp_offset = (ry - self.src_pos[0], rx - self.src_pos[1])
                self.clone(ry, rx, save_history=True)
                
        elif event == cv2.EVENT_MOUSEMOVE:
            if flags & cv2.EVENT_FLAG_LBUTTON and self.src_pos:
                # Continuous cloning during drag
                self.clone(ry, rx, save_history=False)
            elif flags & cv2.EVENT_FLAG_RBUTTON and self.pan_start:
                # Viewport panning logic
                self.offset[1] -= (x - self.pan_start[0]); self.offset[0] -= (y - self.pan_start[1])
                self.pan_start = (x, y)
                
        elif event == cv2.EVENT_RBUTTONDOWN: 
            self.pan_start = (x, y)

    def clone(self, yd, xd, save_history=True):
        """ Core cloning function using NumPy slicing and alpha masking """
        if not self.src_pos: return
        
        # Calculate source coordinates based on mode
        ys, xs = (yd - self.stamp_offset[0], xd - self.stamp_offset[1]) if (self.stamp_offset and not self.chk_lock.isChecked()) else self.src_pos
        r = self.sld_r.value() // 2
        
        if save_history:
            self.history.append(self.data.copy())
            if len(self.history) > 15: self.history.pop(0)
            
        # Generate feathering mask (Circular with hardness)
        y, x = np.ogrid[-r:r, -r:r]
        mask = np.clip((r - np.sqrt(x*x + y*y)) / (r * (1.0 - self.sld_h.value()/100.0 + 0.01)), 0, 1) * (self.sld_o.value()/100.0)
        
        # Determine valid overlapping regions for Source and Destination
        y1d, y2d, x1d, x2d = max(0, yd-r), min(self.h, yd+r), max(0, xd-r), min(self.w, xd+r)
        y1s, x1s = int(ys-(yd-y1d)), int(xs-(xd-x1d))
        y2s, x2s = int(y1s+(y2d-y1d)), int(x1s+(x2d-x1d))
        
        if y1s < 0 or x1s < 0 or y2s > self.h or x2s > self.w: return
        
        # Apply cloning per channel
        lm = mask[r-(yd-y1d):r+(y2d-yd), r-(xd-x1d):r+(x2d-xd)]
        for i in range(self.c):
            self.data[i, y1d:y2d, x1d:x2d] = self.data[i, y1d:y2d, x1d:x2d]*(1-lm) + self.data[i, y1s:y2s, x1s:x2s]*lm

    def undo(self):
        if self.history: self.data = self.history.pop()

    def loop(self):
        """ Main display loop: Stretch -> Resize -> Ghost Rendering """
        # Image transformation for OpenCV (BGR + Top-Left origin)
        img_disp = np.flipud(np.transpose(self.data, (1, 2, 0))[:, :, ::-1] if self.c > 1 else self.data)
        
        # Visual stretch (clipping max values based on slider)
        w_clip = self.min_val + (self.max_val - self.min_val) * ((101 - self.sld_s.value()) / 100.0)
        disp = (np.clip((img_disp - self.min_val) / (w_clip - self.min_val + 1e-7), 0, 1) * 255).astype(np.uint8)
        if disp.ndim == 2: disp = cv2.cvtColor(disp, cv2.COLOR_GRAY2BGR)
        
        # Scaling with INTER_NEAREST for maximum UI reactivity
        z = self.sld_z.value() / 100.0
        disp_z = cv2.resize(disp, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
        
        # Build viewport view
        view = np.zeros((self.vh, self.vw, 3), dtype=np.uint8)
        h_z, w_z = disp_z.shape[:2]
        self.offset = [int(np.clip(self.offset[0], 0, max(0, h_z - self.vh))), int(np.clip(self.offset[1], 0, max(0, w_z - self.vw)))]
        y1, y2, x1, x2 = self.offset[0], min(h_z, self.offset[0]+self.vh), self.offset[1], min(w_z, self.offset[1]+self.vw)
        crop = disp_z[y1:y2, x1:x2]
        py, px = (self.vh-crop.shape[0])//2, (self.vw-crop.shape[1])//2
        view[py:py+crop.shape[0], px:px+crop.shape[1]] = crop
        
        # Render the Ghost Stamp preview
        if self.src_pos:
            r = self.sld_r.value() // 2; mx, my = self.mouse_pos
            rx, ry = (mx - px + self.offset[1]) / z, (my - py + self.offset[0]) / z
            isrc_y, isrc_x = self.h - self.src_pos[0], self.src_pos[1]
            
            # Use persistent offset if available (Photoshop mode)
            if self.chk_lock.isChecked(): ys_cv, xs_cv = isrc_y, isrc_x
            elif self.stamp_offset: ys_cv, xs_cv = ry + self.stamp_offset[0], rx - self.stamp_offset[1]
            else: ys_cv, xs_cv = isrc_y, isrc_x

            y1s, y2s, x1s, x2s = int(ys_cv - r), int(ys_cv + r), int(xs_cv - r), int(xs_cv + r)
            if 0 <= y1s and y2s < self.h and 0 <= x1s and x2s < self.w:
                sz_out = int(2*r*z)
                if sz_out > 2:
                    # Update circular mask cache only if size changes
                    if sz_out != self._last_r_z:
                        self._last_r_z = sz_out
                        self._cached_mask = np.zeros((sz_out, sz_out, 1), dtype=np.uint8)
                        cv2.circle(self._cached_mask, (sz_out//2, sz_out//2), sz_out//2, 255, -1)
                    
                    # Blend the source pixels over the target view
                    stamp = cv2.resize(disp[y1s:y2s, x1s:x2s], (sz_out, sz_out), interpolation=cv2.INTER_NEAREST)
                    szh = sz_out // 2
                    t_y1, t_y2, t_x1, t_x2 = my-szh, my-szh+sz_out, mx-szh, mx-szh+sz_out
                    
                    if 0 <= t_y1 and t_y2 < self.vh and 0 <= t_x1 and t_x2 < self.vw:
                        target = view[t_y1:t_y2, t_x1:t_x2]
                        if target.shape[:2] == stamp.shape[:2]:
                            # Optimized blending using cached mask and np.where
                            view[t_y1:t_y2, t_x1:t_x2] = np.where(self._cached_mask == 255, cv2.addWeighted(target, 0.4, stamp, 0.6, 0), target)
                            cv2.circle(view, (mx, my), szh, (255, 255, 255), 1)

        cv2.imshow("AEROPIC View", view); cv2.waitKey(1)

    def save_auto(self):
        """ Export cleaned image to FITS """
        try:
            out = f"{os.path.splitext(self.current_file)[0]}_clean.fit"
            fits.PrimaryHDU(data=self.data.astype(np.float32), header=self.header).writeto(out, overwrite=True)
            QMessageBox.information(self, "OK", f"Saved: {out}")
        except Exception as e: QMessageBox.warning(self, "Error", str(e))

    def closeEvent(self, event):
        self.timer.stop(); cv2.destroyAllWindows(); event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv); win = AEROPIC(); win.show(); sys.exit(app.exec())
