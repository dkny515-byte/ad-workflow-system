from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from routers import orders, customers, fonts, notifications
import config

app = FastAPI(title="广告工单系统", version="1.0.0")

# CORS - 允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 健康检查（必须在静态文件挂载之前）
@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}

# 诊断端点（排查环境变量和配置）
@app.get("/diagnostic")
async def diagnostic():
    """诊断后端配置状态（不返回敏感信息）"""
    diag = config.settings.get_diagnostic()
    
    # 尝试测试飞书连接
    feishu_test = {"tested": False, "success": False, "error": None}
    if diag["feishu_app_id_configured"] and diag["feishu_app_secret_configured"]:
        try:
            from feishu_client import FeishuClient
            client = FeishuClient()
            # 只测试token获取，不实际查询数据
            import asyncio
            await client._get_tenant_access_token()
            feishu_test = {"tested": True, "success": True, "error": None}
        except Exception as e:
            feishu_test = {"tested": True, "success": False, "error": str(e)}
    
    return {
        "status": "ok",
        "config": diag,
        "feishu_connection": feishu_test,
    }

# API路由（必须在静态文件挂载之前）
app.include_router(orders.router, prefix="/api/orders", tags=["工单"])
app.include_router(customers.router, prefix="/api/customers", tags=["客户"])
app.include_router(fonts.router, prefix="/api/fonts", tags=["字体"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["通知"])

# 静态文件（前端界面）- 放在最后，避免拦截API路由
app.mount("/", StaticFiles(directory="static", html=True), name="static")
