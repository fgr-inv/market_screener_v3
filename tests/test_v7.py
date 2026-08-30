import pandas as pd
import numpy as np

from core.data_quality import completeness_score, quality_label
from core.advanced_factor_model import shrink_covariance
from core.point_in_time import premium_data_contracts
from core.fx_macro import parse_pair


def test_completeness():
    assert completeness_score({'a':1,'b':None},['a','b']) == 50
    assert quality_label(95) == 'EXCELLENT'


def test_fx_pair():
    assert parse_pair('EURUSD=X') == ('EUR','USD')


def test_contracts():
    c = premium_data_contracts()
    assert 'SP500_constituents.csv' in c


def test_shrink_cov_empty():
    assert shrink_covariance({},['A','B']).empty
