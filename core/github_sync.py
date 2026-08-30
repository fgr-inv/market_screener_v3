import base64
import os
from pathlib import Path
import requests


def _secret(name):
    value=os.getenv(name,'')
    if value: return value
    try:
        import streamlit as st
        return str(st.secrets.get(name,''))
    except Exception:
        return ''


def push_file(local_path, repo_path, message='update app data'):
    repo=_secret('GITHUB_REPO')
    token=_secret('GITHUB_PAT')
    if not repo or not token: return False,'GITHUB_REPO/GITHUB_PAT not configured'
    local=Path(local_path)
    if not local.exists(): return False,'local file missing'
    api=f'https://api.github.com/repos/{repo}/contents/{repo_path}'
    headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json'}
    sha=None
    try:
        r=requests.get(api,headers=headers,timeout=10)
        if r.status_code==200: sha=r.json().get('sha')
        payload={'message':message,'content':base64.b64encode(local.read_bytes()).decode('ascii')}
        if sha: payload['sha']=sha
        r=requests.put(api,headers=headers,json=payload,timeout=15)
        return (200<=r.status_code<300), (r.json().get('content',{}).get('html_url','') if r.content else '')
    except Exception as e:
        return False,str(e)
