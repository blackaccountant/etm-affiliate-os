"""Run a guarded, evidence-producing qualification described by a JSON spec."""
from __future__ import annotations

import argparse, hashlib, json, os, platform, re, subprocess, sys, time, uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

VALID_KINDS = {"unit", "contract", "postgresql", "regression"}
VALID_MIGRATIONS = {"none", "new_revision", "historical"}

class SpecError(ValueError): pass

def relpath(root: Path, value: str) -> str:
    p = Path(value)
    if p.is_absolute() or ".." in p.parts: raise SpecError(f"unsafe repository path: {value}")
    resolved = (root / p).resolve()
    if root.resolve() not in (resolved, *resolved.parents): raise SpecError(f"path escapes repository: {value}")
    return resolved.relative_to(root.resolve()).as_posix()

def load_spec(root: Path, path: Path) -> dict:
    try: spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise SpecError(f"invalid JSON spec: {exc}") from exc
    for key in ("phase", "expected_branch", "expected_base_head", "candidate_manifest", "production_files", "test_files", "compile_targets", "required_alembic_revision", "migration_expectation", "test_suites", "default_timeout_seconds"):
        if key not in spec: raise SpecError(f"missing required field: {key}")
    if spec.get("format_version") != 1: raise SpecError("unsupported format_version")
    if not isinstance(spec["phase"], str) or not spec["phase"].strip(): raise SpecError("phase must be nonblank")
    if spec["migration_expectation"] not in VALID_MIGRATIONS: raise SpecError("invalid migration_expectation")
    if not isinstance(spec["default_timeout_seconds"], int) or spec["default_timeout_seconds"] <= 0: raise SpecError("invalid default_timeout_seconds")
    for field in ("candidate_manifest", "production_files", "test_files", "compile_targets"):
        if not isinstance(spec[field], list): raise SpecError(f"{field} must be a list")
        spec[field] = [relpath(root, x) for x in spec[field]]
    if len(set(spec["candidate_manifest"])) != len(spec["candidate_manifest"]): raise SpecError("duplicate candidate paths")
    candidates = set(spec["candidate_manifest"])
    if not set(spec["production_files"] + spec["test_files"]).issubset(candidates): raise SpecError("production/test paths must be candidates")
    for suite in spec["test_suites"]:
        if not isinstance(suite, dict) or suite.get("kind") not in VALID_KINDS: raise SpecError("invalid test kind")
        suite["path"] = relpath(root, suite.get("path", ""))
        if not (root / suite["path"]).is_file(): raise SpecError(f"missing test path: {suite['path']}")
        timeout = suite.get("timeout_seconds", spec["default_timeout_seconds"])
        if not isinstance(timeout, int) or timeout <= 0: raise SpecError("invalid timeout")
        suite["timeout_seconds"] = timeout
        pg = suite.get("postgresql")
        if suite["kind"] == "postgresql" and not isinstance(pg, dict): raise SpecError("PG suite requires postgresql guard")
        if pg is not None:
            required = {"url_env","role_env","required_role","expected_driver_prefix","expected_host","expected_port","expected_database","required_revision","fresh_database_required","freshness_attestation_env"}
            if not required.issubset(pg) or not isinstance(pg["expected_port"], int): raise SpecError("malformed PG metadata")
    if spec["migration_expectation"] == "none" and any(p.startswith("backend/alembic/versions/") for p in candidates): raise SpecError("migration file forbidden by migration_expectation=none")
    return spec

