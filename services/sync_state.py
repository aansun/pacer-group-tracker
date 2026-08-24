import datetime

_state = None


def record(source, updated_count, total_count, error=None, failed_members=None):
    global _state
    _state = {
        "last_run_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "updated_count": updated_count,
        "total_count": total_count,
        "error": error,
        "failed_members": failed_members or [],
    }
    return _state


def get():
    return _state
