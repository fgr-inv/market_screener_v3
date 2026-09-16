"""Canonical ownership boundaries for the Investment Desk agent fleet."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    owns: str
    may_publish: bool=False
    may_execute: bool=False


AGENT_REGISTRY={spec.key:spec for spec in (
    AgentSpec('technical','Technical Signal','price structure, participation and entry timing'),
    AgentSpec('fundamental','Fundamental Analyst','financial quality, growth and valuation'),
    AgentSpec('news','News & Catalyst','new events, filings and primary-source confirmation'),
    AgentSpec('market','Market Regime & Sector','structured macro regime and sector rotation'),
    AgentSpec('portfolio','Portfolio & Risk','concentration, correlation and portfolio fit'),
    AgentSpec('verification','Verification','evidence validity, freshness and contradictions'),
    AgentSpec('cio','CIO / Chief of Staff','prioritization of already verified work'),
    AgentSpec('strategist','Market Strategist','long-form explanation from frozen evidence'),
    AgentSpec('journal','Journal & Process Review','outcomes, calibration and recurring mistakes'),
)}


def validate_agent_registry():
    assert len(AGENT_REGISTRY)==len(set(AGENT_REGISTRY))
    assert all(spec.owns and not spec.may_execute for spec in AGENT_REGISTRY.values())
    return True
