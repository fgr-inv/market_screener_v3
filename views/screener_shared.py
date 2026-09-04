def render_screener(forced_mode=None, page_title=None, page_subtitle=None):
    import numpy as np
    import pandas as pd
    import streamlit as st
    import time

    from core.market_data import (
        load_universe, build_asset_universe, get_asset_presets,
        download_prices, get_market_symbols, get_sector_etfs, get_macro_symbols, classify_symbol,
    )
    from core.indicators import enrich_indicators
    from core.scoring import analyze_symbol, sector_strength_entry
    from core.asset_models import analyze_asset, normalize_asset_type, effective_asset_type, suggested_history_period
    from core.asset_fundamentals import get_asset_context, equity_context_score
    from core.equity_sector_model import sector_fundamental_score
    from core.professional_equity_engine import professional_equity_snapshot, add_professional_peer_valuation_scores
    from core.professional_research_engine import scenario_valuation, peer_benchmark_snapshot
    from core.financial_forensics import financial_forensics
    from core.institutional_valuation import valuation_workstation
    from core.macro_regime_engine import macro_regime
    from core.economic_data import institutional_macro_snapshot
    from core.macro import sector_macro_score
    from core.opportunity import normalize_sector, add_cross_sectional_metrics, attach_scores
    from core.relative_strength import add_multi_horizon_rs
    from core.valuation import standalone_valuation_score, add_peer_valuation_scores
    from core.confidence import confidence_score
    from core.data_coverage import equity_data_coverage, asset_data_coverage
    from core.storage import save_score_snapshot, save_latest_snapshot
    from core.audit import append_score_audit
    from core.ui import hero, section_note
    from core.screener_enrichment import fetch_deep_bundles, clear_deep_cache
    from core.access_control import current_user, require_feature, require_quota, record_usage, limit_value, require_api_budget, require_job_slot, end_job

    _user=current_user()
    _feature_map={'Técnico':'technical_screener','Fundamental':'fundamental_screener','Combinado':'combined_screener'}
    _page_feature=_feature_map.get(forced_mode)
    if _page_feature and not require_feature(_page_feature, f'{forced_mode} Screener', _user):
        st.info('Podés seguir usando las funciones incluidas en tu plan desde las otras páginas.')
        st.stop()

    hero(
        page_title or 'Professional Screener',
        page_subtitle or 'Modelos separados por activo: equities, índices/ETFs, cripto, commodities, renta fija/tasas y FX.',
        'Multi-Factor Ranking',
    )

    with st.sidebar:
        st.header('Universo')
        asset_type=st.selectbox('Tipo de activo',['Acciones','ETFs','Índices','Cripto','Commodities','Bonos / Tasas','Forex','Personalizado'])
        custom=''; universe_name=None; preset=None
        if asset_type=='Acciones':
            universe_name=st.selectbox('Mercado',['US Expanded Liquid','S&P 500','Nasdaq 100',
                                                   'S&P MidCap 400','S&P SmallCap 600','Fallback líquido'])
        elif asset_type=='Personalizado':
            custom=st.text_area('Símbolos','META,NVDA,MU,GEV,CAVA,LMT,RTX',height=100)
        else:
            presets=get_asset_presets().get(asset_type,{})
            preset=st.selectbox('Universo',list(presets.keys()))
            if st.checkbox('Editar símbolos manualmente'):
                custom=st.text_area('Símbolos',','.join(presets[preset]),height=100)

        st.header('Filtros')
        _max_assets=int(limit_value('max_screener_assets',_user,500) or 500)
        max_names=st.slider('Máx. activos',10,_max_assets,min(200,_max_assets),10)
        st.caption(f"Plan {_user['plan']} · máximo {_max_assets} activos")
        min_prelim=st.slider('Setup preliminar mínimo',0,100,55)
        scanner=st.selectbox('Scanner',['Todas','Uptrend Pullback','EMA62/79 Buy Zone','200-Day Bounce','Breakout / Base','Extended / Trim'])

        st.header('Tipo de análisis')
        if asset_type=='Acciones':
            if forced_mode in {'Técnico','Fundamental','Combinado'}:
                analysis_mode=forced_mode
                st.info(f'Modo fijo de esta página: {analysis_mode}')
            else:
                analysis_mode=st.selectbox('Análisis',['Técnico','Fundamental','Combinado'],index=2,
                    help='Técnico no llama SEC/FMP/analyst. Fundamental y Combinado enriquecen solo las mejores candidatas.')
            _depths=list(limit_value('allowed_depths',_user,('Rápido',)) or ('Rápido',))
            depth_mode=st.selectbox('Profundidad',_depths,index=min(1,len(_depths)-1),
                help='La profundidad disponible depende del plan. En Fundamental/Combinado también cambia cuántas candidatas se enriquecen.')
            enrich_forward=analysis_mode in {'Fundamental','Combinado'}
            mode_default={'Rápido':15,'Balanceado':25,'Profundo':50}[depth_mode]
            if enrich_forward:
                st.caption('Primero se hace un filtro local de mercado; SEC/FMP/Yahoo fundamentals solo se consultan para las mejores candidatas.')
                _deep_cap=int(limit_value('max_deep_candidates',_user,0) or 0)
                if _deep_cap < 5:
                    st.error('Tu plan no incluye enriquecimiento profundo para este screener.'); st.stop()
                top_n=st.slider('Candidatas a enriquecer',5,_deep_cap,min(mode_default,_deep_cap),5)
                _worker_cap=int(limit_value('max_workers',_user,1) or 1)
                max_workers=st.slider('Consultas paralelas',1,_worker_cap,min(4,_worker_cap),1,help='Además del límite del plan, todas las llamadas pasan por protección global de proveedores.')
                force_refresh=st.checkbox('Forzar actualización de datos profundos',value=False,help='Ignora el caché de fundamentals/analyst/event. Usalo solo cuando necesites datos frescos.')
                if st.button('🧹 Limpiar caché profundo',width='stretch'):
                    n=clear_deep_cache(); st.success(f'Caché profundo limpiado: {n} archivos.')
            else:
                top_n=0; max_workers=1; force_refresh=False
                st.success('Modo Técnico: SEC, FMP, fundamentals, revisions, DCF y escenarios están desactivados. Consumo externo mínimo.')
        else:
            analysis_mode='Técnico'; depth_mode='Balanceado'; enrich_forward=False
            top_n=0; max_workers=1; force_refresh=False
        run=st.button('🔎 Escanear',type='primary',width='stretch')

    if run:
        _run_feature=_feature_map.get(analysis_mode,'technical_screener')
        if not require_quota(_run_feature, f'{analysis_mode} Screener', _user):
            st.stop()
        if not require_api_budget(_run_feature,_user,cache_hit=False):
            st.stop()
        _job_token=require_job_slot(_user)
        if not _job_token:
            st.stop()
        scan_started=time.perf_counter()
        stage_times={}
        if asset_type=='Acciones':
            universe_df=load_universe(universe_name)
        elif asset_type=='Personalizado':
            universe_df=build_asset_universe('Personalizado',custom_text=custom)
        else:
            if custom.strip():
                universe_df=build_asset_universe('Personalizado',custom_text=custom); universe_df['Sector']=asset_type
            else:
                universe_df=build_asset_universe(asset_type,preset=preset)

        universe_df=universe_df.drop_duplicates('Ticker').head(max_names).copy()
        ticks=universe_df['Ticker'].tolist()
        symbols=list(dict.fromkeys(ticks+get_market_symbols()+list(get_sector_etfs().values())+list(get_macro_symbols().values())))

        with st.status('Ejecutando screener...',expanded=True) as status:
            st.write('1/5 Descargando precios...')
            scan_period=('5y' if asset_type=='Acciones' and depth_mode=='Profundo' else '2y' if asset_type=='Acciones' and depth_mode=='Balanceado' else '1y' if asset_type=='Acciones' else suggested_history_period(asset_type))
            _t=time.perf_counter(); pm=download_prices(symbols,period=scan_period); spy=pm.get('SPY'); stage_times['prices']=time.perf_counter()-_t
            rows=[]; histories={}
            st.write('2/5 Calculando técnica, entrada y riesgo...')
            _t=time.perf_counter()
            for t in ticks:
                try:
                    raw=pm.get(t)
                    if raw is None or raw.empty: continue
                    h=enrich_indicators(raw)
                    if len(h.dropna(subset=['SMA200']))<20: continue
                    sector=universe_df.loc[universe_df['Ticker']==t,'Sector'].iloc[0]
                    detected_type=classify_symbol(t) if asset_type=='Personalizado' else normalize_asset_type(asset_type)
                    row_type=effective_asset_type(t,detected_type)
                    r=analyze_asset(t,h,spy,sector,row_type,technical_depth=depth_mode)
                    r['Sector']=normalize_sector(r['Sector']); r['Asset_Type']=row_type
                    if 'Universe Source' in universe_df:
                        r['Universe Source']=universe_df.loc[universe_df['Ticker']==t,'Universe Source'].iloc[0]
                    rows.append(r); histories[t]=h
                except Exception: pass

            stage_times['technical']=time.perf_counter()-_t
            results=pd.DataFrame(rows)
            if results.empty:
                end_job(_job_token,_user)
                st.error('No hubo resultados.'); st.stop()
            results=add_cross_sectional_metrics(results)
            results=add_multi_horizon_rs(results,histories,pm,get_sector_etfs())

            st.write('3/5 Calculando macro y sectores...')
            _t=time.perf_counter()
            macro=st.session_state.macro_snapshot
            if macro is None:
                macro=institutional_macro_snapshot(pm,breadth_level=50)
            macro_v9=macro_regime(macro)
            strength_map={}
            for sec,etf in get_sector_etfs().items():
                try:
                    sr=analyze_symbol(etf,enrich_indicators(pm[etf]),spy,sec)
                    strength_map[sec]=sector_strength_entry(sr)[0]
                except Exception: pass
            results['Sector_Score']=np.nan
            results['Macro_Fit']=np.nan
            results['Asset_Context_Score']=np.nan
            results['Framework']=''
            for idx, rr in results.iterrows():
                typ=normalize_asset_type(rr.get('Asset_Type',asset_type))
                if typ=='Acción':
                    results.at[idx,'Sector_Score']=strength_map.get(normalize_sector(rr.get('Sector')),50)
                    results.at[idx,'Macro_Fit']=sector_macro_score(normalize_sector(rr.get('Sector')),macro)
                    # Equity context is market context, separate from fundamentals and local-only.
                    _ctx=equity_context_score(results.loc[idx])
                    results.at[idx,'Asset_Context_Score']=_ctx.get('Asset_Context_Score',np.nan)
                    results.at[idx,'Framework']=_ctx.get('Framework','')
                else:
                    try:
                        ctx=get_asset_context(rr['Ticker'],typ,pm,macro)
                        results.at[idx,'Asset_Context_Score']=ctx.get('Asset_Context_Score',np.nan)
                        results.at[idx,'Macro_Fit']=ctx.get('Asset_Context_Score',np.nan)
                        results.at[idx,'Framework']=ctx.get('Framework',rr.get('Professional_Framework',''))
                        dc=asset_data_coverage(rr['Ticker'],typ,ctx,macro)
                        results.at[idx,'Data_Coverage_Score']=dc.get('Data_Coverage_Score',np.nan)
                        results.at[idx,'Data_Coverage_Label']=dc.get('Data_Coverage_Label','N/D')
                    except Exception:
                        results.at[idx,'Macro_Fit']=50
            results['Quality_Score']=np.nan; results['Revision_Score']=np.nan; results['Valuation_Score']=np.nan; results['Event_Risk']='N/D'; results['Confidence_Score']=np.nan; results['Data_Coverage_Score']=np.nan; results['Data_Coverage_Label']='N/D'
            results['Analysis_Mode']=analysis_mode; results['Depth_Mode']=depth_mode
            results['Macro_Regime']=macro_v9.get('Macro_Regime','N/D'); results['Global_Liquidity_Proxy_Score']=macro_v9.get('Global_Liquidity_Proxy_Score',np.nan)
            for _c in ['Earnings_Quality_Score','Financial_Resilience_Score','Capital_Allocation_Score','Reverse_DCF_Implied_Growth_%','DCF_Fair_Value_Upside_%','Management_Execution_Score','Revision_Velocity_%','Target_Dispersion_%']:
                results[_c]=np.nan
            results=attach_scores(results)
            stage_times['macro_sector']=time.perf_counter()-_t

            if asset_type=='Acciones' and enrich_forward:
                candidates=(results[results['Preliminary_Score']>=min_prelim].sort_values(['Preliminary_Score','Trend_Score'],ascending=False).head(top_n))
                st.write(f'4/5 Análisis profundo para {len(candidates)} candidatas (paralelo + caché)...')
                _t=time.perf_counter()
                candidate_tickers=candidates['Ticker'].tolist()
                bundles, deep_diag=fetch_deep_bundles(candidate_tickers,max_workers=max_workers,force_refresh=force_refresh)
                stage_times['deep_network']=time.perf_counter()-_t
                st.write(f"   ↳ {deep_diag['tickers']} tickers · {deep_diag['workers']} workers · {deep_diag['elapsed_seconds']:.1f}s · {deep_diag['cache_sections']} secciones desde caché")
                _t_local=time.perf_counter()
                # Provider/stage failures are isolated. Network calls were fetched in parallel above;
                # everything below is local scoring/model work.
                for t in candidate_tickers:
                    mask=results['Ticker']==t
                    bundle=bundles.get(t,{})
                    issues=list(bundle.get('Fetch_Issues',[]))
                    f=bundle.get('fundamentals') or {}
                    a=bundle.get('analyst') or {'EPS_Revision_Score':50,'Revision_Direction':'NEUTRAL'}
                    e=bundle.get('event') or {'risk':'UNKNOWN','days_to_earnings':None}
                    if isinstance(f,dict):
                        st.session_state.fundamentals_cache[t]=f
                    results.loc[mask,'Fundamentals_Status']='OK' if f and not f.get('error') else 'PARTIAL' if f else 'ERROR'
                    results.loc[mask,'Fundamentals_Source']=f.get('Fundamentals_Source',f.get('Premium_Fundamentals_Source','NONE')) if isinstance(f,dict) else 'NONE'
                    results.loc[mask,'Deep_Cache_Hits']=', '.join(bundle.get('Cache_Hits',[]))
                    results.loc[mask,'Deep_Fetch_Seconds']=bundle.get('Fetch_Seconds',np.nan)
                    if isinstance(f,dict) and f.get('Provider_Issues'):
                        issues.extend([str(x) for x in f.get('Provider_Issues',[])])

                    # Quality/valuation are independent from analyst/event endpoints.
                    eq={}
                    if f:
                        try:
                            sec=normalize_sector(results.loc[mask,'Sector'].iloc[0])
                            eq=professional_equity_snapshot(f,sec,f.get('Industry',''),t)
                            results.loc[mask,'Industry']=f.get('Industry','Unknown')
                            results.loc[mask,'Equity_Model']=eq.get('Equity_Model','General Equity')
                            results.loc[mask,'Equity_Model_Key']=eq.get('Equity_Model_Key','generic')
                            results.loc[mask,'Peer_Group']=eq.get('Peer_Group','Same-industry peers')
                            q=eq.get('Quality_Score',np.nan)
                            if pd.isna(q) and f.get('Fundamentals_Available',False):
                                q=f.get('Fundamental_Score',np.nan)
                            results.loc[mask,'Quality_Score']=q
                            results.loc[mask,'Fundamental_Coverage_%']=eq.get('Fundamental_Coverage_%',0)
                            results.loc[mask,'Valuation_Coverage_%']=eq.get('Valuation_Coverage_%',0)
                            results.loc[mask,'Specialist_KPI_Coverage_%']=eq.get('Specialist_KPI_Coverage_%',0)
                            results.loc[mask,'Missing_Specialist_KPIs']=', '.join(eq.get('Missing_Specialist_KPIs',[]))
                            dc=equity_data_coverage(f,sec,f.get('Industry',''),t)
                            results.loc[mask,'Data_Coverage_Score']=dc.get('Data_Coverage_Score',np.nan)
                            results.loc[mask,'Data_Coverage_Label']=dc.get('Data_Coverage_Label','N/D')
                            results.loc[mask,'Missing_Critical_Data']=', '.join(dc.get('Missing_Critical_Data',[]))
                            for col in ['Forward_PE','EV_EBITDA','Price_to_Book','Price_to_Sales','EV_Revenue','FCF_Yield','Revenue_Growth','Earnings_Growth']:
                                results.loc[mask,col]=f.get(col,np.nan)
                            val=eq.get('Valuation_Score',np.nan)
                            if pd.isna(val):
                                try:
                                    val=standalone_valuation_score(f)
                                except Exception:
                                    val=np.nan
                            results.loc[mask,'Valuation_Score']=val
                            results.loc[mask,'Equity_Model_Status']='OK'
                        except Exception as exc:
                            issues.append(f'equity_model:{type(exc).__name__}')
                            results.loc[mask,'Equity_Model_Status']='ERROR'
                            # Minimum observed-data quality fallback; never invent a neutral if no data exists.
                            if f.get('Fundamentals_Available',False) and pd.isna(results.loc[mask,'Quality_Score'].iloc[0]) and pd.notna(f.get('Fundamental_Score',np.nan)):
                                results.loc[mask,'Quality_Score']=f.get('Fundamental_Score')
                            if pd.isna(results.loc[mask,'Valuation_Score'].iloc[0]):
                                try: results.loc[mask,'Valuation_Score']=standalone_valuation_score(f)
                                except Exception: pass

                        try:
                            ff=financial_forensics(f)
                            results.loc[mask,'Earnings_Quality_Score']=ff.get('Earnings_Quality_Score',np.nan)
                            results.loc[mask,'Financial_Resilience_Score']=ff.get('Financial_Resilience_Score',np.nan)
                            results.loc[mask,'Capital_Allocation_Score']=ff.get('Capital_Allocation_Score',np.nan)
                        except Exception as exc:
                            issues.append(f'forensics:{type(exc).__name__}')
                        try:
                            vw=valuation_workstation(f,eq.get('Equity_Model_Key','generic'))
                            results.loc[mask,'Reverse_DCF_Implied_Growth_%']=vw.get('Reverse_DCF',{}).get('Implied_FCF_Growth_%',np.nan)
                            results.loc[mask,'DCF_Fair_Value_Upside_%']=vw.get('DCF',{}).get('Fair_Value_Upside_%',np.nan)
                        except Exception as exc:
                            issues.append(f'dcf:{type(exc).__name__}')

                    # Analyst revisions always get their own attempt. The analyst engine's
                    # evidence-poor fallback is score 50 / NEUTRAL, so the column should not
                    # stay None just because Yahoo analyst tables are unavailable.
                    try:
                        rev=a.get('EPS_Revision_Score',50) if isinstance(a,dict) else 50
                        if pd.isna(rev): rev=50
                        results.loc[mask,'Revision_Score']=rev
                        results.loc[mask,'Revision_Direction']=a.get('Revision_Direction','NEUTRAL') if isinstance(a,dict) else 'NEUTRAL'
                        results.loc[mask,'Target_Upside_%']=a.get('Price_Target_Upside_%',np.nan) if isinstance(a,dict) else np.nan
                        results.loc[mask,'Management_Execution_Score']=a.get('Management_Execution_Score',np.nan) if isinstance(a,dict) else np.nan
                        results.loc[mask,'Revision_Velocity_%']=a.get('Revision_Velocity_%',np.nan) if isinstance(a,dict) else np.nan
                        results.loc[mask,'Target_Dispersion_%']=a.get('Target_Dispersion_%',np.nan) if isinstance(a,dict) else np.nan
                        ac=a.get('Analyst_Count',np.nan) if isinstance(a,dict) else np.nan
                        results.loc[mask,'Analyst_Status']='OK' if rev!=50 or pd.notna(ac) else 'LIMITED'
                    except Exception as exc:
                        issues.append(f'analyst_local:{type(exc).__name__}')
                        results.loc[mask,'Revision_Score']=50
                        results.loc[mask,'Revision_Direction']='NEUTRAL'
                        results.loc[mask,'Analyst_Status']='ERROR/FALLBACK'

                    try:
                        results.loc[mask,'Event_Risk']=e.get('risk','UNKNOWN') if isinstance(e,dict) else 'UNKNOWN'
                        results.loc[mask,'Days_to_Earnings']=e.get('days_to_earnings',np.nan) if isinstance(e,dict) else np.nan
                        results.loc[mask,'Event_Status']='OK' if isinstance(e,dict) and e else 'LIMITED'
                    except Exception as exc:
                        issues.append(f'event_local:{type(exc).__name__}')
                        results.loc[mask,'Event_Status']='ERROR'

                    try:
                        row=results.loc[mask].iloc[0]
                        conf,_=confidence_score(row,fundamentals=f if f and not f.get('error') else None,macro=macro)
                        results.loc[mask,'Confidence_Score']=conf
                    except Exception as exc:
                        issues.append(f'confidence:{type(exc).__name__}')

                    try:
                        if f and not f.get('error'):
                            row=results.loc[mask].iloc[0]
                            scen=scenario_valuation(row,f,a,{})
                            results.loc[mask,'Bear_Case_Price']=scen.get('Bear_Price',np.nan)
                            results.loc[mask,'Base_Case_Price']=scen.get('Base_Price',np.nan)
                            results.loc[mask,'Bull_Case_Price']=scen.get('Bull_Price',np.nan)
                            results.loc[mask,'Scenario_Expected_Return_%']=scen.get('Expected_Return_%',np.nan)
                            results.loc[mask,'Scenario_Coverage_%']=scen.get('Scenario_Coverage_%',np.nan)
                    except Exception as exc:
                        issues.append(f'scenario:{type(exc).__name__}')

                    results.loc[mask,'Enrichment_Issues']=' | '.join(dict.fromkeys(issues))
                    qv=pd.to_numeric(results.loc[mask,'Quality_Score'],errors='coerce').iloc[0]
                    rv=pd.to_numeric(results.loc[mask,'Revision_Score'],errors='coerce').iloc[0]
                    results.loc[mask,'Enrichment_Status']='OK' if pd.notna(qv) and pd.notna(rv) else 'PARTIAL'
                stage_times['deep_local_models']=time.perf_counter()-_t_local

            # Final resilience pass: professional equity rows must not lose the entire
            # enrichment layer because one optional provider/stage returned no data.
            if asset_type=='Acciones' and enrich_forward:
                candidate_set=set(candidates['Ticker'].tolist()) if 'candidates' in locals() else set()
                for idx in results.index:
                    if results.at[idx,'Ticker'] not in candidate_set:
                        continue
                    if pd.isna(results.at[idx,'Revision_Score']):
                        results.at[idx,'Revision_Score']=50
                        results.at[idx,'Revision_Direction']='NEUTRAL'
                    # If the professional model could not score quality but the resilient
                    # fundamental layer produced observed inputs, use its observed-data score.
                    if pd.isna(results.at[idx,'Quality_Score']):
                        ft=st.session_state.fundamentals_cache.get(results.at[idx,'Ticker'],{})
                        if isinstance(ft,dict) and ft.get('Fundamentals_Available') and pd.notna(ft.get('Fundamental_Score',np.nan)):
                            results.at[idx,'Quality_Score']=ft.get('Fundamental_Score')
                    if pd.isna(results.at[idx,'Valuation_Score']):
                        ft=st.session_state.fundamentals_cache.get(results.at[idx,'Ticker'],{})
                        if isinstance(ft,dict):
                            try:
                                vv=standalone_valuation_score(ft)
                                if pd.notna(vv): results.at[idx,'Valuation_Score']=vv
                            except Exception:
                                pass

            results=add_peer_valuation_scores(results)
            results=add_professional_peer_valuation_scores(results)
            results['Peer_Rank_Score']=np.nan
            results['Peer_Rank_Source']='UNAVAILABLE'
            results['Peer_Rank_Peer_Count']=0
            if 'Equity_Model_Key' in results.columns:
                for idx,pr in results.iterrows():
                    try:
                        _peer=peer_benchmark_snapshot(pr,results)
                        results.at[idx,'Peer_Rank_Score']=_peer.get('Peer_Rank_Score',np.nan)
                        results.at[idx,'Peer_Rank_Source']=_peer.get('Peer_Rank_Source','UNAVAILABLE')
                        results.at[idx,'Peer_Rank_Peer_Count']=_peer.get('Peer_Rank_Peer_Count',_peer.get('Peer_Count',0))
                    except Exception:
                        pass

            # Confidence for rows not enriched.
            for idx,r in results.iterrows():
                if pd.isna(r.get('Confidence_Score')):
                    results.at[idx,'Confidence_Score']=confidence_score(r,macro=macro)[0]

            st.write('5/5 Recalculando ranking y guardando historial...')
            _t=time.perf_counter()
            results=attach_scores(results)
            # Persist both the generic latest scan and the page-specific result set.
            # Specialized screener pages read scan_results_tecnico / fundamental / combinado;
            # without this assignment a completed scan looked empty immediately afterwards.
            _mode_key=str(analysis_mode).lower().replace('é','e')
            st.session_state.scan_results=results
            st.session_state[f'scan_results_{_mode_key}']=results.copy()
            record_usage(_run_feature, units=1, cache_hit=False, metadata={'analysis_mode':analysis_mode,'assets':len(ticks),'deep_candidates':int(top_n or 0)}, user=_user)
            end_job(_job_token,_user)
            st.session_state.scan_histories=histories
            st.session_state.scan_price_map=pm; st.session_state.scan_universe_df=universe_df
            save_score_snapshot(results,asset_type)
            save_latest_snapshot(results,'latest_manual_screener')
            for _, audit_row in results.sort_values('Preliminary_Score',ascending=False).head(50).iterrows():
                try: append_score_audit(audit_row.to_dict(), reason='manual_screener')
                except Exception: pass
            stage_times['save_finalize']=time.perf_counter()-_t
            total_seconds=time.perf_counter()-scan_started
            st.session_state.screener_timing={'total_seconds':round(total_seconds,2),**{k:round(v,2) for k,v in stage_times.items()}}
            status.update(label=f'Screener terminado en {total_seconds:.1f}s',state='complete',expanded=False)

    _display_mode=(forced_mode or analysis_mode or 'Técnico').lower().replace('é','e')
    _stored=st.session_state.get(f'scan_results_{_display_mode}')
    if _stored is None:
        st.info('Configurá el universo y presioná Escanear.'); st.stop()

    results=_stored.copy()
    if 'Preliminary_Score' not in results:
        st.warning('Los resultados en memoria son de una versión anterior. Volvé a ejecutar el screener.')
        st.stop()
    filtered=results[results['Preliminary_Score']>=min_prelim].copy()
    if scanner!='Todas':
        cmap={'Uptrend Pullback':'Scan_Uptrend_Pullback','EMA62/79 Buy Zone':'Scan_EMA_Buy_Zone','200-Day Bounce':'Scan_200D_Bounce','Breakout / Base':'Scan_Breakout_Base','Extended / Trim':'Scan_Extended_Trim'}
        col=cmap[scanner]
        if col in filtered: filtered=filtered[filtered[col]]

    _active_mode=(forced_mode or (str(filtered['Analysis_Mode'].iloc[0]) if 'Analysis_Mode' in filtered and not filtered.empty else analysis_mode or 'Técnico'))

    if _active_mode=='Técnico':
        st.subheader('🎯 Mejores oportunidades técnicas')
        section_note('Ranking puramente técnico: tendencia, momentum, fuerza relativa, entrada, volumen y riesgo. No se muestran métricas fundamentales.')
    elif _active_mode=='Fundamental':
        st.subheader('🏆 Mejores oportunidades fundamentales')
        section_note('Oportunidad fundamental: combina calidad, valoración, revisiones y resiliencia. Los líderes de calidad se muestran aparte para no confundir gran empresa con precio atractivo.')
    else:
        st.subheader('🎯 Best Opportunities Now')
        section_note('Ranking combinado: fundamentales + técnica + contexto. El score final penaliza R/R pobre, extensión y earnings inminentes.')

    if filtered.empty:
        st.warning(f'El escaneo encontró datos, pero 0 activos superan el Setup preliminar mínimo de {min_prelim}. Bajá ese filtro para ver resultados.')
        with st.expander('📊 Ver resultados sin filtro preliminar'):
            if _active_mode=='Técnico':
                _raw_cols=['Ticker','Analysis_Mode','Depth_Mode','Technical_Score','Preliminary_Score','Trend_Score','Entry_Score','RS_Percentile','Sector_Score','Asset_Context_Score','Macro_Fit','Risk_Score','Confidence_Score','Setup','Action']
            elif _active_mode=='Fundamental':
                _raw_cols=['Ticker','Analysis_Mode','Depth_Mode','Sector','Industry','Quality_Score','Valuation_Score','Revision_Score','Peer_Rank_Score','PE_Sector_Percentile','Data_Coverage_Score','Event_Risk']
            else:
                _raw_cols=['Ticker','Analysis_Mode','Depth_Mode','Opportunity_Score','Preliminary_Score','Quality_Score','Valuation_Score','Revision_Score','Technical_Score','Trend_Score','Entry_Score','RS_Percentile','Asset_Context_Score','Risk_Score','Action']
            _raw_cols=[c for c in _raw_cols if c in results.columns]
            _raw_sort='Technical_Score' if _active_mode=='Técnico' and 'Technical_Score' in results else ('Quality_Score' if _active_mode=='Fundamental' and 'Quality_Score' in results else 'Preliminary_Score')
            st.dataframe(results[_raw_cols].sort_values(_raw_sort,ascending=False,na_position='last').head(40),width='stretch',hide_index=True)

    opps=filtered.copy()
    if _active_mode=='Técnico':
        opps['_rank']=pd.to_numeric(opps.get('Technical_Score'),errors='coerce').fillna(opps['Preliminary_Score'])
    elif _active_mode=='Fundamental':
        opps['_rank']=pd.to_numeric(opps.get('Fundamental_Opportunity_Score'),errors='coerce')
    else:
        opps['_rank']=pd.to_numeric(opps.get('Opportunity_Score'),errors='coerce').fillna(opps['Preliminary_Score'])
    opps=opps.sort_values(['_rank','Entry_Score','RS_Percentile'],ascending=False,na_position='last')

    technical_cols=['Ticker','Analysis_Mode','Depth_Mode','Asset_Type','Analysis_Model','Sector','Technical_Score','Preliminary_Score','Trend_Score','Entry_Score','RS_Percentile','Sector_Score','Asset_Context_Score','Macro_Fit','Risk_Score','Confidence_Score','Setup','Trend','Price','RSI14','Dist_EMA62_%','Dist_EMA79_%','Dist_SMA200_%','RS_63d_%','Rel_Volume','RR_Text','Action']
    fundamental_cols=['Ticker','Analysis_Mode','Depth_Mode','Sector','Industry','Equity_Model','Fundamental_Opportunity_Score','Quality_Score','Valuation_Score','Revision_Score','Peer_Rank_Score','Peer_Rank_Source','Peer_Rank_Peer_Count','PE_Sector_Percentile','PE_Percentile_Source','PE_Peer_Count','Revision_Direction','Earnings_Quality_Score','Financial_Resilience_Score','Capital_Allocation_Score','Management_Execution_Score','Revenue_Growth','Earnings_Growth','Forward_PE','EV_EBITDA','Price_to_Book','Price_to_Sales','FCF_Yield','Reverse_DCF_Implied_Growth_%','DCF_Fair_Value_Upside_%','Data_Coverage_Score','Data_Coverage_Label','Event_Risk','Days_to_Earnings','Bear_Case_Price','Base_Case_Price','Bull_Case_Price','Scenario_Expected_Return_%','Scenario_Coverage_%']
    combined_cols=['Ticker','Analysis_Mode','Depth_Mode','Asset_Type','Analysis_Model','Sector','Industry','Equity_Model','Opportunity_Score','Preliminary_Score','Quality_Score','Valuation_Score','Peer_Rank_Score','PE_Sector_Percentile','Revision_Score','Revision_Direction','Technical_Score','Trend_Score','Entry_Score','RS_Percentile','Sector_Score','Asset_Context_Score','Macro_Fit','Macro_Regime','Risk_Score','Confidence_Score','Data_Coverage_Score','Data_Coverage_Label','Event_Risk','Days_to_Earnings','RR_Text','Setup','Action']

    visible_cols=[c for c in (technical_cols if _active_mode=='Técnico' else fundamental_cols if _active_mode=='Fundamental' else combined_cols) if c in opps.columns]
    st.dataframe(opps[visible_cols].head(40),width='stretch',hide_index=True)

    if _active_mode=='Fundamental':
        leaders=results[results['Fundamental_Leader_Score'].notna()].sort_values('Fundamental_Leader_Score',ascending=False) if 'Fundamental_Leader_Score' in results else pd.DataFrame()
        if not leaders.empty:
            st.subheader('🏆 Líderes fundamentales')
            section_note('Ranking de calidad del negocio: calidad, resiliencia financiera, calidad de earnings, asignación de capital y ejecución. No premia una acción solo por estar barata y no usa timing técnico.')
            cols=['Ticker','Sector','Industry','Equity_Model','Fundamental_Leader_Score','Quality_Score','Financial_Resilience_Score','Earnings_Quality_Score','Capital_Allocation_Score','Management_Execution_Score','Peer_Rank_Score','Peer_Rank_Source','Peer_Rank_Peer_Count','Data_Coverage_Score','Data_Coverage_Label','Event_Risk']
            st.dataframe(leaders[[c for c in cols if c in leaders]].head(30),width='stretch',hide_index=True)
    elif _active_mode=='Combinado':
        leaders=results[results['Best_Stock_Score'].notna()].sort_values('Best_Stock_Score',ascending=False) if 'Best_Stock_Score' in results else pd.DataFrame()
        if not leaders.empty:
            st.subheader('🏆 Best Stocks / Leaders')
            section_note('Calidad + revisions + liderazgo. Puede ser excelente empresa y mala entrada hoy.')
            cols=['Ticker','Sector','Industry','Equity_Model','Best_Stock_Score','Quality_Score','Valuation_Score','Revision_Score','Trend_Score','RS_Percentile','Sector_Score','Macro_Fit','Entry_Score','Data_Coverage_Score','Data_Coverage_Label','Event_Risk','RR_Text','Action']
            st.dataframe(leaders[[c for c in cols if c in leaders]].head(30),width='stretch',hide_index=True)

    if _active_mode=='Técnico':
        with st.expander('📊 Tabla técnica completa',expanded=False):
            cols=['Ticker','Asset_Type','Analysis_Model','Sector','Technical_Score','Trend_Score','Entry_Score','RS_Percentile','Sector_Score','Asset_Context_Score','Macro_Fit','Risk_Score','Confidence_Score','Setup','Trend','Price','RSI14','Dist_EMA62_%','Dist_EMA79_%','Dist_SMA200_%','RS_63d_%','Rel_Volume','RR_Text','Action']
            st.dataframe(results[[c for c in cols if c in results]],width='stretch',hide_index=True)
    elif _active_mode=='Fundamental':
        with st.expander('📚 Tabla fundamental completa',expanded=False):
            cols=['Ticker','Sector','Industry','Equity_Model','Fundamental_Opportunity_Score','Fundamental_Leader_Score','Quality_Score','Valuation_Score','Revision_Score','Peer_Rank_Score','Peer_Rank_Source','Peer_Rank_Peer_Count','PE_Sector_Percentile','PE_Percentile_Source','PE_Peer_Count','Revision_Direction','Earnings_Quality_Score','Financial_Resilience_Score','Capital_Allocation_Score','Management_Execution_Score','Revenue_Growth','Earnings_Growth','Forward_PE','EV_EBITDA','Price_to_Book','Price_to_Sales','FCF_Yield','Reverse_DCF_Implied_Growth_%','DCF_Fair_Value_Upside_%','Data_Coverage_Score','Data_Coverage_Label','Event_Risk','Days_to_Earnings','Bear_Case_Price','Base_Case_Price','Bull_Case_Price','Scenario_Expected_Return_%','Scenario_Coverage_%']
            st.dataframe(results[[c for c in cols if c in results]],width='stretch',hide_index=True)
    else:
        with st.expander('📊 Tabla combinada completa',expanded=False):
            cols=[c for c in combined_cols if c in results]
            st.dataframe(results[cols],width='stretch',hide_index=True)


    if st.session_state.get('screener_timing'):
        with st.expander('⏱️ Rendimiento del último escaneo'):
            tm=st.session_state.screener_timing
            st.caption(f"Tiempo total: {tm.get('total_seconds',0):.1f}s")
            perf=pd.DataFrame([{'Etapa':k,'Segundos':v} for k,v in tm.items() if k!='total_seconds'])
            st.dataframe(perf,width='stretch',hide_index=True)

    st.download_button('⬇️ Descargar análisis completo',results.to_csv(index=False).encode('utf-8'),'professional_screener_v5.csv','text/csv')