def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def run(argv, cwd, timeout):
    start=time.monotonic()
    p=subprocess.Popen(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    try:
        out, err=p.communicate(timeout=timeout)
        return {"command": argv, "exit_code":p.returncode, "stdout":out, "stderr":err, "duration_seconds":round(time.monotonic()-start,3), "timed_out":False}
    except subprocess.TimeoutExpired:
        if os.name == "nt": subprocess.run(["taskkill","/PID",str(p.pid),"/T","/F"], capture_output=True, text=True, shell=False)
        else: p.kill()
        out, err=p.communicate()
        return {"command":argv,"exit_code":None,"stdout":out or "","stderr":err or "","duration_seconds":round(time.monotonic()-start,3),"timed_out":True}
def git(root, *args): return run(["git",*args],root,30)
def lines(result): return [x for x in result["stdout"].splitlines() if x]
def hashes(root, paths): return {p: sha(root/p) if (root/p).is_file() else None for p in sorted(paths)}
def status(root):
    return lines(git(root,"status","--porcelain=v1") ), lines(git(root,"diff","--cached","--name-only"))
def changed_paths(root, entries):
    result=set(lines(git(root,"ls-files","--others","--exclude-standard")))
    for entry in entries:
        path=entry[3:]
        if not entry.startswith("?? "): result.add(path.replace("\\","/"))
    return result
def junit(path):
    try: root=ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc: raise SpecError(f"missing or malformed JUnit XML: {exc}")
    suites=[root] if root.tag=="testsuite" else root.findall(".//testsuite")
    totals={k:0 for k in ("collected","passed","failed","errors","skipped")}
    for s in suites:
        tests=int(s.attrib.get("tests",0)); totals["collected"]+=tests; totals["failed"]+=int(s.attrib.get("failures",0)); totals["errors"]+=int(s.attrib.get("errors",0)); totals["skipped"]+=int(s.attrib.get("skipped",0))
    totals["passed"]=totals["collected"]-totals["failed"]-totals["errors"]-totals["skipped"]; return totals
def pg_guard(pg):
    raw, role=os.getenv(pg["url_env"]),os.getenv(pg["role_env"])
    safe={"configured":bool(raw and role),"role_match":role==pg["required_role"],"freshness_attestation_present":bool(os.getenv(pg["freshness_attestation_env"]))}
    if not raw: return safe,"PG_NOT_CONFIGURED"
    u=urlparse(raw); safe.update(driver=u.scheme,host=u.hostname,port=u.port,database=u.path.lstrip("/"))
    expected=(u.scheme.startswith(pg["expected_driver_prefix"]) and u.hostname==pg["expected_host"] and u.port==pg["expected_port"] and u.path.lstrip("/")==pg["expected_database"] and safe["role_match"])
    return safe, None if expected and (not pg["fresh_database_required"] or safe["freshness_attestation_present"]) else "PG_MISCONFIGURED"

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--evidence-dir"); ap.add_argument("--timeout-seconds",type=int); ap.add_argument("--no-pg",action="store_true"); ns=ap.parse_args(argv)
    root=Path(git(Path.cwd(),"rev-parse","--show-toplevel")["stdout"].strip()).resolve()
    spec_path=Path(ns.spec).resolve(); spec=load_spec(root,spec_path); backend=root/"backend"; run_id=uuid.uuid4().hex; evidence_dir=Path(ns.evidence_dir).resolve() if ns.evidence_dir else backend/".qualification-evidence"/spec["phase"]/run_id; evidence_dir.mkdir(parents=True,exist_ok=True)
    initial_status, staged=status(root); candidate=set(spec["candidate_manifest"]); dirty=changed_paths(root,initial_status)
    evidence={"evidence_format_version":1,"phase":spec["phase"],"timestamp_utc":datetime.now(timezone.utc).isoformat(),"run_id":run_id,"spec_path":spec_path.relative_to(root).as_posix(),"spec_sha256":sha(spec_path),"runner_path":Path(__file__).resolve().relative_to(root).as_posix(),"runner_sha256":sha(Path(__file__).resolve()),"python_executable":sys.executable,"python_version":sys.version,"branch":git(root,"branch","--show-current")["stdout"].strip(),"initial_head":git(root,"rev-parse","HEAD")["stdout"].strip(),"upstream":git(root,"rev-parse","@{upstream}")["stdout"].strip(),"ahead_behind":git(root,"rev-list","--left-right","--count","@{upstream}...HEAD")["stdout"].strip(),"candidate_manifest":sorted(candidate),"initial_candidate_hashes":hashes(root,candidate),"working_tree_initial":initial_status,"staged_initial":staged,"python_platform":platform.platform(),"test_suites":[],"failure_classifications":[],"unresolved_defects":[]}
    fail=[]; incomplete=[]
    if evidence["branch"]!=spec["expected_branch"] or evidence["initial_head"]!=spec["expected_base_head"]: fail.append("REPOSITORY_STATE")
    if staged: fail.append("REPOSITORY_STATE")
    if not dirty.issubset(candidate): fail.append("REPOSITORY_STATE")
    comp=[]
    for target in spec["compile_targets"]:
        r=run([sys.executable,"-m","py_compile",target],root,ns.timeout_seconds or spec["default_timeout_seconds"]); comp.append({"path":target,**r});
        if r["exit_code"]: fail.append("COMPILE")
    evidence["py_compile"]=comp; diff=git(root,"diff","--check"); evidence["git_diff_check"]=diff
    if diff["exit_code"]: fail.append("REPOSITORY_STATE")
    alembic=run([sys.executable,"-m","alembic","heads"],backend,ns.timeout_seconds or spec["default_timeout_seconds"]); heads=[x.strip().split()[0] for x in lines(alembic) if "(head)" in x]; ids=[]
    for p in (backend/"alembic"/"versions").glob("*.py"):
        m=re.search(r'^revision\s*=\s*["\']([^"\']+)',p.read_text(encoding="utf-8"),re.M)
        if m: ids.append(m.group(1))
    evidence["alembic"]={"observed_heads":heads,"required_revision":spec["required_alembic_revision"],"duplicate_revision_count":len(ids)-len(set(ids)),"command":alembic["command"],"exit_code":alembic["exit_code"]}
    if alembic["exit_code"] or heads != [spec["required_alembic_revision"]] or len(ids)!=len(set(ids)): fail.append("ALEMBIC")
    for i,s in enumerate(spec["test_suites"]):
        result={"name":s["name"],"kind":s["kind"],"path":s["path"]}; pg=s.get("postgresql")
        if pg:
            result["postgresql"],reason=pg_guard(pg)
            if ns.no_pg: reason="PG_NOT_CONFIGURED"
            if reason: result.update(status="INCOMPLETE",reason=reason); incomplete.append(reason); evidence["test_suites"].append(result); continue
        timeout=ns.timeout_seconds or s["timeout_seconds"]; suite_path=str(Path(s["path"]).relative_to("backend")); collect=run([sys.executable,"-m","pytest","-p","no:cacheprovider","--collect-only","-q",suite_path],backend,timeout); xml=evidence_dir/f"suite-{i}.xml"; base=evidence_dir/f"basetemp-{i}"; execute=run([sys.executable,"-m","pytest","-p","no:cacheprovider",suite_path,f"--junitxml={xml}",f"--basetemp={base}"],backend,timeout)
        result.update(collection_command=collect["command"],collection_exit_code=collect["exit_code"],execution_command=execute["command"],execution_exit_code=execute["exit_code"],duration_seconds=execute["duration_seconds"],timed_out=execute["timed_out"])
        try: result.update(junit(xml))
        except SpecError as exc: result["junit_error"]=str(exc); fail.append("RUNNER_INTERNAL")
        if collect["exit_code"] or execute["timed_out"]: fail.append("PYTEST_COLLECTION" if collect["exit_code"] else "TIMEOUT")
        elif execute["exit_code"]: fail.append("PYTEST_TEST")
        evidence["test_suites"].append(result)
    final_status, final_staged=status(root); evidence.update(final_head=git(root,"rev-parse","HEAD")["stdout"].strip(),working_tree_final=final_status,staged_final=final_staged,final_candidate_hashes=hashes(root,candidate))
    evidence["post_qualification_drift"]=(evidence["initial_head"]!=evidence["final_head"] or evidence["initial_candidate_hashes"]!=evidence["final_candidate_hashes"] or final_staged or not changed_paths(root,final_status).issubset(candidate))
    if evidence["post_qualification_drift"]: fail.append("EVIDENCE_INTEGRITY")
    evidence["failure_classifications"]=sorted(set(fail+incomplete)); evidence["overall_status"]="FAIL" if fail else "INCOMPLETE" if incomplete else "PASS"; evidence["unresolved_defects"]=evidence["failure_classifications"]
    output=evidence_dir/"evidence.json"; output.write_text(json.dumps(evidence,indent=2),encoding="utf-8"); print(f"{evidence['overall_status']} evidence={output}"); return 0 if evidence["overall_status"]=="PASS" else 1
if __name__ == "__main__": raise SystemExit(main())
