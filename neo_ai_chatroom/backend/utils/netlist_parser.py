"""
PADS网表解析器
基于 net-analysis.html 的解析逻辑
"""
import re
from typing import Dict, List, Optional, Tuple


class PadsNetlistParser:
    """PADS网表解析器"""

    W_RC_L_VALUE_PATTERN = re.compile(r'W-[RCL]-(.*?)@', re.IGNORECASE)
    BRACE_VALUE_PATTERN = re.compile(r'\{([^}]+)\}')
    PACKAGE_PATTERN = re.compile(r'@([\w-]+)')

    def __init__(self):
        self.components: Dict[str, Dict] = {}
        self.nets: Dict[str, List[str]] = {}
        self.attributes: Dict[str, Dict[str, str]] = {}

    def parse(self, content: str) -> Dict:
        """
        解析 PADS 网表内容

        Returns:
            {
                "components": {component_id: component_info},
                "nets": {net_name: [connections]},
                "attributes": {component_id: {attr: value}}
            }
        """
        self.components = {}
        self.nets = {}
        self.attributes = {}

        lines = content.split('\n')
        in_part_section = False
        in_net_section = False
        in_attribute_section = False
        current_attribute_component: Optional[str] = None

        # 与 net-analysis.html 一致：使用可手动推进的下标，避免 enumerate 无法跳过连接行
        i = 0
        line_count = len(lines)
        while i < line_count:
            line = lines[i].strip()

            if line.startswith('*PART*'):
                in_part_section = True
                in_net_section = False
                in_attribute_section = False
                i += 1
                continue

            if line.startswith('*NET*'):
                in_part_section = False
                in_net_section = True
                in_attribute_section = False
                i += 1
                continue

            if line.startswith('ATTRIBUTE VALUES'):
                in_part_section = False
                in_net_section = False
                in_attribute_section = True
                i += 1
                continue

            if line.startswith('*END*') or line.startswith('*MISC*'):
                in_part_section = False
                in_net_section = False
                in_attribute_section = False
                i += 1
                continue

            if in_part_section and line and not line.startswith('*') and line.upper() != 'ITEMS':
                self._parse_part_line(line)

            if in_net_section and line.startswith('*SIGNAL*'):
                net_name = line[8:].strip()
                if net_name:
                    self.nets[net_name] = []
                    i += 1
                    while i < line_count:
                        conn_line = lines[i].strip()
                        if not conn_line:
                            i += 1
                            continue
                        if conn_line.startswith('*SIGNAL*'):
                            i -= 1
                            break
                        if conn_line.startswith('*'):
                            break
                        for conn in conn_line.split():
                            conn = conn.strip()
                            if not conn:
                                continue
                            self.nets[net_name].append(conn)
                            if '.' in conn:
                                try:
                                    component_id, pin = conn.split('.', 1)
                                    if component_id and pin and component_id in self.components:
                                        self.components[component_id]['pins'][pin] = net_name
                                except ValueError:
                                    pass
                        i += 1

            if in_attribute_section:
                if line.startswith('PART'):
                    match = re.search(r'PART\s+(\w+)', line)
                    if match:
                        current_attribute_component = match.group(1)
                        self.attributes[current_attribute_component] = {}

                if current_attribute_component and '"' in line:
                    match = re.search(r'"([^"]+)"\s*([^"]*)', line)
                    if match:
                        key = match.group(1)
                        value = match.group(2).strip()
                        self.attributes[current_attribute_component][key] = value
                        self._apply_attribute(current_attribute_component, key, value)

            i += 1

        return {
            'components': self.components,
            'nets': self.nets,
            'attributes': self.attributes,
        }

    def _parse_part_line(self, line: str) -> None:
        parts = line.split()
        if len(parts) < 2:
            return

        component_id = parts[0]
        component_info = parts[1]

        package_name = self._extract_package(component_info)
        value, voltage_rating, tolerance, temp_tolerance, param_package = self._extract_params(
            component_id, component_info
        )
        if param_package:
            package_name = param_package
        component_type = self._detect_component_type(component_id, component_info)

        self.components[component_id] = {
            'id': component_id,
            'type': component_type,
            'value': value,
            'package': package_name,
            'voltage_rating': voltage_rating,
            'tolerance': tolerance,
            'temp_tolerance': temp_tolerance,
            'part_number': component_info,
            'pins': {},
        }

    def _extract_package(self, component_info: str) -> str:
        match = self.PACKAGE_PATTERN.search(component_info)
        return match.group(1) if match else ''

    def _extract_params(
        self, component_id: str, component_info: str
    ) -> Tuple[str, str, str, str, str]:
        value = ''
        voltage_rating = ''
        tolerance = ''
        temp_tolerance = ''
        param_package = ''

        value_match = self.W_RC_L_VALUE_PATTERN.search(component_info)
        if value_match:
            params = value_match.group(1).split('|')
            if component_id.startswith('C') or 'W-C-' in component_info.upper():
                if len(params) >= 1:
                    value = params[0] or ''
                if len(params) >= 2:
                    voltage_rating = params[1] or ''
                if len(params) >= 3:
                    tolerance = params[2] or ''
                if len(params) >= 4:
                    temp_tolerance = params[3] or ''
                if len(params) >= 5:
                    param_package = params[4] or ''
            elif component_id.startswith('R') or 'W-R-' in component_info.upper():
                if len(params) >= 1:
                    value = params[0] or ''
                if len(params) >= 2:
                    tolerance = params[1] or ''
                if len(params) >= 3:
                    param_package = params[2] or ''
            elif component_id.startswith('L') or 'W-L-' in component_info.upper():
                if len(params) >= 1:
                    value = params[0] or ''
                if len(params) >= 2:
                    tolerance = params[1] or ''
                if len(params) >= 3:
                    param_package = params[2] or ''
            else:
                if len(params) >= 1:
                    value = params[0] or ''
                if len(params) >= 2:
                    voltage_rating = params[1] or ''
                if len(params) >= 3:
                    tolerance = params[2] or ''
                if len(params) >= 4:
                    temp_tolerance = params[3] or ''
                if len(params) >= 5:
                    param_package = params[4] or ''
        else:
            brace_match = self.BRACE_VALUE_PATTERN.search(component_info)
            if brace_match:
                value = brace_match.group(1).strip()

        return value, voltage_rating, tolerance, temp_tolerance, param_package

    def _detect_component_type(self, component_id: str, component_info: str) -> str:
        info_upper = component_info.upper()
        if component_id.startswith('C') or 'W-C-' in info_upper:
            return 'Capacitor'
        if component_id.startswith('R') or 'W-R-' in info_upper:
            return 'Resistor'
        if component_id.startswith('L') or 'W-L-' in info_upper:
            return 'Inductor'
        if component_id.startswith('D'):
            return 'Diode'
        if component_id.startswith('Q'):
            return 'Transistor'
        if component_id.startswith('U'):
            return 'IC'
        return 'Unknown'

    def _apply_attribute(self, component_id: str, key: str, value: str) -> None:
        if component_id not in self.components:
            return
        comp = self.components[component_id]
        if key == 'Value' and value:
            comp['value'] = value
        elif key == 'Voltage Rating' and value:
            comp['voltage_rating'] = value
        elif key == 'Tolerance' and value:
            comp['tolerance'] = value
        elif key == 'TempTolerance' and value:
            comp['temp_tolerance'] = value
        elif key == 'Package' and value:
            comp['package'] = value
        elif key == 'EType' and value:
            etype_map = {
                'C': 'Capacitor',
                'R': 'Resistor',
                'L': 'Inductor',
                'D': 'Diode',
                'Q': 'Transistor',
                'U': 'IC',
            }
            comp['type'] = etype_map.get(value, value)


