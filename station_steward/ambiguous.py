"""Real Ambiguous task delivery, with durable duplicate prevention and read-back."""
from __future__ import annotations

import copy
import ctypes
import json
import os
import threading
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, SecretStr
from station_steward.local_access import require_laptop

ORIGIN = "https://app.ambiguous.ai"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def protect(data: bytes, *, decrypt=False) -> bytes:
    """Windows DPAPI: credentials remain readable only by this Windows account."""
    if os.name != "nt":
        raise RuntimeError("Saved credentials require Windows on this local companion.")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError("Windows could not secure the saved connection.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


class AmbiguousError(Exception):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def valid_id(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise AmbiguousError("Ambiguous returned an invalid record identifier.") from None


def has_marker(task, marker):
    return f"Handoff reference: {marker}" in [line.strip() for line in (task.get("description") or "").splitlines()]


class AmbiguousConnection:
    def __init__(self, directory: Path, transport=None):
        self.directory = directory
        self.transport = transport
        self.lock = threading.RLock()
        self.operations = threading.RLock()
        self.config = {}
        self.records = {}
        self.problem = ""
        self.journal_ok = True
        try:
            if self.credentials_path.exists():
                self.config = json.loads(protect(self.credentials_path.read_bytes(), decrypt=True))
        except Exception:
            self.problem = "The saved connection could not be opened. Connect again on this laptop."
        try:
            if self.journal_path.exists():
                self.records = json.loads(self.journal_path.read_text(encoding="utf-8"))
                if not isinstance(self.records, dict):
                    raise ValueError()
        except Exception:
            self.journal_ok = False
            self.problem = "The saved handoff log could not be read. Repair it before creating any more tasks."

    @property
    def credentials_path(self):
        return self.directory / "ambiguous-connection.dpapi"

    @property
    def journal_path(self):
        return self.directory / "ambiguous-handoffs.json"

    def _save(self, path, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def _save_config(self, config):
        self._save(self.credentials_path, protect(json.dumps(config).encode()))

    def _record(self, mission_id, record):
        with self.lock:
            updated = {**self.records, mission_id: copy.deepcopy(record)}
            self._save(self.journal_path, json.dumps(updated, indent=2).encode())
            self.records = updated
        return copy.deepcopy(record)

    def _request(self, token, method, path, **kwargs):
        try:
            with httpx.Client(transport=self.transport, timeout=20, follow_redirects=False) as client:
                response = client.request(method, ORIGIN + path, headers={"Authorization": f"Bearer {token}", "API-Version": "1"}, **kwargs)
            if response.status_code >= 400 or response.is_redirect:
                raise AmbiguousError(f"Ambiguous returned HTTP {response.status_code}. Check the key and workspace permissions.", uncertain=method == "POST" and response.status_code >= 500)
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (httpx.HTTPError, ValueError):
            raise AmbiguousError("Ambiguous did not return a usable response. Check the task before trying another mission.", uncertain=method == "POST") from None

    def _identity(self, token):
        identity = self._request(token, "GET", "/api/users/me")
        if identity.get("needs_workspace_setup") or not identity.get("workspace_id"):
            raise AmbiguousError("Finish creating your workspace in Ambiguous first.")
        return {"id": valid_id(identity.get("id")), "workspace_id": valid_id(identity.get("workspace_id")),
                "display_name": identity.get("display_name", "Ambiguous user"), "type": identity.get("type", "unknown")}

    def connect(self, token):
        if not token or len(token) > 8192:
            raise AmbiguousError("Enter the API key from your Ambiguous workspace's Connect instructions.")
        with self.operations:
            identity = self._identity(token)
            people = self._request(token, "GET", "/api/users", params={"limit": 100})
            projects = self._request(token, "GET", "/api/projects", params={"limit": 100})
            # Store only the fields needed for destination selection, never full profiles.
            config = {"token": token, "identity": identity, "enabled": False, "checked_at": timestamp(),
                      "people": [{"id": valid_id(x["id"]), "name": x.get("display_name", "Workspace member"), "type": x.get("type")} for x in people.get("data", []) if x.get("type") == "human"],
                      "projects": [{"id": valid_id(x["id"]), "name": x.get("name", "Project")} for x in projects.get("data", [])],
                      "more_people": bool(people.get("has_more")), "more_projects": bool(projects.get("has_more"))}
            self._save_config(config)
            with self.lock:
                self.config = config
                self.problem = "" if self.journal_ok else self.problem
        return self.snapshot()

    def enable(self, assignee_id, project_id):
        with self.operations:
            with self.lock:
                config = copy.deepcopy(self.config)
            if not config.get("token"):
                raise AmbiguousError("Connect your Ambiguous key first.")
            if not self.journal_ok:
                raise AmbiguousError(self.problem)
            assignee = next((x for x in config["people"] if x["id"] == assignee_id), None)
            project = next((x for x in config["projects"] if x["id"] == project_id), None) if project_id else None
            if not assignee or (project_id and not project):
                raise AmbiguousError("Choose a person and optional project from the connected workspace.")
            current = self._identity(config["token"])
            if current["workspace_id"] != config["identity"]["workspace_id"] or current["id"] != config["identity"]["id"]:
                raise AmbiguousError("The credential's workspace or identity changed. Connect again.")
            config.update(enabled=True, assignee=assignee, project=project, checked_at=timestamp())
            self._save_config(config)
            with self.lock:
                self.config = config
        return self.snapshot()

    def disconnect(self):
        with self.operations, self.lock:
            self.credentials_path.unlink(missing_ok=True)
            self.config = {}
        return self.snapshot()

    def snapshot(self):
        with self.lock:
            workspace = self.config.get("identity", {}).get("workspace_id")
            return copy.deepcopy({"connected": bool(self.config.get("token")), "enabled": bool(self.config.get("enabled")) and self.journal_ok,
                                  **{k: v for k, v in self.config.items() if k not in {"token", "enabled"}}, "problem": self.problem,
                                  "recent": list(reversed([v for v in self.records.values() if v.get("workspace_id") == workspace]))[:10]})

    def _readback(self, config, record):
        task = self._request(config["token"], "GET", f"/api/tasks/{valid_id(record['task_id'])}").get("task", {})
        if task.get("id") != record["task_id"] or not has_marker(task, record["marker"]) or task.get("assignee_id") != record["assignee_id"] or task.get("project_id") != record.get("project_id") or task.get("creator_id") != record["creator_id"]:
            return {**record, "status": "needs_review", "verified": False, "error": "Task read-back did not match the expected handoff. Inspect it in Ambiguous."}
        return {**record, "status": "sent", "sent_to_ambiguous": True, "verified": True, "remote_status": task.get("status"),
                "task_title": task.get("title"), "checked_at": timestamp(), "error": None}

    def deliver(self, mission_id, summary, context, *, cancelled=None):
        cancelled = cancelled or (lambda: False)
        stopped = {"status": "cancelled", "summary": summary, "error": "Stopped before creating an Ambiguous task.", "sent_to_ambiguous": False, "verified": False}
        with self.operations:
            with self.lock:
                config = copy.deepcopy(self.config)
                existing = copy.deepcopy(self.records.get(mission_id))
            if existing:
                return existing  # Never repeat a POST, including after a crash or timeout.
            if cancelled():
                return stopped
            if not config.get("enabled"):
                return {"status": "pending_local", "summary": summary, "sent_to_ambiguous": False, "verified": False}
            if not self.journal_ok:
                return {"status": "not_sent", "summary": summary, "error": self.problem, "sent_to_ambiguous": False, "verified": False}
            try:
                identity = self._identity(config["token"])
                if identity != config["identity"]:
                    # A display-name change is harmless; workspace/user changes are not.
                    if any(identity[k] != config["identity"][k] for k in ("id", "workspace_id")):
                        raise AmbiguousError("The credential's workspace changed. Reconnect before creating tasks.")
            except AmbiguousError as error:
                return {"status": "not_sent", "summary": summary, "error": str(error), "sent_to_ambiguous": False, "verified": False}
            if cancelled():
                return stopped
            marker = f"station-steward:{mission_id}"
            if context.get("station_id", "virtual") == "bench":
                evidence_description = (
                    "This is a physical Arduino bench handoff. Available telemetry comes from the real Arduino. "
                    "The fan runs under autonomous firmware control. No agent actuator command or independently verified fan motion is claimed."
                )
                completion_description = (
                    "After assistance, obtain a fresh bench observation in Station Steward and verify the mission goal; "
                    "completing this task alone does not prove the physical bench goal is satisfied."
                )
            else:
                evidence_description = "This is a simulated workcell handoff. No physical hardware action is claimed."
                completion_description = (
                    "After assistance, run a fresh verification in Station Steward; "
                    "completing this task alone does not prove the simulator goal is satisfied."
                )
            body = {"title": f"Station Steward: {summary.splitlines()[0]}"[:255],
                    "description": f"## Human assistance needed\n{summary}\n\n## Mission goal\n{context['goal']}\n\n## Evidence\n{evidence_description}\n\n```json\n{json.dumps(context, indent=2)}\n```\n\n{completion_description}\n\nHandoff reference: {marker}",
                    "status": "todo", "assignee_id": config["assignee"]["id"]}
            if config.get("project"):
                body["project_id"] = config["project"]["id"]
            record = {"mission_id": mission_id, "marker": marker, "summary": summary, "workspace_id": identity["workspace_id"],
                      "creator_id": identity["id"], "assignee_id": body["assignee_id"], "project_id": body.get("project_id"),
                      "status": "uncertain", "sent_to_ambiguous": False, "verified": False, "created_at": timestamp(), "task_id": None,
                      "error": "Delivery began; check Ambiguous before attempting another task."}
            self._record(mission_id, record)  # Reserve durably BEFORE the external write.
            if cancelled():
                return self._record(mission_id, {**record, **stopped})
            try:
                created = self._request(config["token"], "POST", "/api/tasks", json=body).get("task", {})
                task_id = valid_id(created.get("id"))
                record.update(task_id=task_id, url=f"{ORIGIN}/tasks/{task_id}", sent_to_ambiguous=True, status="created_unverified", error=None)
                self._record(mission_id, record)
                record = self._readback(config, record)
            except AmbiguousError as error:
                record["error"] = str(error)
                # A missing/malformed success ID is also uncertain, never a reason to POST again.
                if not record["task_id"] and not error.uncertain and "HTTP 4" in str(error):
                    record["status"] = "not_sent"
            return self._record(mission_id, record)

    def refresh(self, mission_id):
        with self.operations:
            with self.lock:
                config = copy.deepcopy(self.config)
                record = copy.deepcopy(self.records.get(mission_id))
            if not record or not config.get("token") or record["workspace_id"] != config["identity"]["workspace_id"]:
                raise AmbiguousError("Connect the original workspace to check this handoff.")
            if not record["task_id"]:
                results = self._request(config["token"], "GET", "/api/tasks", params={"q": record["marker"], "show_archived": "true", "limit": 200})
                matches = [x for x in results.get("data", []) if has_marker(x, record["marker"]) and x.get("creator_id") == record["creator_id"]]
                if len(matches) != 1 or results.get("has_more"):
                    record["error"] = "No unique existing task could be confirmed. No replacement task was created."
                    return self._record(mission_id, record)
                record["task_id"] = valid_id(matches[0]["id"])
                record.update(url=f"{ORIGIN}/tasks/{record['task_id']}", sent_to_ambiguous=True)
                self._record(mission_id, record)
            return self._record(mission_id, self._readback(config, record))


class ConnectInput(BaseModel):
    key: SecretStr


class DestinationInput(BaseModel):
    assignee_id: str
    project_id: str | None = None


def ambiguous_router(connection, on_refresh=None):
    router = APIRouter(prefix="/api/ambiguous")

    def local(request):
        require_laptop(request)

    def perform(callback):
        try:
            return callback()
        except AmbiguousError as error:
            raise HTTPException(400, str(error)) from None
        except (OSError, RuntimeError):
            raise HTTPException(500, "The local connection or handoff log could not be saved. No automatic retry was made.") from None

    @router.get("/connection")
    def state(request: Request):
        local(request)
        return connection.snapshot()

    @router.post("/connect")
    def connect(body: ConnectInput, request: Request):
        local(request)
        return perform(lambda: connection.connect(body.key.get_secret_value().strip()))

    @router.post("/destination")
    def destination(body: DestinationInput, request: Request):
        local(request)
        return perform(lambda: connection.enable(body.assignee_id, body.project_id))

    @router.post("/disconnect")
    def disconnect(request: Request):
        local(request)
        return perform(connection.disconnect)

    @router.post("/handoffs/{mission_id}/refresh")
    def refresh(mission_id: str, request: Request):
        local(request)
        record = perform(lambda: connection.refresh(mission_id))
        if on_refresh:
            on_refresh(record)
        return record

    return router
