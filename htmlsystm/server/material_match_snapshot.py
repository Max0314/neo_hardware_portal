"""Read-only projection for AI BOM; source libraries remain authoritative."""
import hashlib
import json

FIELDS = {'物料代码': 'partCode', '物料描述': 'description', '替代组标签': 'altGroup', '优选情况': 'preference'}


def build_snapshot(libraries):
    parts, seen, conflicts = [], {}, []
    for lib in sorted(libraries, key=lambda x: str(x.get('id', ''))):
        table = lib.get('currentTable') or {}
        rows = table.get('data') or []
        if not rows:
            continue
        header = [str(v or '').strip() for v in rows[0]]
        if '物料代码' not in header or '物料描述' not in header:
            if len(rows) > 1:
                raise ValueError('物料库表头缺少物料代码或物料描述：' + str(lib.get('name', '')))
            continue
        indices = {field: header.index(label) if label in header else -1 for label, field in FIELDS.items()}
        for row in rows[1:]:
            part = {field: str(row[i] if 0 <= i < len(row) and row[i] is not None else '').strip() for field, i in indices.items()}
            if not part['partCode']:
                continue
            code = part['partCode']
            if code in seen:
                if seen[code] != part:
                    conflicts.append(code)
                continue
            seen[code] = dict(part)
            part['libraryId'] = str(lib['id'])
            parts.append(part)
    if conflicts:
        raise ValueError('物料代码存在字段冲突，请在物料库核对：' + '、'.join(sorted(set(conflicts))[:10]))
    parts.sort(key=lambda p: (p['partCode'], p['libraryId']))
    version = hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'parts': parts, 'version': version, 'libraryCount': len(libraries)}
