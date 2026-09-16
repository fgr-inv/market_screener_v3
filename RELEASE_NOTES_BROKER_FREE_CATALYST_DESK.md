# Broker-Free US Equities Catalyst Desk

This update turns the operating ideas from the desk playbook into deterministic product policy while preserving the existing multi-asset research architecture.

## Added

- Versioned `US_EQUITIES_CATALYST_DESK` mandate.
- Fresh primary-source catalyst gate for raised/reaffirmed guidance and signed/closed deals.
- Official thesis-kill detection for guidance cuts, terminated deals, and material legal/regulatory events.
- Fourteen-day full catalyst scan, explicit anti-chase gate, weekly maximum of two new virtual positions, and 70% starter sizing.
- Broker-free manual portfolio CSV import.
- Repository context, agent rules, operating playbook, and mandate tests.

## Removed

- Alpaca connector, credentials, provider status, and UI controls.
- Broker-specific import naming from the application navigation.

## Safety boundary

The desk remains research plus internal virtual simulation. It cannot access an external brokerage account, submit an order, or enable live trading.
