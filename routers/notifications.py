from fastapi import APIRouter, HTTPException
from models import WebhookMessage
from feishu_client import feishu

router = APIRouter()

@router.post("/webhook")
async def send_webhook_message(message: WebhookMessage):
    """发送群机器人消息"""
    try:
        success = await feishu.send_webhook(message.text)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/status-change")
async def notify_status_change(
    project_name: str,
    status: str,
    designer: str = None,
    ae: str = None,
    version: int = 1
):
    """状态变更通知模板"""
    try:
        status_labels = {
            'pending_copy': '待文案', 'pending': '待分配', 'designing': '设计中',
            'review': '待内审', 'client': '提交客户', 'revise': '客户修改',
            'done': '正稿交付', 'cancelled': '已取消'
        }
        
        label = status_labels.get(status, status)
        text = f"📢 工单状态变更\n项目：{project_name}\n新状态：{label}"
        
        if designer:
            text += f"\n设计师：{designer}"
        if ae:
            text += f"\nAE：{ae}"
        if version > 1:
            text += f"\n版本：v{version}"
        
        success = await feishu.send_webhook(text)
        return {"success": success, "message": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
