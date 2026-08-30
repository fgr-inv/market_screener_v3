from core.refresh import build_market_snapshot

if __name__=='__main__':
    snap=build_market_snapshot(scan_limit=220)
    print('snapshot rows:',len(snap['results']))
    print('generated:',snap['meta']['generated_at'])
