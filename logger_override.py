# logger_override.py
import builtins
from datetime import datetime

original_print = print

def timestamped_print(*args, **kwargs):
    timestamp = datetime.now().strftime("(%m-%d %H:%M:%S)")
    original_print(timestamp, ":", *args, **kwargs)

builtins.print = timestamped_print