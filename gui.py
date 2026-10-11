import os
import sys
import numpy as np
import cv2
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QFileDialog,
    QTabWidget, QProgressBar, QGroupBox, QMessageBox, QCheckBox,
    QMenuBar, QDockWidget
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QAction

from logger import logger
from workers import ImageWorker, AudioWorker, VideoWorker
from tests import TestEngine
from stego_engine import StegoEngine
from acceleration import get_accelerator

# Check Audio
try:
    import soundfile as sf
    AUDIO_ENABLED = True
except ImportError:
    AUDIO_ENABLED = False

class SteganographyApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Steganography Pro v2.3 (Modular)")
        self.setMinimumSize(1100, 750)
        self.current_worker = None
        self.apply_styles()
        self.create_menu()
        self.create_ui()
        self.create_console()
        self.check_accelerators()

    def check_accelerators(self):
        acc = get_accelerator()
        msg = f"Ready | Acceleration: {acc.upper()}"
        if not AUDIO_ENABLED: msg += " | Audio Disabled"
        self.statusBar().showMessage(msg)

    def create_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)
        
        tools_menu = bar.addMenu("Tools")
        test_act = QAction("Run Self-Test", self)
        test_act.triggered.connect(lambda: TestEngine.run_tests(self))
        tools_menu.addAction(test_act)

    def create_console(self):
        dock = QDockWidget("Console Log", self)
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("font-family: Consolas; font-size: 11px; color: #00FF00; background-color: #000;")
        dock.setWidget(self.log_console)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        logger.subscribe(self.append_log)

    def append_log(self, msg):
        self.log_console.append(msg)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; }
            QWidget { background-color: #121212; color: #E0E0E0; font-family: 'Segoe UI'; font-size: 13px; }
            QMenuBar { background-color: #1E1E1E; border-bottom: 1px solid #333; }
            QMenuBar::item:selected { background-color: #0078D4; }
            QMenu { background-color: #1E1E1E; border: 1px solid #333; }
            QMenu::item:selected { background-color: #0078D4; }
            QGroupBox { border: 1px solid #2D2D2D; border-radius: 5px; margin-top: 20px; font-weight: bold; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; color: #0078D4; }
            QPushButton { background-color: #0078D4; color: white; border-radius: 4px; padding: 10px; font-weight: bold; }
            QPushButton:hover { background-color: #1084D8; }
            QPushButton:disabled { background-color: #333333; color: #666666; }
            QLineEdit, QTextEdit { background-color: #1E1E1E; border: 1px solid #333333; border-radius: 4px; padding: 5px; }
            QProgressBar { border: 2px solid #333; border-radius: 5px; text-align: center; background-color: #1E1E1E; }
            QProgressBar::chunk { background-color: #0078D4; width: 10px; }
            QTabWidget::pane { border: 1px solid #333; background-color: #121212; }
            QTabBar::tab { background-color: #1E1E1E; padding: 10px 20px; border-top-left-radius: 4px; }
            QTabBar::tab:selected { background-color: #0078D4; color: white; }
            QDockWidget { color: #0078D4; }
            QDockWidget::title { background: #1E1E1E; padding: 6px; }
        """)

    def create_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        header = QLabel("🛡️ Steganography Workflow")
        header.setFont(QFont("Segoe UI", 20, QFont.Bold))
        header.setStyleSheet("color: #0078D4;")
        layout.addWidget(header)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.img_ui = self.create_operation_tab("Image")
        self.aud_ui = self.create_operation_tab("Audio")
        self.vid_ui = self.create_operation_tab("Video")

        self.tabs.addTab(self.img_ui['widget'], "🖼️ Image")
        self.tabs.addTab(self.aud_ui['widget'], "🎵 Audio")
        self.tabs.addTab(self.vid_ui['widget'], "🎬 Video")

    def create_operation_tab(self, name):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        left = QVBoxLayout()
        
        # Step 1
        step1_grp = QGroupBox(f"Step 1: Select Source")
        step1_layout = QVBoxLayout(step1_grp)
        path_h = QHBoxLayout()
        path_edit = QLineEdit(); path_edit.setReadOnly(True)
        btn_browse = QPushButton("📂 Browse")
        path_h.addWidget(path_edit); path_h.addWidget(btn_browse)
        info_lbl = QLabel("ℹ️ Capacity: --"); info_lbl.setStyleSheet("color: #888;")
        step1_layout.addLayout(path_h); step1_layout.addWidget(info_lbl)
        left.addWidget(step1_grp)
        
        # Password
        pwd_grp = QGroupBox("🔐 Security")
        pwd_layout = QHBoxLayout(pwd_grp)
        pass_edit = QLineEdit(); pass_edit.setEchoMode(QLineEdit.Password)
        chk_show = QCheckBox("Show")
        chk_show.toggled.connect(lambda c: pass_edit.setEchoMode(QLineEdit.Normal if c else QLineEdit.Password))
        pwd_layout.addWidget(pass_edit); pwd_layout.addWidget(chk_show)
        left.addWidget(pwd_grp)
        layout.addLayout(left, 40)
        
        # Right Panel
        right = QVBoxLayout()
        step2_grp = QGroupBox("Step 2: Payload")
        step2_layout = QVBoxLayout(step2_grp)
        msg_text = QTextEdit()
        file_data = {'data': None, 'name': None}
        
        def attach_file():
            p, _ = QFileDialog.getOpenFileName(self, "Select File")
            if p:
                with open(p, 'rb') as f: file_data['data'] = f.read()
                file_data['name'] = os.path.basename(p)
                msg_text.setText(f"Attached: {file_data['name']}\nSize: {len(file_data['data'])} bytes")
                
        btn_attach = QPushButton("📎 Attach File"); btn_attach.clicked.connect(attach_file)
        step2_layout.addWidget(msg_text); step2_layout.addWidget(btn_attach)
        right.addWidget(step2_grp)
        
        # Actions
        step3_grp = QGroupBox("Step 3: Execute")
        step3_layout = QVBoxLayout(step3_grp)
        btn_encode = QPushButton("🔒 ENCODE"); btn_encode.setStyleSheet("background-color: #28a745; padding: 15px;")
        btn_decode = QPushButton("🔓 DECODE"); btn_decode.setStyleSheet("background-color: #6c757d; padding: 15px;")
        prog_bar = QProgressBar()
        step3_layout.addWidget(btn_encode); step3_layout.addWidget(btn_decode); step3_layout.addWidget(prog_bar)
        right.addWidget(step3_grp)
        layout.addLayout(right, 60)
        
        # Connections
        btn_browse.clicked.connect(lambda: self.browse_file(path_edit, info_lbl, name))
        btn_encode.clicked.connect(lambda: self.start_process('encode', path_edit.text(), file_data, msg_text.toPlainText(), pass_edit.text(), name))
        btn_decode.clicked.connect(lambda: self.start_process('decode', path_edit.text(), None, "", pass_edit.text(), name))
        
        return {
            'widget': widget, 'path': path_edit, 'info': info_lbl, 
            'pass': pass_edit, 'msg': msg_text, 'prog': prog_bar, 
            'btn_enc': btn_encode, 'btn_dec': btn_decode, 'file_data': file_data
        }

    def browse_file(self, path_edit, info_lbl, type_name):
        filters = {"Image": "Images (*.png *.bmp *.tif)", "Audio": "Audio (*.wav *.flac)", "Video": "Video (*.avi)"}
        path, _ = QFileDialog.getOpenFileName(self, "Select", "", filters.get(type_name, ""))
        if path:
            path_edit.setText(path)
            try:
                size = 0
                if type_name == "Image": 
                    img = cv2.imread(path)
                    if img is not None: size = img.size // 8
                elif type_name == "Audio" and AUDIO_ENABLED: 
                    data, _ = sf.read(path)
                    size = len(data) // 8
                elif type_name == "Video":
                    cap = cv2.VideoCapture(path)
                    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    w = int(cap.get(3))
                    h = int(cap.get(4))
                    size = frames * w * h * 3 // 8
                    cap.release()
                info_lbl.setText(f"ℹ️ Capacity: {self.format_size(size)}")
            except Exception as e:
                logger.log("error", f"Error reading capacity: {e}")

    def start_process(self, mode, path, file_dict, text, password, type_name):
        if not path:
            logger.log("warning", "No source file selected.")
            return

        data, is_file, filename = b"", False, ""
        if mode == 'encode':
            if file_dict['data']: 
                data, is_file, filename = file_dict['data'], True, file_dict['name']
            elif text: 
                data = text.encode('utf-8')
            else: 
                return
            
            save_path, _ = QFileDialog.getSaveFileName(self, "Save", "", "")
            if not save_path: return
            self._save_path = save_path
        
        # Worker Selection
        if type_name == "Image": 
            self.current_worker = ImageWorker(path, data, password, is_file, filename, mode)
        elif type_name == "Audio": 
            self.current_worker = AudioWorker(path, data, password, is_file, filename, mode)
        elif type_name == "Video": 
            self.current_worker = VideoWorker(path, data, password, is_file, filename, mode)
        
        # Signals
        try: self.current_worker.finished.disconnect()
        except: pass
        try: self.current_worker.error.disconnect()
        except: pass

        self.current_worker.progress.connect(self.update_progress)
        self.current_worker.finished.connect(lambda res: self.on_finished(res, type_name, mode))
        self.current_worker.error.connect(lambda err: logger.log("error", err))
        self.current_worker.start()

    def update_progress(self, val):
        idx = self.tabs.currentIndex()
        if idx == 0: self.img_ui['prog'].setValue(val)
        elif idx == 1: self.aud_ui['prog'].setValue(val)
        elif idx == 2: self.vid_ui['prog'].setValue(val)

    def on_finished(self, result, type_name, mode):
        type_res, data = result
        if type_res == 'data':
            meta = data[1]
            data = data[0]
            if meta.get('is_file'):
                p, _ = QFileDialog.getSaveFileName(self, "Save File", meta.get('filename',''))
                if p: open(p, 'wb').write(data)
            else:
                idx = self.tabs.currentIndex()
                target_ui = [self.img_ui, self.aud_ui, self.vid_ui][idx]
                try:
                    target_ui['msg'].setText(data.decode('utf-8'))
                except:
                    target_ui['msg'].setText("Binary data extracted (see log).")
                    logger.log("info", f"Binary data size: {len(data)}")
        elif type_res == 'image':
            cv2.imwrite(self._save_path, data)
            logger.log("success", f"Saved to {self._save_path}")
        elif type_res == 'audio_path' or type_res == 'video_path':
            logger.log("success", f"Saved to {data}")

    def format_size(self, n):
        for u in ['B', 'KB', 'MB', 'GB']:
            if n < 1024: return f"{n:.2f} {u}"
            n /= 1024
        return f"{n:.2f} TB"