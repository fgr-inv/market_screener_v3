"""Canonical ownership boundaries for the Investment Desk agent fleet."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    owns: str
    reports_to: str='verification'
    tools: tuple[str,...]=()
    may_publish: bool=False
    may_execute: bool=False
    may_edit_thesis: bool=False


AGENT_REGISTRY={spec.key:spec for spec in (
    AgentSpec('technical','Technical Signal','price structure, participation and entry timing',tools=('price_snapshots','indicators')),
    AgentSpec('fundamental','Fundamental Analyst','financial quality, growth and valuation',tools=('fundamental_cache','official_filings')),
    AgentSpec('news','News & Catalyst','new events, filings and primary-source confirmation',tools=('news_cache','official_filings')),
    AgentSpec('market','Market Regime & Sector','structured macro regime and sector rotation',tools=('macro_snapshots','sector_snapshots')),
    AgentSpec('portfolio','Portfolio & Risk','concentration, correlation and portfolio fit',tools=('portfolio_snapshot','price_snapshots')),
    AgentSpec('verification','Verification','evidence validity, freshness and contradictions',reports_to='cio',tools=('research_packet','agent_handoffs')),
    AgentSpec('cio','CIO / Chief of Staff','prioritization of already verified work',reports_to='user',tools=('verified_handoffs','thesis_memory')),
    AgentSpec('strategist','Market Strategist','long-form explanation from frozen evidence',reports_to='cio',tools=('research_packet','verified_handoffs')),
    AgentSpec('journal','Journal & Process Review','outcomes, calibration and recurring mistakes',reports_to='user',tools=('shadow_outcomes','agent_audit')),
)}


def validate_agent_registry():
    assert len(AGENT_REGISTRY)==len(set(AGENT_REGISTRY))
    assert all(spec.owns and spec.reports_to and not spec.may_execute for spec in AGENT_REGISTRY.values())
    assert all(not spec.may_edit_thesis for spec in AGENT_REGISTRY.values())
    return True
