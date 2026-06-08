import httpx
import json
from typing import List, Dict, Any, Optional
from config import settings

class FeishuClient:
    def __init__(self):
        self.app_id = settings.FEISHU_APP_ID
        self.app_secret = settings.FEISHU_APP_SECRET
        self.tenant_access_token = None
        self._user_id_cache = {}  # 昵称 -> 用户ID 缓存
        
        # 环境变量校验
        if not self.app_id:
            raise ValueError("FEISHU_APP_ID 环境变量未设置")
        if not self.app_secret:
            raise ValueError("FEISHU_APP_SECRET 环境变量未设置")
    
    def _get_user_id_map(self) -> dict:
        """获取用户昵称到ID的映射"""
        try:
            return json.loads(settings.USER_ID_MAP) if hasattr(settings, 'USER_ID_MAP') else {}
        except:
            return {}
    
    def get_user_id(self, name: str) -> Optional[str]:
        """根据昵称获取飞书用户ID"""
        if not name:
            return None
        # 先查缓存
        if name in self._user_id_cache:
            return self._user_id_cache[name]
        # 再查配置映射
        user_map = self._get_user_id_map()
        if name in user_map:
            self._user_id_cache[name] = user_map[name]
            return user_map[name]
        return None
    
    def get_user_field_value(self, name: str) -> Any:
        """获取人员字段的值：如果有用户ID则返回对象数组，否则返回文本"""
        if not name:
            return ""
        user_id = self.get_user_id(name)
        if user_id:
            return [{"id": user_id, "type": "user"}]
        return name
    
    def extract_user_name(self, value: Any) -> str:
        """从飞书人员字段提取用户名"""
        if not value:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            if len(value) == 0:
                return ""
            first = value[0]
            if isinstance(first, dict):
                return first.get("name", first.get("en_name", first.get("text", "")))
            return str(first)
        if isinstance(value, dict):
            return value.get("name", value.get("en_name", value.get("text", "")))
        return str(value)
        
    async def _get_tenant_access_token(self) -> str:
        """获取飞书 tenant_access_token"""
        if self.tenant_access_token:
            return self.tenant_access_token
            
        if not self.app_id or not self.app_secret:
            raise ValueError("飞书应用凭证未配置，请检查环境变量 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
            
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={
                "app_id": self.app_id,
                "app_secret": self.app_secret
            })
            data = resp.json()
            if data.get("code") != 0:
                error_msg = data.get("msg", "未知错误")
                raise Exception(f"获取飞书token失败: {error_msg} (code={data.get('code')})")
            self.tenant_access_token = data["tenant_access_token"]
            return self.tenant_access_token
    
    async def _request(self, method: str, url: str, **kwargs) -> Dict:
        """发送带认证的请求"""
        token = await self._get_tenant_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
            data = resp.json()
            if data.get("code") != 0:
                raise Exception(f"API错误: {data}")
            return data.get("data", {})
    
    # ========== 记录操作 ==========
    
    async def list_records(self, table_id: str, filter_str: str = None, page_size: int = 500) -> List[Dict]:
        """查询记录列表"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.BASE_ID}/tables/{table_id}/records"
        params = {"page_size": page_size}
        if filter_str:
            params["filter"] = filter_str
            
        data = await self._request("GET", url, params=params)
        return data.get("items", [])
    
    async def get_record(self, table_id: str, record_id: str) -> Dict:
        """获取单条记录"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.BASE_ID}/tables/{table_id}/records/{record_id}"
        data = await self._request("GET", url)
        # 飞书API返回格式: {"record": {"record_id": "...", "fields": {...}}}
        return data.get("record", {})
    
    async def create_record(self, table_id: str, fields: Dict) -> Dict:
        """创建记录"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.BASE_ID}/tables/{table_id}/records?user_id_type=open_id"
        return await self._request("POST", url, json={"fields": fields})
    
    async def update_record(self, table_id: str, record_id: str, fields: Dict) -> Dict:
        """更新记录"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.BASE_ID}/tables/{table_id}/records/{record_id}?user_id_type=open_id"
        return await self._request("PUT", url, json={"fields": fields})
    
    async def delete_record(self, table_id: str, record_id: str) -> Dict:
        """删除记录"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.BASE_ID}/tables/{table_id}/records/{record_id}"
        return await self._request("DELETE", url)
    
    # ========== 字段操作 ==========
    
    async def list_fields(self, table_id: str) -> List[Dict]:
        """获取表格字段列表"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.BASE_ID}/tables/{table_id}/fields"
        data = await self._request("GET", url)
        return data.get("items", [])
    
    # ========== 群机器人通知 ==========
    
    async def send_webhook(self, text: str, at_users: list = None) -> bool:
        """发送群机器人消息，支持@用户"""
        if not settings.WEBHOOK_URL:
            return False
            
        try:
            # 构建消息内容，支持@用户
            content = {"text": text}
            
            # 如果有用户需要@，添加at标签
            if at_users:
                for user_id in at_users:
                    if user_id:
                        content["text"] += f' <at id="{user_id}"></at>'
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(settings.WEBHOOK_URL, json={
                    "msg_type": "text",
                    "content": content
                })
                return resp.status_code == 200
        except Exception as e:
            print(f"Webhook发送失败: {e}")
            return False

# 全局客户端实例
feishu = FeishuClient()
