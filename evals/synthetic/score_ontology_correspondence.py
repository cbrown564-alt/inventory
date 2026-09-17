#!/usr/bin/env python3
"""Offline Phase-1 test of canonical identity on existing describe records.

This deliberately does not call a model. It asks the first causal question:
if the current free-form names are mapped through the proposed ontology, how
much measured naming/membership instability disappears, and how much cannot be
mapped safely? It complements (does not replace) score_stability.py.
"""
from __future__ import annotations
from collections import Counter
from typing import Iterable
from homeinventory.ontology import canonicalize_name


def canonical_key(name: str) -> str | None:
    return canonicalize_name(name)


def multiset_stats(names_a: Iterable[str], names_b: Iterable[str]) -> dict:
    a_names=list(names_a); b_names=list(names_b)
    a=[canonical_key(n) for n in a_names]; b=[canonical_key(n) for n in b_names]
    known_a=Counter(x for x in a if x); known_b=Counter(x for x in b if x)
    both=sum((known_a & known_b).values()); either=sum((known_a | known_b).values())
    total=len(a)+len(b); unknown=sum(x is None for x in a)+sum(x is None for x in b)
    return {
        "canonical_agreement_pct": round(100*both/either,1) if either else 0.0,
        "canonical_membership_churn": sum((known_a-known_b).values())+sum((known_b-known_a).values()),
        "mapped_items": total-unknown, "total_items": total,
        "mapping_coverage_pct": round(100*(total-unknown)/total,1) if total else 0.0,
        "unknown_a": [n for n,k in zip(a_names,a) if k is None],
        "unknown_b": [n for n,k in zip(b_names,b) if k is None],
    }


def dangerous_collapses(names: Iterable[str]) -> dict[str,list[str]]:
    """Surface names collapsed to one type; review these before adoption."""
    grouped:dict[str,set[str]]={}
    for name in names:
        key=canonical_key(name)
        if key: grouped.setdefault(key,set()).add(name)
    return {k:sorted(v) for k,v in grouped.items() if len(v)>1}
