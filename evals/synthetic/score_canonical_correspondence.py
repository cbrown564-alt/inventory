#!/usr/bin/env python3
"""Score canonical correspondence on frozen cached describe outputs.

Repository-only R0/R1 instrument: no model or network calls. Unknown names are
not collapsed together; repeated items remain multisets.
"""
from __future__ import annotations
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from homeinventory.merge import _head_nouns
from homeinventory.ontology import ONTOLOGY_VERSION, canonicalize_name
from homeinventory.compare import _norm_name

SCHEMA_VERSION=1
DEFAULT_ROOT=Path("evals/fixtures/synthetic-room-eval")
DEFAULT_REPEAT=DEFAULT_ROOT/"outputs/repeat/antigravity-cli/gemini-3.5-flash-low/production-v1"
DEFAULT_DELTA=DEFAULT_ROOT/"outputs/delta/antigravity-cli/gemini-3.5-flash-low/production-v1"
DEFAULT_BASELINE=DEFAULT_ROOT/"reports/phase0-describe-stability-2026-08-06.json"

def _pct(n,d): return round(100.0*n/d,1) if d else 0.0
def _normalised(name): return frozenset(_head_nouns(name))
def _surface_key(name): return "surface:"+_norm_name(name)
def canonical_key(name):
    item_type=canonicalize_name(name)
    return "type:"+item_type if item_type else _surface_key(name)
def _agreement(names_a,names_b,key):
    a,b=Counter(key(n) for n in names_a),Counter(key(n) for n in names_b)
    both=sum((a&b).values()); either=sum((a|b).values())
    return {"both":both,"either":either,"agreement":_pct(both,either),"churn":sum((a-b).values())+sum((b-a).values())}
def _items(record):
    output=record.get("output") or record.get("response") or record
    return list(output.get("items") or [])
def _pair_id(path):
    for suffix in (".T0.json",".T1.json",".R2.json"):
        if path.name.endswith(suffix): return path.name[:-len(suffix)]
    raise ValueError(path.name)
def _load(path): return json.loads(path.read_text(encoding="utf-8"))
def _names(path): return [str(i.get("name") or "").strip() for i in _items(_load(path)) if str(i.get("name") or "").strip()]
def _base_file(delta_dir,pair_id):
    path=delta_dir/f"{pair_id}.T0.json"
    if not path.exists(): raise FileNotFoundError(path)
    return path

def pair_score(a_path,b_path):
    a,b=_names(a_path),_names(b_path); exact=_agreement(a,b,_norm_name); norm=_agreement(a,b,_normalised); canon=_agreement(a,b,canonical_key)
    ua=[n for n in a if canonicalize_name(n) is None]; ub=[n for n in b if canonicalize_name(n) is None]
    return {"pair_id":_pair_id(b_path),"files":{"a":str(a_path),"b":str(b_path)},"counts":{"items_a":len(a),"items_b":len(b),"mapped_a":len(a)-len(ua),"mapped_b":len(b)-len(ub)},"metrics":{"exact_agreement":exact["agreement"],"normalised_agreement":norm["agreement"],"canonical_agreement":canon["agreement"],"exact_churn":exact["churn"],"normalised_churn":norm["churn"],"canonical_churn":canon["churn"],"mapping_coverage_a":_pct(len(a)-len(ua),len(a)),"mapping_coverage_b":_pct(len(b)-len(ub),len(b))},"unknown":{"a":ua,"b":ub}}

def pool(pairs):
    totals=Counter()
    for p in pairs:
        a,b=_names(Path(p["files"]["a"])),_names(Path(p["files"]["b"]))
        for prefix,key in (("exact",_norm_name),("normalised",_normalised),("canonical",canonical_key)):
            m=_agreement(a,b,key); totals[prefix+"_both"]+=m["both"]; totals[prefix+"_either"]+=m["either"]; totals[prefix+"_churn"]+=m["churn"]
        totals["items_a"]+=len(a); totals["items_b"]+=len(b); totals["mapped_a"]+=sum(canonicalize_name(n) is not None for n in a); totals["mapped_b"]+=sum(canonicalize_name(n) is not None for n in b)
    ca=_pct(totals["canonical_both"],totals["canonical_either"]); na=_pct(totals["normalised_both"],totals["normalised_either"])
    return {"pairs":len(pairs),"counts":dict(totals),"metrics":{"exact_agreement":_pct(totals["exact_both"],totals["exact_either"]),"normalised_agreement":na,"canonical_agreement":ca,"canonical_agreement_gain_vs_normalised_pp":round(ca-na,1),"normalised_churn_per_room":round(totals["normalised_churn"]/len(pairs),2) if pairs else 0,"canonical_churn_per_room":round(totals["canonical_churn"]/len(pairs),2) if pairs else 0,"canonical_churn_reduction_pct":round(100*(totals["normalised_churn"]-totals["canonical_churn"])/totals["normalised_churn"],1) if totals["normalised_churn"] else 0,"mapping_coverage_a":_pct(totals["mapped_a"],totals["items_a"]),"mapping_coverage_b":_pct(totals["mapped_b"],totals["items_b"])}}

def audit_surfaces(paths):
    by_type=defaultdict(Counter); unknown=Counter()
    for path in paths:
        for name in _names(path):
            key=canonicalize_name(name)
            if key: by_type[key][name]+=1
            else: unknown[name]+=1
    return {"many_surface_collapses":{k:dict(v.most_common()) for k,v in sorted(by_type.items()) if len(v)>1},"unknown_surface_names":dict(unknown.most_common())}
def discover(repeat_dir,delta_dir):
    repeats=[]; deltas=[]
    for r2 in sorted(repeat_dir.glob("*.R2.json")):
        pid=_pair_id(r2); repeats.append((_base_file(delta_dir,pid),r2))
    for t1 in sorted(delta_dir.glob("*.T1.json")):
        pid=_pair_id(t1); deltas.append((_base_file(delta_dir,pid),t1))
    return repeats,deltas

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--repeat-dir",type=Path,default=DEFAULT_REPEAT); ap.add_argument("--delta-dir",type=Path,default=DEFAULT_DELTA); ap.add_argument("--baseline",type=Path,default=DEFAULT_BASELINE); ap.add_argument("--out",type=Path); args=ap.parse_args()
    repeats,deltas=discover(args.repeat_dir,args.delta_dir); rs=[pair_score(a,b) for a,b in repeats]; ds=[pair_score(a,b) for a,b in deltas]; baseline=_load(args.baseline) if args.baseline.exists() else None; all_paths=sorted({p for pair in repeats+deltas for p in pair})
    result={"schema_version":SCHEMA_VERSION,"record_type":"canonical_correspondence_counterfactual","ontology_version":ONTOLOGY_VERSION,"source_baseline":str(args.baseline),"frozen_inputs":{"repeat_pairs":len(repeats),"delta_pairs":len(deltas)},"repeat_control":{"pooled":pool(rs),"per_pair":rs},"delta_pairs":{"pooled":pool(ds),"per_pair":ds},"surface_audit":audit_surfaces(all_paths)}
    if baseline: result["phase0_reference"]={"repeat_normalised_agreement":baseline["instruments"]["repeat_describe_control"]["metrics"]["schedule_agreement_normalised"],"repeat_membership_churn_per_room":baseline["instruments"]["repeat_describe_control"]["metrics"]["membership_churn_per_room"]}
    text=json.dumps(result,indent=2,ensure_ascii=False)+"\n"
    if args.out: args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(text,encoding="utf-8")
    else: print(text)
    return 0
if __name__=="__main__": raise SystemExit(main())
