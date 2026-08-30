import math


def size_position(capital, risk_pct, entry, stop, max_position_pct=25):
    capital=float(capital); risk_pct=float(risk_pct); entry=float(entry); stop=float(stop)
    if capital<=0 or entry<=0 or stop>=entry:
        return {'shares':0,'position_value':0,'risk_amount':0,'actual_risk':0,'position_pct':0}
    risk_amount=capital*risk_pct/100
    per_share=entry-stop
    shares=math.floor(risk_amount/per_share)
    max_value=capital*max_position_pct/100
    shares=min(shares, math.floor(max_value/entry))
    value=shares*entry
    actual=shares*per_share
    return {
        'shares':shares,'position_value':value,'risk_amount':risk_amount,'actual_risk':actual,
        'position_pct':value/capital*100 if capital else 0,'risk_per_share':per_share,
    }
