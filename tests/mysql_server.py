"""An opt-in disposable *real* MySQL server, isolated from the user's service.

Never uses .env. Creates a fresh data directory and loopback port, and tears
down only its owned child process. Data/logs stay in ignored .test-artifacts.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time

import pymysql

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def disposable_mysql():
    executable = Path(os.environ.get("NILA_TEST_MYSQLD", r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe"))
    if not executable.is_file():
        raise RuntimeError("MySQL Server executable not found. Set NILA_TEST_MYSQLD or run tests without --mysql-integration.")
    artifacts = ROOT / ".test-artifacts"
    artifacts.mkdir(exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="mysql-", dir=artifacts)).resolve()
    datadir = run_dir / "data"
    datadir.mkdir()
    password = secrets.token_hex(32)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (run_dir / "initialize.log").open("w", encoding="utf-8") as init_log:
        initialized = subprocess.run(
            [str(executable), "--no-defaults", "--initialize-insecure", f"--datadir={datadir}"],
            stdout=init_log, stderr=subprocess.STDOUT, timeout=120, creationflags=flags,
        )
    if initialized.returncode:
        raise RuntimeError(f"Disposable MySQL initialization failed. See {run_dir / 'initialize.log'}.")
    # An init-file sets a random root password before the server accepts clients.
    # It is an ignored, short-lived runtime artifact; the token is never printed.
    init_file = run_dir / "bootstrap.sql"
    init_file.write_text(f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{password}';\n", encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = None
    try:
        with (run_dir / "server.log").open("w", encoding="utf-8") as server_log:
            server = subprocess.Popen(
                [str(executable), "--no-defaults", f"--datadir={datadir}", "--bind-address=127.0.0.1",
                 f"--port={port}", "--mysqlx=OFF", "--skip-log-bin", "--innodb-buffer-pool-size=64M",
                 f"--init-file={init_file}", "--console"],
                stdout=server_log, stderr=subprocess.STDOUT, creationflags=flags,
            )
            deadline = time.monotonic() + 60
            while True:
                if server.poll() is not None:
                    raise RuntimeError(f"Disposable MySQL exited. See {run_dir / 'server.log'}.")
                try:
                    connection = pymysql.connect(host="127.0.0.1", port=port, user="root", password=password, connect_timeout=2)
                    break
                except pymysql.Error:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Disposable MySQL did not become ready within 60 seconds.") from None
                    time.sleep(.5)
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT @@datadir, VERSION()")
                    actual_dir, version = cursor.fetchone()
                    if Path(actual_dir).resolve() != datadir:
                        raise RuntimeError("Test server identity mismatch; refusing any database writes.")
                    cursor.execute("CREATE DATABASE nila_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            init_file.unlink()
            settings = {"NILA_DB_HOST": "127.0.0.1", "NILA_DB_PORT": str(port), "NILA_DB_NAME": "nila_test",
                        "NILA_DB_USER": "root", "NILA_DB_PASSWORD": password, "NILA_SECRET_KEY": secrets.token_hex(32)}
            print(f"Disposable MySQL {version} running on loopback port {port}; isolated data: {run_dir}", flush=True)
            yield settings
    finally:
        if init_file.exists():
            init_file.unlink()
        if server is not None and server.poll() is None:
            try:
                with pymysql.connect(host="127.0.0.1", port=port, user="root", password=password, connect_timeout=2) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT @@datadir")
                        if Path(cursor.fetchone()[0]).resolve() == datadir:
                            cursor.execute("SHUTDOWN")
            except pymysql.Error:
                pass
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.terminate()
                server.wait(timeout=10)

