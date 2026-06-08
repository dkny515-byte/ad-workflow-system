from fastapi import APIRouter, HTTPException
from typing import List, Optional
from models import OrderCreate, OrderUpdate, OrderResponse
from feishu_client import feishu
from config import settings
import json

router = APIRouter()

# 状态流转规则
STATUS_FLOW = {
    'pending_copy': ['pending', 'designing'],
    'pending': ['designing'],
    'designing': ['review'],
    'review': ['designing', 'client'],
    'client': ['revise', 'done'],
    'revise': ['client'],
    'done': [],
    'cancelled': []
}

STATUS_LABELS = {
    'pending_copy': '待文案', 'pending': '待分配', 'designing': '设计中',
    'review': '待内审', 'client': '提交客户', 'revise': '客户修改',
    'done': '正稿交付', 'cancelled': '已取消'
}

INTERNAL_STATUS_MAP = {
    'pending': '内部待审核', 'revising': '内部修改', 'approved': '内部通过', 'exempt': '内部免审'
}

def _record_to_order(record: dict) -> dict:
    """将飞书记录转换为系统订单格式"""
    fields = record.get("fields", {})
    return {
        "recordId": record.get("record_id", ""),
        "id": fields.get("项目编号", ""),
        "projectName": fields.get("项目简述", ""),
        "workType": fields.get("工作性质", ""),
        "customer": fields.get("客户", ""),
        "dept": fields.get("部门", ""),
        "orderPerson": fields.get("下单人", ""),
        "orderDate": fields.get("下单日期", ""),
        "planDate": fields.get("计划交付日期", ""),
        "makeDate": fields.get("制作日期", ""),
        "priority": fields.get("优先级", "P1"),
        "deliverType": fields.get("交付物类型", ""),
        "size": fields.get("规格尺寸", ""),
        "quantity": fields.get("数量", 1),
        "unit": fields.get("单位", "个"),
        "desc": fields.get("说明", ""),
        "driveLink": fields.get("网盘链接", ""),
        "designer": fields.get("设计师", ""),
        "needCopy": fields.get("需要前策/文案", "否") == "是",
        "copywriter": fields.get("前策/文案", ""),
        "copyContent": fields.get("文案内容", ""),
        "status": _map_status_from_feishu(fields.get("进度状态", "")),
        "internalStatus": _map_internal_status(fields.get("内审状态", "")),
        "version": _parse_version(fields.get("版本号", "v1")),
        "createDate": fields.get("下单日期", ""),
        "ae": fields.get("AE-创建人", ""),
        "fonts": _parse_list(fields.get("使用字体", "")),
        "materialSource": _parse_list(fields.get("素材来源", "")),
        "materialDesc": fields.get("素材说明", ""),
        "portrait": fields.get("肖像权", ""),
        "designerSubmitted": fields.get("设计师是否提交", "") == "是",
        "actualDate": fields.get("实际交付日期", ""),
        "reviewer": fields.get("指定内审员", "")
    }

def _order_to_fields(order: dict) -> dict:
    """将系统订单转换为飞书字段格式"""
    return {
        "项目编号": order.get("id", ""),
        "项目简述": order.get("projectName", ""),
        "工作性质": order.get("workType", ""),
        "客户": order.get("customer", ""),
        "部门": order.get("dept", ""),
        "下单人": order.get("orderPerson", ""),
        "下单日期": order.get("orderDate", ""),
        "计划交付日期": order.get("planDate", ""),
        "制作日期": order.get("makeDate", ""),
        "优先级": order.get("priority", "P1"),
        "交付物类型": order.get("deliverType", ""),
        "规格尺寸": order.get("size", ""),
        "数量": order.get("quantity", 1),
        "单位": order.get("unit", "个"),
        "说明": order.get("desc", ""),
        "网盘链接": order.get("driveLink", ""),
        "设计师": order.get("designer", ""),
        "需要前策/文案": "是" if order.get("needCopy") else "否",
        "前策/文案": order.get("copywriter", ""),
        "文案内容": order.get("copyContent", ""),
        "进度状态": _map_status_to_feishu(order.get("status", "")),
        "内审状态": _map_internal_status_to_feishu(order.get("internalStatus", "")),
        "版本号": f"v{order.get('version', 1)}",
        "AE-创建人": order.get("ae", ""),
        "使用字体": _format_list(order.get("fonts", [])),
        "素材来源": _format_list(order.get("materialSource", [])),
        "素材说明": order.get("materialDesc", ""),
        "肖像权": order.get("portrait", ""),
        "设计师是否提交": "是" if order.get("designerSubmitted") else "否",
        "实际交付日期": order.get("actualDate", ""),
        "指定内审员": order.get("reviewer", "")
    }

