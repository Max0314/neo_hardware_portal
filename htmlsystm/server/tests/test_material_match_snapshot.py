import pytest
from server.material_match_snapshot import build_snapshot


def library(rows, id='a'):
    return {'id': id, 'currentTable': {'data': [['物料代码', '物料描述', '替代组标签', '优选情况'], *rows]}}


def test_empty_alternative_group_is_kept_and_code_is_string():
    result = build_snapshot([library([['001', '螺钉', '', '优选']])])
    assert result['parts'][0]['partCode'] == '001'
    assert result['parts'][0]['altGroup'] == ''


def test_duplicates_and_conflicts():
    a = library([['001', '电阻', 'A', '优选']])
    assert len(build_snapshot([a, a])['parts']) == 1
    with pytest.raises(ValueError, match='冲突'):
        build_snapshot([a, library([['001', '电容', 'A', '优选']], 'b')])


def test_version_changes_only_when_material_content_changes():
    a = library([['001', '电阻', '', '']])
    b = library([['002', '电容', '', '']], 'b')
    assert build_snapshot([a,b])['version'] == build_snapshot([b,a])['version']
    assert build_snapshot([a])['version'] != build_snapshot([a,b])['version']
