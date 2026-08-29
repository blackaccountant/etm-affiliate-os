"""Generic durable execution lease authority and independent heartbeat."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from uuid import uuid4
from app.core.config import settings
@dataclass(frozen=True)
class ExecutionLeaseAuthority:
 execution_id:int; lease_owner:str; lease_generation:int
 @classmethod
 def fresh(cls,execution_id,generation=0): return cls(execution_id,uuid4().hex,generation)
class ExecutionLeaseHeartbeat:
 def __init__(self,session_factory,authority,lease_seconds=None,heartbeat_seconds=None):
  self.session_factory=session_factory;self.authority=authority;self.lease_seconds=lease_seconds or settings.EXECUTION_LEASE_SECONDS;self.heartbeat_seconds=heartbeat_seconds or settings.EXECUTION_HEARTBEAT_SECONDS;self.lost=False;self._stop=Event();self._thread=None
 def start(self):
  if self.heartbeat_seconds>=self.lease_seconds: raise ValueError("heartbeat interval must be shorter than lease duration")
  self._thread=Thread(target=self._run,daemon=True);self._thread.start();return self
 def _run(self):
  while not self._stop.wait(self.heartbeat_seconds):
   db=self.session_factory()
   try:
    from app.repositories.execution_repository import ExecutionRepository
    if not ExecutionRepository(db).renew_lease(self.authority,self.lease_seconds): self.lost=True;return
   except Exception: pass
   finally: db.close()
 def stop(self):
  self._stop.set()
  if self._thread:self._thread.join(timeout=self.heartbeat_seconds+1)
 def __enter__(self):return self.start()
 def __exit__(self,*_):self.stop()
