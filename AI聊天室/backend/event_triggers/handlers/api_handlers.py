"""
API调用事件处理器
API Call Event Handlers
"""
from typing import Dict, Any


class APIHandlers:
    """API调用相关事件处理器"""
    
    @staticmethod
    async def handle_call_api(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """调用API"""
        url = params.get("url")
        method = params.get("method", "GET")
        data = params.get("data")
        
        if not url:
            raise ValueError("API URL不能为空")
        
        import aiohttp
        async with aiohttp.ClientSession() as session:
            if method.upper() == "GET":
                async with session.get(url, params=data) as response:
                    result = await response.json()
                    return {"response": result}
            elif method.upper() == "POST":
                async with session.post(url, json=data) as response:
                    result = await response.json()
                    return {"response": result}
            else:
                raise ValueError(f"不支持的HTTP方法: {method}")
