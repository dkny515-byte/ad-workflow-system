import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 飞书应用凭证
    FEISHU_APP_ID: str = os.getenv("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET: str = os.getenv("FEISHU_APP_SECRET", "")
    
    # 多维表格配置
    BASE_ID: str = os.getenv("BASE_ID", "")
    ORDERS_TABLE_ID: str = os.getenv("ORDERS_TABLE_ID", "")
    CUSTOMERS_TABLE_ID: str = os.getenv("CUSTOMERS_TABLE_ID", "")
    FONTS_TABLE_ID: str = os.getenv("FONTS_TABLE_ID", "")
    
    # 群机器人Webhook
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    
    # 人员配置（JSON格式）— 使用飞书真实昵称，通过环境变量配置
    DESIGNERS: str = os.getenv("DESIGNERS", "[]")
    OTHER_STAFF: str = os.getenv("OTHER_STAFF", "[]")
    REVIEWERS: str = os.getenv("REVIEWERS", "[]")
    
    # 人员昵称→飞书用户ID映射（open_id格式），通过环境变量配置
    USER_ID_MAP: str = os.getenv("USER_ID_MAP", "{}")
    
    # 部门ID列表（用于自动同步通讯录），通过环境变量配置
    DEPT_IDS: str = os.getenv("DEPT_IDS", "[]")
    
    class Config:
        env_file = ".env"
    
    def get_user_id_map(self) -> dict:
        """解析用户ID映射"""
        import json
        try:
            return json.loads(self.USER_ID_MAP)
        except:
            return {}
    
    def get_dept_ids(self) -> list:
        """解析部门ID列表"""
        import json
        try:
            return json.loads(self.DEPT_IDS)
        except:
            return []
    
    def get_diagnostic(self) -> dict:
        """返回配置诊断信息（隐藏敏感值）"""
        return {
            "feishu_app_id_configured": bool(self.FEISHU_APP_ID),
            "feishu_app_id_length": len(self.FEISHU_APP_ID) if self.FEISHU_APP_ID else 0,
            "feishu_app_secret_configured": bool(self.FEISHU_APP_SECRET),
            "feishu_app_secret_length": len(self.FEISHU_APP_SECRET) if self.FEISHU_APP_SECRET else 0,
            "base_id_configured": bool(self.BASE_ID),
            "base_id_length": len(self.BASE_ID) if self.BASE_ID else 0,
            "orders_table_configured": bool(self.ORDERS_TABLE_ID),
            "customers_table_configured": bool(self.CUSTOMERS_TABLE_ID),
            "fonts_table_configured": bool(self.FONTS_TABLE_ID),
            "webhook_configured": bool(self.WEBHOOK_URL),
            "user_id_map_count": len(self.get_user_id_map()),
            "dept_ids_count": len(self.get_dept_ids()),
        }

settings = Settings()
