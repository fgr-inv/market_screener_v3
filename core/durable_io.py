"""Small durable-file primitives for concurrent automation workers."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from threading import Lock


_LOCKS: dict[str, Lock] = {}
_LOCKS_GUARD = Lock()


def _process_lock(path: Path) -> Lock:
    key=str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key,Lock())


@contextmanager
def file_lock(path):
    """Serialize writers in-process and, on Unix, between worker processes."""
    target=Path(path); target.parent.mkdir(parents=True,exist_ok=True)
    lock_path=target.with_suffix(target.suffix+'.lock')
    with _process_lock(lock_path):
        handle=lock_path.open('a+',encoding='utf-8')
        try:
            try:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            except ImportError:
                pass
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
            except ImportError:
                pass
            handle.close()


def atomic_write_text(path, text, encoding='utf-8'):
    """Write, fsync and atomically replace a file in its own directory."""
    target=Path(path); target.parent.mkdir(parents=True,exist_ok=True)
    with file_lock(target):
        descriptor,temp_name=tempfile.mkstemp(prefix=f'.{target.name}.',suffix='.tmp',dir=target.parent)
        try:
            with os.fdopen(descriptor,'w',encoding=encoding) as handle:
                handle.write(text); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp_name,target)
        finally:
            if os.path.exists(temp_name): os.unlink(temp_name)


def atomic_write_json(path, value):
    atomic_write_text(path,json.dumps(value,ensure_ascii=False,default=str,indent=2))