def _map_status_from_feishu(status: str) -> str:
    """飞书状态 → 系统状态"""
    mapping = {
        '待文案': 'pending_copy', '待分配': 'pending', '设计中': 'designing',
        '待内审': 'review', '提交客户': 'client', '客户修改': 'revise',
        '正稿交付': 'done', '已取消': 'cancelled'
    }
    return mapping.get(status, status)

def _map_status_to_feishu(status: str) -> str:
    """系统状态 → 飞书状态"""
    mapping = {
        'pending_copy': '待文案', 'pending': '待分配', 'designing': '设计中',
        'review': '待内审', 'client': '提交客户', 'revise': '客户修改',
        'done': '正稿交付', 'cancelled': '已取消'
    }
    return mapping.get(status, status)

def _map_internal_status(status: str) -> str:
    """飞书内审状态 → 系统内审状态"""
    mapping = {
        '内部待审核': 'pending', '内部修改': 'revising',
        '内部通过': 'approved', '内部免审': 'exempt'
    }
    return mapping.get(status, status)

def _map_internal_status_to_feishu(status: str) -> str:
    """系统内审状态 → 飞书内审状态"""
    mapping = {
        'pending': '内部待审核', 'revising': '内部修改',
        'approved': '内部通过', 'exempt': '内部免审'
    }
    return mapping.get(status, "")

def _parse_version(version_str: str) -> int:
    """解析版本号 v1 → 1"""
    if not version_str:
        return 1
    try:
        return int(version_str.replace("v", "").replace("V", ""))
    except:
        return 1

def _parse_list(value) -> list:
    """解析列表字段"""
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []

def _format_list(value: list) -> str:
    """格式化列表为字符串"""
    if not value:
        return ""
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)

@router.get("/", response_model=List[OrderResponse])
async def list_orders(
    status: Optional[str] = None,
    customer: Optional[str] = None,
    designer: Optional[str] = None,
    ae: Optional[str] = None
):
    """查询工单列表"""
    try:
        records = await feishu.list_records(settings.ORDERS_TABLE_ID)
        orders = [_record_to_order(r) for r in records]
        
        # 过滤
        if status:
            orders = [o for o in orders if o["status"] == status]
        if customer:
            orders = [o for o in orders if o["customer"] == customer]
        if designer:
            orders = [o for o in orders if o["designer"] == designer]
        if ae:
            orders = [o for o in orders if o["ae"] == ae]
            
        return orders
    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n{traceback.format_exc()}"
        print(f"[ERROR] list_orders: {error_detail}")
        raise HTTPException(status_code=500, detail=str(e) or "后端连接飞书表格失败，请检查环境变量和权限配置")

@router.get("/{record_id}", response_model=OrderResponse)
async def get_order(record_id: str):
    """获取单条工单"""
    try:
        record = await feishu.get_record(settings.ORDERS_TABLE_ID, record_id)
        return _record_to_order(record)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/", response_model=OrderResponse)
