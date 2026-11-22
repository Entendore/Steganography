from datetime import datetime
from typing import List, Callable

class LogManager:
    """Centralized logging manager to broadcast messages to GUI and Terminal."""
    def __init__(self):
        self.subscribers: List[Callable] = []

    def subscribe(self, callback: Callable):
        self.subscribers.append(callback)

    def log(self, level: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] [{level.upper()}] {message}"
        print(formatted)
        for callback in self.subscribers:
            callback(formatted)

# Global Logger Instance
logger = LogManager()