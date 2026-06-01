"""
网表分析器
对单个网表进行详细分析
"""
import re
from typing import Dict, List, Optional
from backend.utils.netlist_parser import PadsNetlistParser


class NetlistAnalyzer:
    """网表分析器"""
    
    def __init__(self):
        self.parser = PadsNetlistParser()
    
    def analyze(self, netlist_content: str) -> Dict:
        """
        分析网表，生成详细报告
        
        Returns:
            {
                "summary": {...},
                "components": [...],
                "nets": [...],
                "analysis": {...}
            }
        """
        # 解析网表
        parsed = self.parser.parse(netlist_content)
        
        components = parsed['components']
        nets = parsed['nets']
        
        # 生成摘要
        summary = {
            'total_components': len(components),
            'total_nets': len(nets),
            'component_types': self._count_by_type(components),
            'power_nets': self._identify_power_nets(nets),
            'differential_pairs': self._identify_differential_pairs(nets),
            'interface_nets': self._identify_interface_nets(nets)
        }
        
        # 生成元件列表
        component_list = []
        for comp_id, comp in components.items():
            component_list.append({
                'id': comp_id,
                'type': comp['type'],
                'value': comp['value'],
                'package': comp['package'],
                'voltage_rating': comp.get('voltage_rating', ''),
                'tolerance': comp.get('tolerance', ''),
                'temp_tolerance': comp.get('temp_tolerance', ''),
                'part_number': comp.get('part_number', ''),  # 保存完整的元件名称
                'pins': comp.get('pins', {})
            })
        
        # 生成网络列表（按 Power → Clock → Signal 排序，便于展示与 AI 消费）
        net_list = []
        for net_name, connections in nets.items():
            net_list.append({
                'name': net_name,
                'connections': connections,
                'connection_count': len(connections),
                'type': self._classify_net(net_name, connections)
            })
        type_order = {'Power': 0, 'Clock': 1, 'Signal': 2, 'Differential': 3, 'Interface': 4}
        net_list.sort(key=lambda n: (type_order.get(n['type'], 99), n['name'] or ''))
        
        # 生成分析结果
        analysis = {
            'component_analysis': self._analyze_components(components),
            'net_analysis': self._analyze_nets(nets),
            'potential_issues': self._find_potential_issues(components, nets)
        }
        
        return {
            'summary': summary,
            'components': component_list,
            'nets': net_list,
            'attributes': parsed.get('attributes') or {},
            'analysis': analysis,
        }
    
    def _count_by_type(self, components: Dict) -> Dict[str, int]:
        """按类型统计元件"""
        type_count = {}
        for comp in components.values():
            comp_type = comp.get('type', 'Unknown')
            type_count[comp_type] = type_count.get(comp_type, 0) + 1
        return type_count
    
    def _identify_power_nets(self, nets: Dict) -> List[str]:
        """
        识别电源网络（根据常见命名 + PWR 关键字，避免纯数字/编码类网络被误判）

        规则：
        - 含有 VCC/VDD/VDDQ/VREF/VTT/AVDD/DVDD/PVDD/VBAT/VIN/VOUT/PWR 等关键词视为电源
        - 含有类似 3V3、3_3V、+3.3V、PWR_3V3 等写法视为电源
        - 纯数字 / 若干美元符号+数字（如 $$$17578）视为编码，不当电源
        """
        base_keywords = [
            'VCC', 'VDD', 'VDDQ', 'VREF', 'VTT',
            'AVDD', 'DVDD', 'PVDD',
            'VBAT', 'VIN', 'VOUT',
            'PWR',
        ]
        explicit_voltage_patterns = [
            r'[+-]?\d+V\d+',      # 3V3, 1V8
            r'[+-]?\d+[_-]\d+V',  # 3_3V, 1-8V
            r'[+-]?\d+(\.\d+)?V', # 3.3V, 5V, 12V 等
        ]

        power_nets: List[str] = []
        for net_name in nets.keys():
            net_upper = net_name.upper()
            # 纯数字或前缀+数字（如 $$$17578）视为编码类网络，不作为电源
            if re.fullmatch(r'[\$]*\d+', net_upper):
                continue

            # 关键字匹配（含 PWR）
            if any(kw in net_upper for kw in base_keywords):
                power_nets.append(net_name)
                continue

            # 明确的电压写法
            for pat in explicit_voltage_patterns:
                if re.search(pat, net_upper):
                    power_nets.append(net_name)
                    break

        return power_nets
    
    def _identify_differential_pairs(self, nets: Dict) -> List[Dict]:
        """识别差分对"""
        differential_pairs = []
        net_names = list(nets.keys())
        
        for i, net1 in enumerate(net_names):
            for net2 in net_names[i+1:]:
                # 检查是否是差分对（_P/_N, +/-）
                if (net1.endswith('_P') and net2.endswith('_N') and 
                    net1[:-2] == net2[:-2]):
                    differential_pairs.append({
                        'positive': net1,
                        'negative': net2,
                        'base_name': net1[:-2]
                    })
                elif (net1.endswith('+') and net2.endswith('-') and
                      net1[:-1] == net2[:-1]):
                    differential_pairs.append({
                        'positive': net1,
                        'negative': net2,
                        'base_name': net1[:-1]
                    })
        
        return differential_pairs
    
    def _identify_interface_nets(self, nets: Dict) -> Dict[str, List[str]]:
        """识别接口网络"""
        interfaces = {
            'PCIe': [],
            'USB': [],
            'Ethernet': [],
            'HDMI': [],
            'DDR': [],
            'SATA': [],
            'MIPI': [],
            'LVDS': []
        }
        
        for net_name in nets.keys():
            net_upper = net_name.upper()
            if 'PCIE' in net_upper or 'PCI' in net_upper:
                interfaces['PCIe'].append(net_name)
            elif 'USB' in net_upper:
                interfaces['USB'].append(net_name)
            elif 'ETH' in net_upper or 'MDI' in net_upper:
                interfaces['Ethernet'].append(net_name)
            elif 'HDMI' in net_upper or 'TMDS' in net_upper:
                interfaces['HDMI'].append(net_name)
            elif 'DDR' in net_upper or 'DQ' in net_upper or 'DQS' in net_upper:
                interfaces['DDR'].append(net_name)
            elif 'SATA' in net_upper:
                interfaces['SATA'].append(net_name)
            elif 'MIPI' in net_upper:
                interfaces['MIPI'].append(net_name)
            elif 'LVDS' in net_upper:
                interfaces['LVDS'].append(net_name)
        
        # 移除空列表
        return {k: v for k, v in interfaces.items() if v}
    
    def _classify_net(self, net_name: str, connections: List[str]) -> str:
        """分类网络类型"""
        net_upper = net_name.upper()
        
        # 纯数字/编码类网络优先视为普通信号，避免被误判为电源
        if re.fullmatch(r'[\$]*\d+', net_upper):
            return 'Signal'
        
        if any(kw in net_upper for kw in ['VCC', 'VDD', 'GND', 'VSS', '3V3', '3_3V', '+3_3V', '5V', '12V']):
            return 'Power'
        elif any(kw in net_upper for kw in ['CLK', 'CLOCK', 'REFCLK']):
            return 'Clock'
        elif net_name.endswith('_P') or net_name.endswith('_N') or net_name.endswith('+') or net_name.endswith('-'):
            return 'Differential'
        elif any(kw in net_upper for kw in ['PCIE', 'USB', 'ETH', 'HDMI', 'DDR', 'SATA', 'MIPI', 'LVDS']):
            return 'Interface'
        else:
            return 'Signal'
    
    def _analyze_components(self, components: Dict) -> Dict:
        """分析元件"""
        analysis = {
            'missing_values': [],
            'missing_packages': [],
            'unusual_values': []
        }
        
        for comp_id, comp in components.items():
            if not comp.get('value'):
                analysis['missing_values'].append(comp_id)
            if not comp.get('package'):
                analysis['missing_packages'].append(comp_id)
        
        return analysis
    
    def _analyze_nets(self, nets: Dict) -> Dict:
        """分析网络"""
        analysis = {
            'single_connection_nets': [],
            'high_connection_nets': [],
            'unconnected_components': []
        }
        
        for net_name, connections in nets.items():
            if len(connections) == 1:
                analysis['single_connection_nets'].append(net_name)
            elif len(connections) > 20:
                analysis['high_connection_nets'].append({
                    'net': net_name,
                    'connections': len(connections)
                })
        
        return analysis
    
    def _parse_voltage(self, s: str) -> Optional[float]:
        """从字符串解析电压值（如 25V、6.3V、0、1.8V），无法解析返回 None"""
        if not s or not isinstance(s, str):
            return None
        s = str(s).strip().upper().replace(',', '.')
        # 匹配数字（含小数）+ 可选 V/mV/kV
        m = re.match(r'^([\d.]+)\s*(V|MV|KV)?$', s, re.IGNORECASE)
        if not m:
            return None
        try:
            val = float(m.group(1))
            unit = (m.group(2) or 'V').upper()
            if unit == 'MV':
                return val / 1000.0
            if unit == 'KV':
                return val * 1000.0
            return val
        except (ValueError, TypeError):
            return None

    def _infer_net_voltage(self, net_name: str) -> Optional[float]:
        """
        根据网络名称推断典型电压（GND=0, 3V3=3.3, 5V=5 等），无法推断返回 None

        支持的写法示例：
        - 3.3V, 5V, 1.8V, 12V
        - 3V3, 1V2, 1V8, 5V0
        - 3_3V, 1_8V, 3-3V, 1-8V
        - PWR_3V3, +3.3V, VDD_1V8, VCC_5V 等
        - 纯 PWR/VCC/VDD 等不含数字时返回 None（unknown），但在电源网络识别中仍视为电源
        """
        if not net_name:
            return None
        name = net_name.upper().strip()
        # 纯数字/编码类网络（如 $$$17580）不视为电源电压
        if re.fullmatch(r'[\$]*\d+', name):
            return None
        if name in ('GND', 'VSS', 'AGND', 'DGND', 'GNDA', 'GNDD'):
            return 0.0
        # 为方便提取，去掉前缀和后缀中明显与电压无关的部分，仅保留数字/V/分隔符
        core = re.sub(r'[^0-9V\.\+\-\_]', '', name)

        # 1) 直接匹配 x.xV 或 xV 形式（含正负号）
        m = re.search(r'[+-]?(\d+(?:\.\d+)?)V', core)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

        # 2) 匹配 3V3 / 1V8 / 5V0 等：整数 + V + 整数 => 小数
        m = re.search(r'([0-9]+)V([0-9]+)', core)
        if m:
            try:
                base = float(m.group(1))
                frac = float(m.group(2)) / (10 ** len(m.group(2)))
                return base + frac
            except ValueError:
                pass

        # 3) 匹配 3_3V / 1_8V / 3-3V 等：整数 + 分隔符 + 整数 + V
        m = re.search(r'([0-9]+)[_\-]([0-9]+)V', core)
        if m:
            try:
                base = float(m.group(1))
                frac = float(m.group(2)) / (10 ** len(m.group(2)))
                return base + frac
            except ValueError:
                pass

        # 4) 常见固定写法兜底
        if any(k in name for k in ['1.8V', '1V8']):
            return 1.8
        if any(k in name for k in ['3.3V', '3V3', '3_3V', '3-3V']):
            return 3.3
        if any(k in name for k in ['2.5V', '2V5']):
            return 2.5
        if any(k in name for k in ['1.2V', '1V2']):
            return 1.2
        if re.search(r'\b5V\b', name):
            return 5.0
        if re.search(r'\b12V\b', name):
            return 12.0

        return None

    def _find_potential_issues(self, components: Dict, nets: Dict) -> List[Dict]:
        """查找潜在问题"""
        issues = []

        # 电容耐压检查：耐压值应 >= 所在网络电压的 1.5 倍，否则存在风险
        for comp_id, comp in components.items():
            if (comp.get('type') or '').lower() != 'capacitor':
                continue
            rating = self._parse_voltage(comp.get('voltage_rating') or '')
            if rating is None:
                continue
            pins = comp.get('pins') or {}
            if not pins:
                continue
            net_names = list(set(pins.values()))
            max_net_v = None
            for net_name in net_names:
                v = self._infer_net_voltage(net_name)
                if v is not None:
                    if max_net_v is None or v > max_net_v:
                        max_net_v = v
            if max_net_v is None:
                continue
            required = 1.5 * max_net_v
            if rating < required:
                issues.append({
                    'type': 'capacitor_voltage_rating_risk',
                    'component': comp_id,
                    'net': net_names[0] if net_names else '',
                    'nets': net_names,
                    'severity': 'high',
                    'description': (
                        f'电容 {comp_id} 耐压 {comp.get("voltage_rating")}，所在网络电压约 {max_net_v}V，'
                        f'建议耐压 ≥ {required:.1f}V（1.5 倍），当前不足存在风险'
                    ),
                    'voltage_rating': comp.get('voltage_rating'),
                    'required_rating': round(required, 1),
                })
        
        # 检查未连接的元件
        for comp_id, comp in components.items():
            if not comp.get('pins'):
                issues.append({
                    'type': 'unconnected_component',
                    'component': comp_id,
                    'severity': 'medium',
                    'description': f'元件 {comp_id} 没有连接到任何网络'
                })
        
        # 检查单点网络
        for net_name, connections in nets.items():
            if len(connections) == 1 and net_name.upper() not in ['GND', 'VCC', 'VDD']:
                issues.append({
                    'type': 'single_point_net',
                    'net': net_name,
                    'severity': 'low',
                    'description': f'网络 {net_name} 只有一个连接点'
                })
        
        return issues
