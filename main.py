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

@app.get("/test-record-conversion")
async def test_record_conversion():
    """测试记录转换函数"""
    try:
        from feishu_client import feishu
        from config import settings
        from routers.orders import _record_to_order
        
        records = await feishu.list_records(settings.ORDERS_TABLE_ID)
        
        results = []
        errors = []
        for r in records[:5]:  # 只测试前5条
            try:
                order = _record_to_order(r)
                results.append({
                    "record_id": r.get("record_id"),
                    "status": "ok",
                    "project": order.get("projectName")
                })
            except Exception as e:
                import traceback
                errors.append({
                    "record_id": r.get("record_id"),
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "fields": list(r.get("fields", {}).keys())
                })
        
        return {
            "status": "ok",
            "total_tested": len(records[:5]),
            "success": len(results),
            "errors": len(errors),
            "results": results,
            "error_details": errors
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.get("/table-fields")
async def table_fields():
    """获取订单表格的所有字段名"""
    try:
        from feishu_client import feishu
        from config import settings
        
        fields = await feishu.list_fields(settings.ORDERS_TABLE_ID)
        
        return {
            "status": "ok",
            "field_count": len(fields),
            "fields": [
                {
                    "field_id": f.get("field_id"),
                    "field_name": f.get("field_name"),
                    "type": f.get("type"),
                }
                for f in fields
            ]
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.get("/debug-record/{record_id}")
async def debug_record(record_id: str):
    """调试单条记录"""
    try:
        from feishu_client import feishu
        from config import settings
        from routers.orders import _record_to_order
        
        record = await feishu.get_record(settings.ORDERS_TABLE_ID, record_id)
        order = _record_to_order(record)
        
        return {
            "status": "ok",
            "record_id": record_id,
            "order": order
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "raw_record": record if 'record' in locals() else None
        }

@app.get("/debug-all-records")
async def debug_all_records():
    """调试所有记录"""
    try:
        from feishu_client import feishu
        from config import settings
        from routers.orders import _record_to_order
        
        records = await feishu.list_records(settings.ORDERS_TABLE_ID)
        
        results = []
        errors = []
        for r in records:
            try:
                order = _record_to_order(r)
                results.append({"record_id": r.get("record_id"), "status": "ok", "project": order.get("projectName")})
            except Exception as e:
                errors.append({
                    "record_id": r.get("record_id"),
                    "error": str(e),
                    "fields": list(r.get("fields", {}).keys())
                })
        
        return {
            "status": "ok",
            "total": len(records),
            "success": len(results),
            "errors": len(errors),
            "error_details": errors[:5]  # 只返回前5个错误
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.get("/test-orders")
async def test_orders():
    """测试订单列表"""
    try:
        from feishu_client import feishu
        from config import settings
        from routers.orders import _record_to_order
        
        records = await feishu.list_records(settings.ORDERS_TABLE_ID)
        
        results = []
        errors = []
        for r in records[:3]:
            try:
                order = _record_to_order(r)
                results.append({"record_id": r.get("record_id"), "status": "ok", "project": order.get("projectName")})
            except Exception as e:
                import traceback
                errors.append({
                    "record_id": r.get("record_id"),
                    "error": str(e),
                    "traceback": traceback.format_exc()
                })
        
        return {
            "status": "ok",
            "total_records": len(records),
            "tested": len(records[:3]),
            "success": len(results),
            "errors": len(errors),
            "results": results,
            "error_details": errors
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }

# API路由（必须在静态文件挂载之前）
app.include_router(orders.router, prefix="/api/orders", tags=["工单"])
app.include_router(customers.router, prefix="/api/customers", tags=["客户"])
app.include_router(fonts.router, prefix="/api/fonts", tags=["字体"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["通知"])

# 静态文件（前端界面）- 放在最后，避免拦截API路由
app.mount("/", StaticFiles(directory="static", html=True), name="static")
