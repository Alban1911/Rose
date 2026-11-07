import os


def is_subclient() -> bool:
    return os.environ.get("ROSE_SUBCLIENT") == "1"
