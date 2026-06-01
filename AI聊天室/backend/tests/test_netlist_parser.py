"""PADS 网表解析器单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.utils.netlist_parser import PadsNetlistParser, NetlistComparator
from backend.utils.netlist_analyzer import NetlistAnalyzer

SAMPLE_NETLIST = """
*PART*
ITEMS
C38     W-C-15NF|100V|F|X7R|0603@W-C0603
R12V    W-R-4.7K|F|0201@W-R0201
U2V     {PEF31001VSV12}@W-IC
U5      @W-IC
*NET*
*SIGNAL* GND
U5.8 U5.10 C38.1
*SIGNAL* +3_3V
U5.11 R12V.1 U2V.36
*SIGNAL* PCM_CLK
U5.5 R12V.2
*END*
"""


def test_parse_components_and_nets():
    parser = PadsNetlistParser()
    result = parser.parse(SAMPLE_NETLIST)
    assert len(result['components']) == 4
    assert len(result['nets']) == 3
    assert 'GND' in result['nets']
    assert len(result['nets']['GND']) == 3
    assert result['components']['C38']['type'] == 'Capacitor'
    assert result['components']['C38']['value'] == '15NF'
    assert result['components']['C38']['voltage_rating'] == '100V'
    assert result['components']['U2V']['type'] == 'IC'
    assert result['components']['U2V']['value'] == 'PEF31001VSV12'
    assert result['components']['U2V']['package'] == 'W-IC'
    assert result['components']['U5']['pins'].get('8') == 'GND'


def test_analyzer_produces_sorted_nets():
    analyzer = NetlistAnalyzer()
    analysis = analyzer.analyze(SAMPLE_NETLIST)
    assert analysis['summary']['total_nets'] == 3
    assert analysis['summary']['total_components'] == 4
    net_names = [n['name'] for n in analysis['nets']]
    assert 'GND' in net_names
    gnd = next(n for n in analysis['nets'] if n['name'] == 'GND')
    assert gnd['type'] == 'Power'


def test_comparator_detects_net_change():
    parser = PadsNetlistParser()
    n1 = parser.parse(SAMPLE_NETLIST)
    n2 = parser.parse(SAMPLE_NETLIST.replace('U5.10', 'U5.9'))
    cmp = NetlistComparator()
    diff = cmp.compare(n1, n2)
    assert 'GND' in diff['changed_nets']
