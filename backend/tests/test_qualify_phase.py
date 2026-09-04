import importlib.util, json
from pathlib import Path
import pytest

MODULE=Path(__file__).parents[1]/"scripts"/"qualify_phase.py"; spec=importlib.util.spec_from_file_location("qualify_phase",MODULE); q=importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
def base(): return {"format_version":1,"phase":"X","expected_branch":"b","expected_base_head":"h","candidate_manifest":["a.py","t.py"],"production_files":["a.py"],"test_files":["t.py"],"compile_targets":["a.py"],"required_alembic_revision":"r","migration_expectation":"none","test_suites":[{"name":"t","kind":"unit","path":"t.py","timeout_seconds":1,"postgresql":None}],"default_timeout_seconds":1}
def write(root,d):
 for p in ("a.py","t.py"): (root/p).write_text("")
 path=root/"s.json"; path.write_text(json.dumps(d)); return path
@pytest.mark.parametrize("mut",[lambda d:d.update(format_version=2),lambda d:d.pop("phase"),lambda d:d.update(candidate_manifest=["a.py","a.py"]),lambda d:d.update(candidate_manifest=["../x"]),lambda d:d.update(production_files=["x.py"]),lambda d:d.update(migration_expectation="bad")])
def test_spec_rejections(tmp_path,mut):
 d=base(); mut(d)
 with pytest.raises(q.SpecError): q.load_spec(tmp_path,write(tmp_path,d))
def test_spec_and_hash(tmp_path):
 p=write(tmp_path,base()); assert q.load_spec(tmp_path,p)["phase"]=="X"; assert q.sha(tmp_path/"a.py")==q.sha(tmp_path/"a.py")
def test_junit_counts(tmp_path):
 p=tmp_path/"x.xml"; p.write_text('<testsuite tests="4" failures="1" errors="1" skipped="1"/>'); assert q.junit(p)=={"collected":4,"passed":1,"failed":1,"errors":1,"skipped":1}
def test_junit_fails_closed(tmp_path):
 with pytest.raises(q.SpecError): q.junit(tmp_path/"none.xml")
def test_pg_redaction(monkeypatch):
 pg={"url_env":"U","role_env":"R","required_role":"qualification","expected_driver_prefix":"postgresql","expected_host":"127.0.0.1","expected_port":5432,"expected_database":"db","required_revision":"r","fresh_database_required":True,"freshness_attestation_env":"F"}
 monkeypatch.delenv("U",raising=False); safe,reason=q.pg_guard(pg); assert reason=="PG_NOT_CONFIGURED" and "password" not in str(safe)
 monkeypatch.setenv("U","postgresql://user:secret@wrong:5432/db"); monkeypatch.setenv("R","qualification"); safe,reason=q.pg_guard(pg); assert reason=="PG_MISCONFIGURED" and "secret" not in str(safe)
