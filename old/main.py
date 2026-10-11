import sys
import os
from PIL import Image
import numpy as np
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QTextEdit, 
                            QFileDialog, QMessageBox, QTabWidget, QGroupBox,
                            QSpinBox, QComboBox, QProgressBar, QSlider,
                            QSplitter, QToolBar, QStatusBar, QSizePolicy,
                            QCheckBox, QRadioButton, QButtonGroup, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QIcon, QAction, QFont, QPalette, QColor

class SteganographyWorker(QThread):
    progress_updated = pyqtSignal(int)
    operation_completed = pyqtSignal(str, bool)
    image_processed = pyqtSignal(QImage)
    capacity_calculated = pyqtSignal(int)

    def __init__(self, operation, image_path=None, message=None, output_path=None, bits=1, encryption_key="", use_encryption=False):
        super().__init__()
        self.operation = operation
        self.image_path = image_path
        self.message = message
        self.output_path = output_path
        self.bits = bits
        self.encryption_key = encryption_key
        self.use_encryption = use_encryption

    def run(self):
        try:
            if self.operation == 'encode':
                self.encode_message()
            elif self.operation == 'decode':
                self.decode_message()
            elif self.operation == 'calculate_capacity':
                self.calculate_capacity()
        except Exception as e:
            self.operation_completed.emit(f"Error: {str(e)}", False)

    def calculate_capacity(self):
        """Calculate maximum message capacity for the selected image"""
        image = Image.open(self.image_path)
        img_array = np.array(image)
        total_pixels = img_array.size
        max_chars = (total_pixels * self.bits) // 8 - 2  # Reserve 2 bytes for end marker
        self.capacity_calculated.emit(max_chars)

    def simple_encrypt(self, text, key):
        """Simple XOR encryption for demonstration purposes"""
        if not key:
            return text
            
        encrypted = ""
        key_len = len(key)
        for i, char in enumerate(text):
            encrypted += chr(ord(char) ^ ord(key[i % key_len]))
        return encrypted

    def simple_decrypt(self, text, key):
        """Simple XOR decryption (same as encryption)"""
        return self.simple_encrypt(text, key)

    def encode_message(self):
        # Load image
        image = Image.open(self.image_path)
        img_array = np.array(image)
        
        # Encrypt message if requested
        message_to_encode = self.message
        if self.use_encryption:
            message_to_encode = self.simple_encrypt(self.message, self.encryption_key)
        
        # Convert message to binary
        binary_message = ''.join(format(ord(char), '08b') for char in message_to_encode)
        binary_message += '1111111111111110'  # End of message marker
        
        # Calculate maximum capacity
        total_pixels = img_array.size
        max_chars = (total_pixels * self.bits) // 8 - 2
        
        if len(message_to_encode) > max_chars:
            raise ValueError(f"Message too long. Maximum capacity: {max_chars} characters")
        
        # Flatten image array
        flat_array = img_array.flatten()
        
        # Encode message
        data_index = 0
        total_bits = len(binary_message)
        
        for i in range(len(flat_array)):
            if data_index < total_bits:
                # Clear the least significant bits
                flat_array[i] = (flat_array[i] >> self.bits) << self.bits
                # Encode the bits
                for bit_pos in range(self.bits):
                    if data_index < total_bits:
                        bit_val = int(binary_message[data_index])
                        flat_array[i] |= (bit_val << bit_pos)
                        data_index += 1
                
                # Update progress
                if i % 1000 == 0:
                    progress = int((data_index / total_bits) * 100)
                    self.progress_updated.emit(progress)
            else:
                break
        
        # Reshape and save
        new_img_array = flat_array.reshape(img_array.shape)
        encoded_image = Image.fromarray(new_img_array.astype(np.uint8))
        
        # Save as PNG to avoid compression artifacts
        if not self.output_path.lower().endswith('.png'):
            self.output_path += '.png'
        encoded_image.save(self.output_path)
        
        # Convert to QImage for preview
        if len(new_img_array.shape) == 3:  # Color image
            height, width, channel = new_img_array.shape
            bytes_per_line = 3 * width
            q_img = QImage(new_img_array.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        else:  # Grayscale
            height, width = new_img_array.shape
            bytes_per_line = width
            q_img = QImage(new_img_array.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8)
        
        self.image_processed.emit(q_img)
        self.operation_completed.emit(f"Message encoded successfully in {os.path.basename(self.output_path)}", True)

    def decode_message(self):
        # Load image
        image = Image.open(self.image_path)
        img_array = np.array(image)
        
        # Flatten image array
        flat_array = img_array.flatten()
        
        binary_message = ""
        message = ""
        end_marker = "1111111111111110"
        
        # Extract bits
        total_pixels = len(flat_array)
        self.progress_updated.emit(0)
        
        for i in range(total_pixels):
            # Extract the least significant bits
            pixel_val = flat_array[i]
            for bit_pos in range(self.bits):
                bit = (pixel_val >> bit_pos) & 1
                binary_message += str(bit)
            
            # Check for end marker every 16 bits
            if len(binary_message) >= 16:
                if binary_message[-16:] == end_marker:
                    binary_message = binary_message[:-16]  # Remove end marker
                    break
            
            # Update progress
            if i % 1000 == 0:
                progress = int((i / total_pixels) * 100)
                self.progress_updated.emit(progress)
        
        # Convert binary to text
        for i in range(0, len(binary_message), 8):
            byte = binary_message[i:i+8]
            if len(byte) == 8:
                char = chr(int(byte, 2))
                message += char
        
        # Decrypt if encryption was used
        if self.use_encryption:
            message = self.simple_decrypt(message, self.encryption_key)
        
        self.operation_completed.emit(message, True)

class SteganographyApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.current_image_path = None
        self.decode_image_path = None

    def initUI(self):
        self.setWindowTitle("Steganography Tool - Hide Secret Messages in Images")
        self.setGeometry(100, 100, 1000, 700)
        
        # Set application style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
            QTextEdit {
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 5px;
            }
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                width: 10px;
            }
            QLabel#imageLabel {
                border: 2px dashed #cccccc;
                border-radius: 5px;
            }
            QLabel#warningLabel {
                color: #d32f2f;
                font-weight: bold;
            }
        """)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create tabs
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        main_layout.addWidget(tabs)
        
        # Create tabs
        encode_tab = QWidget()
        decode_tab = QWidget()
        about_tab = QWidget()
        
        tabs.addTab(encode_tab, "Encode Message")
        tabs.addTab(decode_tab, "Decode Message")
        tabs.addTab(about_tab, "About")
        
        # Setup tabs
        self.setup_encode_tab(encode_tab)
        self.setup_decode_tab(decode_tab)
        self.setup_about_tab(about_tab)
        
        # Create status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready to hide or reveal secret messages")

    def setup_encode_tab(self, tab):
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        
        # Create splitter for image and controls
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left side - image preview
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        image_group = QGroupBox("Cover Image")
        image_layout = QVBoxLayout()
        
        self.image_label = QLabel("Select an image to hide your message")
        self.image_label.setObjectName("imageLabel")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setStyleSheet("font-style: italic; color: #666;")
        
        btn_layout = QHBoxLayout()
        self.select_image_btn = QPushButton("Select Image")
        self.select_image_btn.clicked.connect(self.select_image)
        self.select_image_btn.setIcon(QIcon.fromTheme("document-open"))
        btn_layout.addWidget(self.select_image_btn)
        
        self.capacity_label = QLabel("Maximum capacity: Unknown")
        btn_layout.addWidget(self.capacity_label)
        btn_layout.addStretch()
        
        image_layout.addWidget(self.image_label)
        image_layout.addLayout(btn_layout)
        image_group.setLayout(image_layout)
        left_layout.addWidget(image_group)
        
        # Right side - message and settings
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Message input
        message_group = QGroupBox("Secret Message")
        message_layout = QVBoxLayout()
        
        self.message_text = QTextEdit()
        self.message_text.setPlaceholderText("Enter your secret message here...")
        self.message_text.textChanged.connect(self.update_message_counter)
        message_layout.addWidget(self.message_text)
        
        counter_layout = QHBoxLayout()
        self.message_counter = QLabel("0 characters")
        self.message_counter.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        self.message_warning = QLabel("")
        self.message_warning.setObjectName("warningLabel")
        self.message_warning.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        counter_layout.addWidget(self.message_counter)
        counter_layout.addWidget(self.message_warning)
        message_layout.addLayout(counter_layout)
        
        message_group.setLayout(message_layout)
        right_layout.addWidget(message_group)
        
        # Settings
        settings_group = QGroupBox("Encoding Settings")
        settings_layout = QVBoxLayout()
        
        # Bit selection
        bits_layout = QHBoxLayout()
        bits_layout.addWidget(QLabel("Bits per pixel:"))
        self.bits_spinbox = QSpinBox()
        self.bits_spinbox.setRange(1, 4)
        self.bits_spinbox.setValue(1)
        self.bits_spinbox.setToolTip("Higher values allow longer messages but may make changes more visible")
        self.bits_spinbox.valueChanged.connect(self.calculate_capacity)
        bits_layout.addWidget(self.bits_spinbox)
        
        bits_layout.addWidget(QLabel("Security:"))
        self.encryption_check = QCheckBox("Use encryption")
        self.encryption_check.setToolTip("Simple XOR encryption for added security")
        bits_layout.addWidget(self.encryption_check)
        
        bits_layout.addStretch()
        settings_layout.addLayout(bits_layout)
        
        # Encryption key
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("Encryption Key:"))
        self.encryption_key = QTextEdit()
        self.encryption_key.setMaximumHeight(30)
        self.encryption_key.setPlaceholderText("Enter encryption key (optional)")
        self.encryption_key.setEnabled(False)
        key_layout.addWidget(self.encryption_key)
        settings_layout.addLayout(key_layout)
        
        # Warning label for encryption
        self.encryption_warning = QLabel("Note: This uses simple XOR encryption for demonstration only")
        self.encryption_warning.setObjectName("warningLabel")
        self.encryption_warning.setWordWrap(True)
        self.encryption_warning.setVisible(False)
        settings_layout.addWidget(self.encryption_warning)
        
        # Connect encryption checkbox
        self.encryption_check.toggled.connect(self.encryption_key.setEnabled)
        self.encryption_check.toggled.connect(self.encryption_warning.setVisible)
        
        settings_group.setLayout(settings_layout)
        right_layout.addWidget(settings_group)
        
        # Progress bar
        self.encode_progress = QProgressBar()
        self.encode_progress.setVisible(False)
        right_layout.addWidget(self.encode_progress)
        
        # Encode button
        self.encode_btn = QPushButton("Encode Message")
        self.encode_btn.clicked.connect(self.encode_message)
        self.encode_btn.setIcon(QIcon.fromTheme("document-encrypt"))
        right_layout.addWidget(self.encode_btn)
        
        # Add widgets to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 600])

    def setup_decode_tab(self, tab):
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        
        # Create splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left side - image preview
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        image_group = QGroupBox("Encoded Image")
        image_layout = QVBoxLayout()
        
        self.decode_image_label = QLabel("Select an image with a hidden message")
        self.decode_image_label.setObjectName("imageLabel")
        self.decode_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.decode_image_label.setMinimumSize(400, 300)
        self.decode_image_label.setStyleSheet("font-style: italic; color: #666;")
        
        btn_layout = QHBoxLayout()
        self.select_decode_image_btn = QPushButton("Select Image")
        self.select_decode_image_btn.clicked.connect(self.select_decode_image)
        self.select_decode_image_btn.setIcon(QIcon.fromTheme("document-open"))
        btn_layout.addWidget(self.select_decode_image_btn)
        btn_layout.addStretch()
        
        image_layout.addWidget(self.decode_image_label)
        image_layout.addLayout(btn_layout)
        image_group.setLayout(image_layout)
        left_layout.addWidget(image_group)
        
        # Right side - decoding options and results
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Decode settings
        settings_group = QGroupBox("Decoding Settings")
        settings_layout = QVBoxLayout()
        
        # Bit selection
        bits_layout = QHBoxLayout()
        bits_layout.addWidget(QLabel("Bits per pixel:"))
        self.decode_bits_spinbox = QSpinBox()
        self.decode_bits_spinbox.setRange(1, 4)
        self.decode_bits_spinbox.setValue(1)
        bits_layout.addWidget(self.decode_bits_spinbox)
        
        bits_layout.addWidget(QLabel("Security:"))
        self.decode_encryption_check = QCheckBox("Use encryption")
        bits_layout.addWidget(self.decode_encryption_check)
        bits_layout.addStretch()
        settings_layout.addLayout(bits_layout)
        
        # Encryption key
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("Encryption Key:"))
        self.decode_encryption_key = QTextEdit()
        self.decode_encryption_key.setMaximumHeight(30)
        self.decode_encryption_key.setPlaceholderText("Enter encryption key if used during encoding")
        self.decode_encryption_key.setEnabled(False)
        key_layout.addWidget(self.decode_encryption_key)
        settings_layout.addLayout(key_layout)
        
        # Connect encryption checkbox
        self.decode_encryption_check.toggled.connect(self.decode_encryption_key.setEnabled)
        
        settings_group.setLayout(settings_layout)
        right_layout.addWidget(settings_group)
        
        # Progress bar
        self.decode_progress = QProgressBar()
        self.decode_progress.setVisible(False)
        right_layout.addWidget(self.decode_progress)
        
        # Decode button
        self.decode_btn = QPushButton("Decode Message")
        self.decode_btn.clicked.connect(self.decode_message)
        self.decode_btn.setIcon(QIcon.fromTheme("document-decrypt"))
        right_layout.addWidget(self.decode_btn)
        
        # Result
        result_group = QGroupBox("Decoded Message")
        result_layout = QVBoxLayout()
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        result_layout.addWidget(self.result_text)
        
        result_group.setLayout(result_layout)
        right_layout.addWidget(result_group)
        
        # Add widgets to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 600])

    def setup_about_tab(self, tab):
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Title
        title = QLabel("Steganography Tool")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Description
        description = QLabel(
            "This application allows you to hide secret messages inside images using steganography techniques.\n\n"
            "Steganography is the practice of concealing a message within another medium, such as an image, "
            "in such a way that no one except the intended recipient suspects the existence of the hidden message."
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignJustify)
        layout.addWidget(description)
        
        # Features
        features_group = QGroupBox("Features")
        features_layout = QVBoxLayout()
        
        features = [
            "• Hide text messages inside images without visibly altering the image",
            "• Support for multiple image formats (PNG, JPG, BMP, TIFF)",
            "• Adjustable bit depth for capacity/visibility trade-off",
            "• Optional basic encryption for added security",
            "• Real-time capacity calculation",
            "• Progress indicators for encoding/decoding operations"
        ]
        
        for feature in features:
            label = QLabel(feature)
            features_layout.addWidget(label)
        
        features_group.setLayout(features_layout)
        layout.addWidget(features_group)
        
        # Instructions
        instructions_group = QGroupBox("How to Use")
        instructions_layout = QVBoxLayout()
        
        instructions = [
            "1. Select the Encode tab to hide a message in an image",
            "2. Choose a cover image and enter your secret message",
            "3. Adjust the bit depth (higher values allow longer messages)",
            "4. Optionally enable encryption and provide a key",
            "5. Click 'Encode Message' and save the resulting image",
            "6. To decode, select the Decode tab and choose the encoded image",
            "7. Make sure to use the same bit depth and encryption settings",
            "8. Click 'Decode Message' to reveal the hidden text"
        ]
        
        for instruction in instructions:
            label = QLabel(instruction)
            instructions_layout.addWidget(label)
        
        instructions_group.setLayout(instructions_layout)
        layout.addWidget(instructions_group)
        
        # Security note
        security_note = QLabel(
            "Security Note: The encryption implemented in this tool is a simple XOR cipher "
            "and should not be used for highly sensitive information. For real security, "
            "consider using dedicated encryption tools before hiding data in images."
        )
        security_note.setWordWrap(True)
        security_note.setObjectName("warningLabel")
        layout.addWidget(security_note)
        
        # Spacer
        layout.addStretch()

    def select_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Cover Image", "", 
            "Image Files (*.png *.jpg *.jpeg *.bmp *.tiff);;All Files (*)"
        )
        if file_path:
            self.current_image_path = file_path
            pixmap = QPixmap(file_path)
            scaled_pixmap = pixmap.scaled(400, 300, Qt.AspectRatioMode.KeepAspectRatio, 
                                         Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
            self.status_bar.showMessage(f"Selected: {os.path.basename(file_path)}")
            self.calculate_capacity()

    def select_decode_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Encoded Image", "", 
            "Image Files (*.png *.jpg *.jpeg *.bmp *.tiff);;All Files (*)"
        )
        if file_path:
            self.decode_image_path = file_path
            pixmap = QPixmap(file_path)
            scaled_pixmap = pixmap.scaled(400, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            self.decode_image_label.setPixmap(scaled_pixmap)
            self.status_bar.showMessage(f"Selected encoded image: {os.path.basename(file_path)}")

    def calculate_capacity(self):
        if not self.current_image_path:
            return
        
        bits = self.bits_spinbox.value()
        
        # Start worker thread to calculate capacity
        self.capacity_worker = SteganographyWorker('calculate_capacity', self.current_image_path, bits=bits)
        self.capacity_worker.capacity_calculated.connect(self.update_capacity_label)
        self.capacity_worker.start()
        
        # Also update message warning
        self.update_message_counter()

    def update_capacity_label(self, capacity):
        self.capacity_label.setText(f"Maximum capacity: {capacity} characters")

    def update_message_counter(self):
        length = len(self.message_text.toPlainText())
        self.message_counter.setText(f"{length} characters")
        
        # Update warning if message is too long
        if hasattr(self, 'capacity_label') and self.current_image_path:
            capacity_text = self.capacity_label.text()
            if "Unknown" not in capacity_text:
                max_chars = int(capacity_text.split(": ")[1].split(" ")[0])
                if length > max_chars:
                    self.message_warning.setText(f"Message exceeds capacity by {length - max_chars} characters")
                else:
                    self.message_warning.setText("")

    def encode_message(self):
        if not self.current_image_path:
            QMessageBox.warning(self, "Warning", "Please select an image first!")
            return
        
        message = self.message_text.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "Warning", "Please enter a message to encode!")
            return
        
        # Check if message is too long
        bits = self.bits_spinbox.value()
        self.calculate_capacity()
        capacity_text = self.capacity_label.text()
        if "Unknown" not in capacity_text:
            max_chars = int(capacity_text.split(": ")[1].split(" ")[0])
            if len(message) > max_chars:
                QMessageBox.warning(self, "Warning", 
                                   f"Message is too long for this image and bit depth.\n"
                                   f"Maximum capacity: {max_chars} characters\n"
                                   f"Your message: {len(message)} characters")
                return
        
        # Get output path
        default_name = os.path.splitext(os.path.basename(self.current_image_path))[0] + "_encoded.png"
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Save Encoded Image", default_name, 
            "PNG Images (*.png);;All Files (*)"
        )
        if not output_path:
            return
        
        bits = self.bits_spinbox.value()
        use_encryption = self.encryption_check.isChecked()
        encryption_key = self.encryption_key.toPlainText()
        
        # Disable UI during operation
        self.set_ui_enabled(False)
        self.encode_progress.setVisible(True)
        self.encode_progress.setValue(0)
        
        # Start worker thread
        self.worker = SteganographyWorker('encode', self.current_image_path, message, 
                                         output_path, bits, encryption_key, use_encryption)
        self.worker.progress_updated.connect(self.encode_progress.setValue)
        self.worker.operation_completed.connect(self.on_encode_completed)
        self.worker.image_processed.connect(self.on_image_processed)
        self.worker.start()

    def decode_message(self):
        if not hasattr(self, 'decode_image_path') or not self.decode_image_path:
            QMessageBox.warning(self, "Warning", "Please select an encoded image first!")
            return
        
        bits = self.decode_bits_spinbox.value()
        use_encryption = self.decode_encryption_check.isChecked()
        encryption_key = self.decode_encryption_key.toPlainText()
        
        # Disable UI during operation
        self.set_ui_enabled(False)
        self.decode_progress.setVisible(True)
        self.decode_progress.setValue(0)
        self.result_text.clear()
        
        # Start worker thread
        self.worker = SteganographyWorker('decode', self.decode_image_path, bits=bits,
                                         encryption_key=encryption_key, use_encryption=use_encryption)
        self.worker.progress_updated.connect(self.decode_progress.setValue)
        self.worker.operation_completed.connect(self.on_decode_completed)
        self.worker.start()

    def on_encode_completed(self, message, success):
        self.set_ui_enabled(True)
        self.encode_progress.setVisible(False)
        if success:
            QMessageBox.information(self, "Success", message)
            self.status_bar.showMessage("Message encoded successfully")
        else:
            QMessageBox.critical(self, "Error", message)
            self.status_bar.showMessage("Encoding failed")

    def on_decode_completed(self, message, success):
        self.set_ui_enabled(True)
        self.decode_progress.setVisible(False)
        if success:
            self.result_text.setPlainText(message)
            self.status_bar.showMessage("Message decoded successfully")
        else:
            QMessageBox.critical(self, "Error", message)
            self.status_bar.showMessage("Decoding failed")

    def on_image_processed(self, qimage):
        pixmap = QPixmap.fromImage(qimage)
        scaled_pixmap = pixmap.scaled(400, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        self.decode_image_label.setPixmap(scaled_pixmap)

    def set_ui_enabled(self, enabled):
        self.encode_btn.setEnabled(enabled)
        self.decode_btn.setEnabled(enabled)
        self.select_image_btn.setEnabled(enabled)
        self.select_decode_image_btn.setEnabled(enabled)
        self.bits_spinbox.setEnabled(enabled)
        self.decode_bits_spinbox.setEnabled(enabled)
        self.message_text.setEnabled(enabled)
        self.encryption_check.setEnabled(enabled)
        self.decode_encryption_check.setEnabled(enabled)
        if enabled and self.encryption_check.isChecked():
            self.encryption_key.setEnabled(True)
        else:
            self.encryption_key.setEnabled(False)
        if enabled and self.decode_encryption_check.isChecked():
            self.decode_encryption_key.setEnabled(True)
        else:
            self.decode_encryption_key.setEnabled(False)

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Steganography Tool")
    app.setApplicationVersion("2.0")
    app.setWindowIcon(QIcon.fromTheme("document-encrypt"))
    
    window = SteganographyApp()
    window.show()
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()