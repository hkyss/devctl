import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass

from .settings import Settings
from .timeutil import now_iso


@dataclass(frozen=True)
class Service:
    name: str
    domain: str
    status: str
    port: int
    pid: int | None
    project_path: str
    host: str
    log_path: str
    status_detail: str | None


@dataclass(frozen=True)
class StopTarget:
    name: str
    adapter: str
    project_path: str
    command: str
    compose_project_name: str | None


@dataclass(frozen=True)
class ExtraRouteEntry:
    route_name: str
    domain: str
    host: str
    port: int


class Registry:
    def __init__(self, settings: Settings):
        self.settings = settings

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.settings.registry_path)) as db, db:
            yield db

    def ensure(self) -> None:
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.settings.log_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS services (
                  name TEXT PRIMARY KEY,
                  domain TEXT NOT NULL UNIQUE,
                  project_path TEXT NOT NULL,
                  adapter TEXT NOT NULL,
                  command TEXT NOT NULL,
                  host TEXT NOT NULL,
                  port INTEGER NOT NULL,
                  pid INTEGER,
                  status TEXT NOT NULL,
                  status_detail TEXT,
                  log_path TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  compose_project_name TEXT
                )
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(services)").fetchall()}
            if "status_detail" not in columns:
                db.execute("ALTER TABLE services ADD COLUMN status_detail TEXT")
            if "compose_project_name" not in columns:
                db.execute("ALTER TABLE services ADD COLUMN compose_project_name TEXT")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS extra_routes (
                  project_name TEXT NOT NULL,
                  route_name TEXT NOT NULL,
                  domain TEXT NOT NULL UNIQUE,
                  host TEXT NOT NULL,
                  port INTEGER NOT NULL,
                  PRIMARY KEY (project_name, route_name)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS allocated_ports (
                  project_name TEXT NOT NULL,
                  slot_key TEXT NOT NULL,
                  port INTEGER NOT NULL,
                  PRIMARY KEY (project_name, slot_key)
                )
                """
            )

    def active_ports(self, exclude: str | None = None) -> list[int]:
        with self._connect() as db:
            rows = db.execute("SELECT name, port, status FROM services").fetchall()
        return [int(port) for name, port, status in rows if status in {"starting", "healthy", "running"} and name != exclude]

    def upsert_starting(
        self,
        *,
        name: str,
        domain: str,
        project_path: str,
        adapter: str,
        command: str,
        host: str,
        port: int,
        log_path: str,
        compose_project_name: str | None = None,
    ) -> None:
        self.ensure()
        timestamp = now_iso()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO services
                  (name, domain, project_path, adapter, command, host, port, pid, status, status_detail,
                   log_path, created_at, updated_at, compose_project_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  domain=excluded.domain,
                  project_path=excluded.project_path,
                  adapter=excluded.adapter,
                  command=excluded.command,
                  host=excluded.host,
                  port=excluded.port,
                  pid=excluded.pid,
                  status=excluded.status,
                  status_detail=excluded.status_detail,
                  log_path=excluded.log_path,
                  updated_at=excluded.updated_at,
                  compose_project_name=excluded.compose_project_name
                """,
                (
                    name,
                    domain,
                    project_path,
                    adapter,
                    command,
                    host,
                    port,
                    None,
                    "starting",
                    None,
                    log_path,
                    timestamp,
                    timestamp,
                    compose_project_name,
                ),
            )

    def set_status(self, name: str, status: str, detail: str | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE services SET status = ?, status_detail = ?, updated_at = ? WHERE name = ?",
                (status, detail, now_iso(), name),
            )

    def delete(self, name: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM services WHERE name = ?", (name,))
            db.execute("DELETE FROM extra_routes WHERE project_name = ?", (name,))

    def set_extra_routes(self, project_name: str, entries: list[ExtraRouteEntry]) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM extra_routes WHERE project_name = ?", (project_name,))
            db.executemany(
                """
                INSERT INTO extra_routes (project_name, route_name, domain, host, port)
                VALUES (?, ?, ?, ?, ?)
                """,
                [(project_name, entry.route_name, entry.domain, entry.host, entry.port) for entry in entries],
            )

    def set_allocated_ports(self, project_name: str, ports: dict[str, int]) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM allocated_ports WHERE project_name = ?", (project_name,))
            db.executemany(
                "INSERT INTO allocated_ports (project_name, slot_key, port) VALUES (?, ?, ?)",
                [(project_name, slot_key, port) for slot_key, port in ports.items()],
            )

    def allocated_ports_for(self, project_name: str) -> dict[str, int]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT slot_key, port FROM allocated_ports WHERE project_name = ?",
                (project_name,),
            ).fetchall()
        return {row[0]: int(row[1]) for row in rows}

    def forget_allocated_ports(self, project_name: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM allocated_ports WHERE project_name = ?", (project_name,))

    def extra_routes_for(self, project_name: str) -> list[ExtraRouteEntry]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT route_name, domain, host, port FROM extra_routes WHERE project_name = ? ORDER BY route_name",
                (project_name,),
            ).fetchall()
        return [ExtraRouteEntry(route_name=row[0], domain=row[1], host=row[2], port=int(row[3])) for row in rows]

    def stop_target(self, name: str) -> StopTarget | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT name, adapter, project_path, command, compose_project_name FROM services WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            return None
        return StopTarget(name=row[0], adapter=row[1], project_path=row[2], command=row[3], compose_project_name=row[4])

    def names(self) -> list[str]:
        with self._connect() as db:
            return [row[0] for row in db.execute("SELECT name FROM services ORDER BY name").fetchall()]

    def services(self) -> list[Service]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT name, domain, status, port, pid, project_path, host, log_path, status_detail FROM services ORDER BY name"
            ).fetchall()
        return [
            Service(
                name=row[0],
                domain=row[1],
                status=row[2],
                port=int(row[3]),
                pid=row[4],
                project_path=row[5],
                host=row[6],
                log_path=row[7],
                status_detail=row[8],
            )
            for row in rows
        ]

    def routes(self) -> list[tuple[str, str, int]]:
        with self._connect() as db:
            return db.execute(
                """
                SELECT domain, host, port FROM services
                UNION ALL
                SELECT er.domain, er.host, er.port FROM extra_routes er
                  JOIN services s ON s.name = er.project_name
                ORDER BY domain
                """
            ).fetchall()