class NetlistComparator:
    """网表比较器"""

    def compare(self, netlist1: Dict, netlist2: Dict) -> Dict:
        """
        比较两个网表

        Returns:
            {
                "added_components": [component_ids],
                "removed_components": [component_ids],
                "changed_components": [component_ids],
                "added_nets": [net_names],
                "removed_nets": [net_names],
                "changed_nets": [net_names],
                "components1": {...},
                "components2": {...},
                "nets1": {...},
                "nets2": {...}
            }
        """
        result = {
            'added_components': [],
            'removed_components': [],
            'changed_components': [],
            'added_nets': [],
            'removed_nets': [],
            'changed_nets': [],
            'components1': netlist1['components'],
            'components2': netlist2['components'],
            'nets1': netlist1['nets'],
            'nets2': netlist2['nets'],
        }

        comp_ids1 = set(netlist1['components'].keys())
        comp_ids2 = set(netlist2['components'].keys())

        result['added_components'] = list(comp_ids2 - comp_ids1)
        result['removed_components'] = list(comp_ids1 - comp_ids2)

        for comp_id in comp_ids1 & comp_ids2:
            comp1 = netlist1['components'][comp_id]
            comp2 = netlist2['components'][comp_id]
            if self._is_component_different(comp1, comp2):
                result['changed_components'].append(comp_id)

        net_names1 = set(netlist1['nets'].keys())
        net_names2 = set(netlist2['nets'].keys())

        result['added_nets'] = list(net_names2 - net_names1)
        result['removed_nets'] = list(net_names1 - net_names2)

        for net_name in net_names1 & net_names2:
            net1 = sorted(netlist1['nets'][net_name])
            net2 = sorted(netlist2['nets'][net_name])
            if net1 != net2:
                result['changed_nets'].append(net_name)

        return result

    def _is_component_different(self, comp1: Dict, comp2: Dict) -> bool:
        if comp1.get('type') != comp2.get('type'):
            return True
        if comp1.get('value') != comp2.get('value'):
            return True
        if comp1.get('package') != comp2.get('package'):
            return True

        if comp1.get('type') == 'Capacitor':
            if comp1.get('voltage_rating') != comp2.get('voltage_rating'):
                return True
            if comp1.get('temp_tolerance') != comp2.get('temp_tolerance'):
                return True

        if comp1.get('tolerance') != comp2.get('tolerance'):
            return True

        if comp1.get('pins', {}) != comp2.get('pins', {}):
            return True

        return False
