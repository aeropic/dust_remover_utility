import sys, os, time
import numpy as np
import cv2
from astropy.io import fits
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QLabel, QSlider, QPushButton, QMessageBox, QHBoxLayout)
from PyQt6.QtCore import Qt, QTimer
from sirilpy import SirilInterface

class AEROPIC(QMainWindow):
    def __init__(self):
        super().__init__()
        self.siril = SirilInterface()
        try:
            self.siril.connect()
            time.sleep(0.5)
            self.current_file = self.siril.get_image_filename()
            raw = self.siril.get_image_pixeldata()
            if raw is None: raise ValueError("empty Image")
            self.data = raw.astype(np.float32)
            self.header = None
            if self.current_file.lower().endswith(('.fit', '.fits')):
                with fits.open(self.current_file) as hdul:
                    self.header = hdul[0].header
        except Exception as e:
            print(f"ERROR: {e}"); sys.exit(1)

        self.c = self.data.shape[0] if self.data.ndim == 3 else 1
        self.h, self.w = self.data.shape[-2:]
        self.min_val, self.max_val = np.nanmin(self.data), np.nanmax(self.data)
        self.src_pos, self.history, self.pan_start = None, [], None
        self.last_dest = None 
        self.offset = [0, 0] 
        self.vw, self.vh = 1400, 900 # Taille fenêtre fixe

        self.init_ui()
        self.setup_cv()

    def init_ui(self):
        self.setWindowTitle("AEROPIC dust removal CONTROL")
        self.setFixedWidth(380)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        central = QWidget(); self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("<b>CTRL+ LEFT CLIC : define Source Stamp</b>"))
        layout.addWidget(QLabel("<b>LEFT CLIC : paste Stamp</b>"))
        layout.addWidget(QLabel("<b>RIGHT CLIC : Pan (move in zoomed view)</b>"))
        layout.addWidget(QLabel("<b>CTRL + Z : undo | CTRL + R : redo</b>"))
        layout.addWidget(QLabel("<b> </b>"))
        
        self.sld_r, _ = self.add_sld("DIAMETER (px)", 10, 500, 150, layout)
        self.sld_h, _ = self.add_sld("HRDNESS (%)", 0, 100, 50, layout)
        self.sld_o, _ = self.add_sld("OPACITY (%)", 5, 100, 100, layout)
        self.sld_s, _ = self.add_sld("DISPLAY STRETCH", 1, 100, 10, layout)
        self.sld_z, self.lbl_z = self.add_sld("ZOOM (%)", 1, 400, 30, layout)

        layout.addSpacing(10)
        h_btn = QHBoxLayout()
        btn_undo = QPushButton("UNDO (Ctrl+Z)"); btn_undo.clicked.connect(self.undo); h_btn.addWidget(btn_undo)
        btn_redo = QPushButton("REDO (Ctrl+R)"); btn_redo.clicked.connect(self.redo); h_btn.addWidget(btn_redo)
        layout.addLayout(h_btn)

        btn_save = QPushButton("SAVE _clean FILE")
        btn_save.setStyleSheet("background: #2E7D32; color: white; font-weight: bold; height: 45px;")
        btn_save.clicked.connect(self.save_auto); layout.addWidget(btn_save)

    def add_sld(self, txt, mi, ma, v, lay):
        h_lay = QHBoxLayout(); lbl_val = QLabel(str(v))
        h_lay.addWidget(QLabel(f"<b>{txt}</b>")); h_lay.addStretch(); h_lay.addWidget(lbl_val); lay.addLayout(h_lay)
        s = QSlider(Qt.Orientation.Horizontal); s.setRange(mi, ma); s.setValue(v)
        s.valueChanged.connect(lambda val: lbl_val.setText(str(val))); lay.addWidget(s)
        return s, lbl_val

    def setup_cv(self):
        cv2.namedWindow("AEROPIC View", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("AEROPIC View", self.vw, self.vh)
        cv2.setMouseCallback("AEROPIC View", self.on_mouse)
        self.timer = QTimer(); self.timer.timeout.connect(self.loop); self.timer.start(40)

    def on_mouse(self, event, x, y, flags, param):
        z = max(0.01, self.sld_z.value() / 100.0)
        # Calcul des coordonnées réelles en tenant compte du centrage
        img_w, img_h = int(self.w * z), int(self.h * z)
        pad_x = max(0, (self.vw - img_w) // 2)
        pad_y = max(0, (self.vh - img_h) // 2)
        
        rx = int((x - pad_x + self.offset[1]) / z)
        ry = self.h - int((y - pad_y + self.offset[0]) / z)

        if event == cv2.EVENT_LBUTTONDOWN:
            if flags & cv2.EVENT_FLAG_CTRLKEY: self.src_pos = (ry, rx)
            elif self.src_pos: self.clone(ry, rx)
        elif event == cv2.EVENT_RBUTTONDOWN: self.pan_start = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and (flags & cv2.EVENT_FLAG_RBUTTON):
            if self.pan_start:
                dx, dy = x - self.pan_start[0], y - self.pan_start[1]
                self.offset[1] -= dx; self.offset[0] -= dy; self.pan_start = (x, y)

    def redo(self):
        if self.last_dest: self.clone(self.last_dest[0], self.last_dest[1])

    def clone(self, yd, xd):
        if not self.src_pos: return
        self.last_dest = (yd, xd)
        ys, xs, r = self.src_pos[0], self.src_pos[1], self.sld_r.value() // 2
        hard, op = self.sld_h.value()/100.0, self.sld_o.value()/100.0
        self.history.append(self.data.copy())
        if len(self.history) > 15: self.history.pop(0)
        y, x = np.ogrid[-r:r, -r:r]
        mask = np.clip((r - np.sqrt(x*x + y*y)) / (r * (1.0 - hard + 0.01)), 0, 1) * op
        y1, y2, x1, x2 = max(0, yd-r), min(self.h, yd+r), max(0, xd-r), min(self.w, xd+r)
        sy1, sx1 = ys - (yd - y1), xs - (xd - x1)
        sy2, sx2 = sy1 + (y2 - y1), sx1 + (x2 - x1)
        if sy1 < 0 or sx1 < 0 or sy2 > self.h or sx2 > self.w: return
        lm = mask[r-(yd-y1):r+(y2-yd), r-(xd-x1):r+(x2-xd)]
        try:
            for i in range(self.c):
                p = self.data[i, sy1:sy2, sx1:sx2]
                self.data[i, y1:y2, x1:x2] = self.data[i, y1:y2, x1:x2]*(1-lm) + p*lm
        except: pass

    def undo(self):
        if self.history: self.data = self.history.pop()

    def loop(self):
        img = np.transpose(self.data, (1, 2, 0))[:, :, ::-1] if self.c > 1 else self.data
        img_disp = np.flipud(img)
        
        white_perc = (101 - self.sld_s.value()) / 100.0
        white_clip = self.min_val + (self.max_val - self.min_val) * white_perc
        disp = (np.clip((img_disp - self.min_val) / (white_clip - self.min_val + 1e-7), 0, 1) * 255).astype(np.uint8)
        if disp.ndim == 2: disp = cv2.cvtColor(disp, cv2.COLOR_GRAY2BGR)
        
        z = max(0.01, self.sld_z.value() / 100.0)
        disp_z = cv2.resize(disp, None, fx=z, fy=z, interpolation=cv2.INTER_LINEAR)
        
        # Gestion du cadre noir et du pan
        view = np.zeros((self.vh, self.vw, 3), dtype=np.uint8)
        
        h_z, w_z = disp_z.shape[:2]
        self.offset[0] = int(np.clip(self.offset[0], 0, max(0, h_z - self.vh)))
        self.offset[1] = int(np.clip(self.offset[1], 0, max(0, w_z - self.vw)))
        
        # Crop de l'image source
        y1, y2 = self.offset[0], min(h_z, self.offset[0] + self.vh)
        x1, x2 = self.offset[1], min(w_z, self.offset[1] + self.vw)
        crop = disp_z[y1:y2, x1:x2]
        
        # Centrage dans la vue fixe
        pad_y = max(0, (self.vh - crop.shape[0]) // 2)
        pad_x = max(0, (self.vw - crop.shape[1]) // 2)
        view[pad_y:pad_y+crop.shape[0], pad_x:pad_x+crop.shape[1]] = crop
        
        if self.src_pos:
            sx = int(self.src_pos[1]*z) - self.offset[1] + pad_x
            sy = int((self.h - self.src_pos[0])*z) - self.offset[0] + pad_y
            if 0 <= sx < self.vw and 0 <= sy < self.vh:
                cv2.circle(view, (sx, sy), int((self.sld_r.value()//2)*z), (0, 255, 0), 2)
        
        cv2.imshow("AEROPIC View", view)
        key = cv2.waitKey(1) & 0xFF
        if key == 26: self.undo() 
        if key == 18: self.redo()

    def save_auto(self):
        try:
            base, ext = os.path.splitext(self.current_file); out = f"{base}_clean{ext}"
            if ext.lower() in ['.fit', '.fits']:
                if self.header: self.header['BITPIX'] = -32
                fits.PrimaryHDU(data=self.data.astype(np.float32), header=self.header).writeto(out, overwrite=True)
            else:
                s_data = np.transpose(self.data, (1, 2, 0))[:,:,::-1] if self.c > 1 else self.data
                cv2.imwrite(out, (s_data * 255).astype(np.uint8))
            QMessageBox.information(self, "Success", f"File saved:\n{out}"); self.close()
        except Exception as e: QMessageBox.warning(self, "Error", str(e))

    def closeEvent(self, event):
        self.timer.stop(); cv2.destroyAllWindows(); event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv); win = AEROPIC(); win.show(); sys.exit(app.exec())