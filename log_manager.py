# log_manager.py
import sys
import os
from datetime import datetime

class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
        return len(data)

    def flush(self):
        for s in self.streams:
            s.flush()

class RotatingLogger:
    def __init__(self, log_dir):
        self.log_dir = log_dir
        self.current_date = None
        self.log_file = None

    def _get_log_path(self):
        today_str = datetime.now().strftime("%Y%m%d")
        return os.path.join(self.log_dir, f"log_{today_str}.txt")

    def _open_log_file(self):
        os.makedirs(self.log_dir, exist_ok=True)
        path = self._get_log_path()
        return open(path, "a", encoding="utf-8")

    def _rotate_if_needed(self):
        today = datetime.now().date()
        if self.current_date != today:
            if self.log_file:
                self.log_file.close()
            self.log_file = self._open_log_file()
            self.current_date = today
            self._set_tee()

    def _set_tee(self):
        sys.stdout = Tee(sys.__stdout__, self.log_file)
        sys.stderr = Tee(sys.__stderr__, self.log_file)

    def start(self):
        self._rotate_if_needed()
        print(f"\n{'='*40}")
        print(f"(▶ 실행 시작 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")

    def check_rotation(self):
        self._rotate_if_needed()

    def close(self):
        print(f"(■ 실행 종료 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
        print(f"{'='*40}\n")
        if self.log_file:
            self.log_file.close()
