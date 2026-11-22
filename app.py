import sys
from PySide6.QtWidgets import QApplication
from gui import SteganographyApp

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = SteganographyApp()
    window.show()
    sys.exit(app.exec())