async def create_order(order: OrderCreate):
    """创建工单"""
    try:
        # 生成编号
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        short = order.customer[:4] if order.customer else "NEW"
        
        # 获取当前记录数用于序号
        records = await feishu.list_records(settings.ORDERS_TABLE_ID, page_size=1)
        seq = len(records) + 1 if records else 1
        order_id = f"{short}-{date_str}-{seq:03d}"
        
        # 确定初始状态
        initial_status = 'pending_copy' if order.needCopy else ('designing' if order.designer else 'pending')
        
        # 构建字段
        fields = {
            "项目编号": order_id,
            "项目简述": order.projectName,
            "工作性质": order.workType,
            "客户": order.customer,
            "部门": order.dept or "",
            "下单人": order.orderPerson or "",
            "下单日期": str(order.orderDate),
            "计划交付日期": str(order.planDate),
            "制作日期": str(order.makeDate) if order.makeDate else "",
            "优先级": order.priority,
            "交付物类型": order.deliverType or "",
            "规格尺寸": order.size or "",
            "数量": order.quantity,
            "单位": order.unit or "个",
            "说明": order.desc or "",
            "设计师": order.designer or "",
            "需要前策/文案": "是" if order.needCopy else "否",
            "前策/文案": order.copywriter or "",
            "进度状态": _map_status_to_feishu(initial_status),
            "版本号": "v1",
            "AE-创建人": "当前AE",  # 实际应从登录用户获取
            "指定内审员": order.reviewer or settings.REVIEWERS[0] if settings.REVIEWERS else ""
        }
        
        result = await feishu.create_record(settings.ORDERS_TABLE_ID, fields)
        
        # 发送通知
        if order.designer:
            await feishu.send_webhook(
                f"📋 新工单创建\n项目：【{order.workType}】{order.projectName}\n"
                f"客户：{order.customer} · {order.dept or ''}\n"
                f"分配设计师：{order.designer}\n交付日期：{order.planDate}"
            )
        
        return _record_to_order(result.get("record", {}))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{record_id}", response_model=OrderResponse)
async def update_order(record_id: str, update: OrderUpdate):
    """更新工单"""
    try:
        # 获取当前记录
        current = await feishu.get_record(settings.ORDERS_TABLE_ID, record_id)
        current_order = _record_to_order(current)
        
        # 构建更新字段
        fields = {}
        
        if update.status is not None:
            fields["进度状态"] = _map_status_to_feishu(update.status)
            
            # 状态变更时的自动逻辑
            if update.status == 'review':
                fields["内审状态"] = "内部待审核"
                fields["设计师是否提交"] = "是"
            elif update.status == 'client':
                fields["内审状态"] = "内部通过"
            elif update.status == 'done':
                fields["实际交付日期"] = datetime.now().strftime("%Y-%m-%d")
            elif update.status == 'revise':
                # 版本号+1
                current_version = current_order.get("version", 1)
                fields["版本号"] = f"v{current_version + 1}"
        
        if update.internalStatus is not None:
            fields["内审状态"] = _map_internal_status_to_feishu(update.internalStatus)
        
        if update.designer is not None:
            fields["设计师"] = update.designer
        
        if update.makeDate is not None:
            fields["制作日期"] = str(update.makeDate)
        
        if update.priority is not None:
            fields["优先级"] = update.priority
        
        if update.desc is not None:
            fields["说明"] = update.desc
        
        if update.planDate is not None:
            fields["计划交付日期"] = str(update.planDate)
        
        if update.driveLink is not None:
            fields["网盘链接"] = update.driveLink
        
        if update.fonts is not None:
            fields["使用字体"] = _format_list(update.fonts)
        
        if update.materialSource is not None:
            fields["素材来源"] = _format_list(update.materialSource)
        
        if update.materialDesc is not None:
            fields["素材说明"] = update.materialDesc
        
        if update.portrait is not None:
            fields["肖像权"] = update.portrait
        
        if update.copyContent is not None:
            fields["文案内容"] = update.copyContent
            # 文案提交后状态变为待设计
            fields["进度状态"] = "待分配" if not current_order.get("designer") else "设计中"
        
        if update.designerSubmitted is not None:
            fields["设计师是否提交"] = "是" if update.designerSubmitted else "否"
        
        if update.actualDate is not None:
            fields["实际交付日期"] = str(update.actualDate)
        
        result = await feishu.update_record(settings.ORDERS_TABLE_ID, record_id, fields)
        
        # 发送状态变更通知
        if update.status and update.status != current_order.get("status"):
            new_status_label = STATUS_LABELS.get(update.status, update.status)
            await feishu.send_webhook(
                f"📢 工单状态变更\n项目：{current_order.get('projectName')}\n"
                f"新状态：{new_status_label}\n"
                f"设计师：{current_order.get('designer', '未分配')}"
            )
        
        return _record_to_order(result.get("record", current))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{record_id}")
async def delete_order(record_id: str):
    """删除工单"""
    try:
        await feishu.delete_record(settings.ORDERS_TABLE_ID, record_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from datetime import datetime
