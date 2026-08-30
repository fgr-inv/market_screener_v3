
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def technical_chart(hist,title=None):
    h=hist.tail(260)
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=.03,row_heights=[.64,.16,.20])
    fig.add_trace(go.Candlestick(x=h.index,open=h["Open"],high=h["High"],low=h["Low"],close=h["Close"],name="Precio"),row=1,col=1)
    for col,name in [("EMA62","EMA62"),("EMA79","EMA79"),("SMA200","SMA200"),("KC_Upper","Keltner Sup."),("KC_Lower","Keltner Inf.")]:
        if col in h.columns:
            fig.add_trace(go.Scatter(x=h.index,y=h[col],mode="lines",name=name,line=dict(width=1.6)),row=1,col=1)
    fig.add_trace(go.Bar(x=h.index,y=h["Volume"],name="Volumen",opacity=.55),row=2,col=1)
    fig.add_trace(go.Scatter(x=h.index,y=h["RSI14"],mode="lines",name="RSI14"),row=3,col=1)
    fig.add_hline(y=70,row=3,col=1); fig.add_hline(y=30,row=3,col=1)
    fig.update_layout(title=title,height=760,xaxis_rangeslider_visible=False,legend=dict(orientation="h",y=1.02,x=0),margin=dict(l=10,r=10,t=50,b=10),hovermode="x unified")
    return fig

def macro_components_chart(m):
    labels=["Breadth","Credit","Risk Appetite","Rates","Liquidity","Growth","Inflation (inverse)"]
    vals=[m["Breadth"],m["Credit"],m["Risk_Appetite"],m["Rates"],m["Liquidity"],m["Growth"],100-m["Inflation_Pressure"]]
    fig=go.Figure(go.Bar(x=vals,y=labels,orientation="h",text=[f"{v:.0f}" for v in vals],textposition="auto"))
    fig.update_layout(height=360,xaxis=dict(range=[0,100],title="Score"),margin=dict(l=10,r=10,t=10,b=30))
    return fig
