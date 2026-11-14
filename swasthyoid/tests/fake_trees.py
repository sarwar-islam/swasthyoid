"""Fake OCR engines that start other processes (process-tree tests). Module-level and light, so they can be
sent to a child process. Each records the pids it started, one per line, in the file named by FAKE_PID_FILE.
The started process only sleeps; nothing else is done."""
import os
import subprocess
import sys
import time

RESULT = {"engine": "fake-ocr", "raw_text": "synthetic raw text", "fields": {}}
SLEEPER = "import time; time.sleep(600)"
# forks; the forked process leaves the group and the session, records itself, and sleeps; the first one exits at
# once: the survivor is an orphan in a session of its own (a daemon)
DAEMON = (
    "import os, sys, time\n"
    "if os.fork():\n"
    "    os._exit(0)\n"
    "os.setsid()\n"
    "open(sys.argv[1], 'a').write(str(os.getpid()) + chr(10))\n"
    "time.sleep(600)\n"
)


def _note(pid):
    with open(os.environ["FAKE_PID_FILE"], "a") as f:
        f.write(f"{pid}\n")


def _start(*, new_session=False):
    child = subprocess.Popen([sys.executable, "-c", SLEEPER], start_new_session=new_session)
    _note(child.pid)


def spawn_and_hang(pages, doc_type):
    _start()
    time.sleep(3600)


def spawn_new_session_and_hang(pages, doc_type):
    _start(new_session=True)
    time.sleep(3600)


def spawn_new_session_and_return(pages, doc_type):
    """The engine finishes normally and leaves a descendant in its own session running."""
    _start(new_session=True)
    return RESULT


def report_process_state(pages, doc_type):
    """Linux: "<process group> <pid> <the worker's process group> <1 if this process is a subreaper>"."""
    import ctypes
    flag = ctypes.c_int(0)
    ctypes.CDLL(None, use_errno=True).prctl(37, ctypes.byref(flag), 0, 0, 0)  # PR_GET_CHILD_SUBREAPER
    parent_group = os.getpgid(os.getppid())
    return {**RESULT, "raw_text": f"{os.getpgid(0)} {os.getpid()} {parent_group} {flag.value}"}


def daemon_and_hang(pages, doc_type):
    subprocess.Popen([sys.executable, "-c", DAEMON, os.environ["FAKE_PID_FILE"]]).wait()  # the orphan records itself
    time.sleep(3600)
