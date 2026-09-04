from core.refresh import build_market_snapshot

if __name__=='__main__':
    # One broad cheap scan per weekday. Specialist/fundamental work is deferred
    # to the bounded opportunity-hunt shortlist.
    snap=build_market_snapshot(scan_limit=1700)
    print('snapshot rows:',len(snap['results']))
    print('generated:',snap['meta']['generated_at'])
