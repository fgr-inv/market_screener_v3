
APP_NAME = "Market Screener Pro"
APP_VERSION = "11.23"

SECTOR_ETFS = {
    "Technology":"XLK","Financials":"XLF","Health Care":"XLV","Industrials":"XLI",
    "Utilities":"XLU","Energy":"XLE","Materials":"XLB","Real Estate":"XLRE",
    "Consumer Discretionary":"XLY","Consumer Staples":"XLP","Communication Services":"XLC",
}

MACRO_SYMBOLS = {
    "SPY":"SPY","QQQ":"QQQ","IWM":"IWM","RSP":"RSP","VIX":"^VIX","US10Y":"^TNX",
    "US5Y":"^FVX","US13W":"^IRX","Dollar":"UUP","High Yield":"HYG",
    "Investment Grade":"LQD","Treasuries":"IEF","Long Treasuries":"TLT",
    "Gold":"GLD","Oil":"CL=F","Copper":"HG=F","Bitcoin":"BTC-USD","Ethereum":"ETH-USD",
}

CROSS_ASSET = {
    "S&P 500":"SPY","Nasdaq 100":"QQQ","Russell 2000":"IWM","Bitcoin":"BTC-USD",
    "Ethereum":"ETH-USD","Gold":"GLD","Long Treasuries":"TLT","US Dollar":"UUP",
    "Oil":"CL=F","Copper":"HG=F",
}

ASSET_PRESETS = {
    "ETFs":{
        "US Market":["SPY","QQQ","IWM","DIA","RSP"],
        "Sectores":list(SECTOR_ETFS.values()),
        "Bonos":["TLT","IEF","SHY","HYG","LQD"],
        "Commodities ETFs":["GLD","SLV","USO","UNG","DBA"],
    },
    "Índices":{
        "Principales":["^GSPC","^NDX","^DJI","^RUT","^VIX"],
        "Internacionales":["^FTSE","^GDAXI","^FCHI","^N225","^HSI"],
    },
    "Cripto":{
        "Grandes":["BTC-USD","ETH-USD","SOL-USD","XRP-USD","BNB-USD"],
        "Ampliado":["BTC-USD","ETH-USD","SOL-USD","XRP-USD","BNB-USD","ADA-USD","DOGE-USD","AVAX-USD","LINK-USD","DOT-USD"],
    },
    "Commodities":{
        "Futuros principales":["GC=F","SI=F","CL=F","NG=F","HG=F"],
        "Agrícolas":["ZC=F","ZW=F","ZS=F","KC=F","SB=F"],
    },
    "Bonos / Tasas":{
        "ETFs":["TLT","IEF","SHY","HYG","LQD"],
        "Yields":["^TNX","^TYX","^FVX","^IRX"],
    },
    "Forex":{
        "Majors":["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X"],
        "Crosses":["EURGBP=X","EURJPY=X","GBPJPY=X"],
    },
}

SECTOR_ALIASES = {
    "Information Technology":"Technology","Technology":"Technology","Financials":"Financials",
    "Health Care":"Health Care","Healthcare":"Health Care","Industrials":"Industrials",
    "Utilities":"Utilities","Energy":"Energy","Materials":"Materials","Real Estate":"Real Estate",
    "Consumer Discretionary":"Consumer Discretionary","Consumer Staples":"Consumer Staples",
    "Communication Services":"Communication Services",
}
