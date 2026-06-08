from fastapi import APIRouter, HTTPException
from typing import List, Optional
from datetime import datetime
import re
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


# ========== 字段提取辅助函数 ==========

def _strip_emoji(text: str) -> str:
    """去掉文本中的emoji，保留纯中文"""
    if not text:
        return ""
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"
        "\U00002600-\U000026FF"
        "\U00002700-\U000027BF"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub(r'', text).strip()

def _extract_text(value):
    """从飞书富文本/文本字段提取纯文本"""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = []
        for item in value:
            if isinstance(item, dict) and "text" in item:
                texts.append(str(item["text"]))
            elif isinstance(item, str):
                texts.append(item)
        return "".join(texts)
    return str(value)

def _extract_date(value):
    """从飞书日期字段提取日期字符串"""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(value / 1000)
            return dt.strftime("%Y-%m-%d")
        except:
            return str(value)
    return str(value)

def _extract_user(value):
    """从飞书用户字段提取用户名"""
    return feishu.extract_user_name(value)

def _extract_option(value):
    """从飞书选项字段提取文本"""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if len(value) == 0:
            return ""
        first = value[0]
        if isinstance(first, str):
            return ", ".join(value)
        if isinstance(first, dict):
            return ", ".join([str(v.get("text", v)) for v in value])
    if isinstance(value, dict):
        return value.get("text", str(value))
    return str(value)

def _extract_list(value):
    """从飞书字段提取字符串列表"""
    if not value:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict) and "text" in item:
                result.append(str(item["text"]))
            elif isinstance(item, str):
                result.append(item)
        return result
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(value)]


# ========== 状态映射 ==========

def _map_status_from_feishu(status: str) -> str:
    """飞书状态 → 系统状态（保留emoji+中文，宽松匹配）"""
    if not status:
        return ""
    clean = status.strip()
    # 宽松匹配：包含关键词即可
    if '文案' in clean:
        return 'pending_copy'
    if '分配' in clean or '反馈' in clean:
        return 'pending'
    if '设计' in clean:
        return 'designing'
    if '内审' in clean:
        return 'review'
    if '提交' in clean or '客户' in clean:
        return 'client'
    if '修改' in clean:
        return 'revise'
    if '交付' in clean or '完成' in clean or '正稿' in clean:
        return 'done'
    if '取消' in clean:
        return 'cancelled'
    return clean

def _map_status_to_feishu(status: str) -> str:
    """系统状态 → 飞书状态（带emoji前缀）"""
    mapping = {
        'pending_copy': '🟡 待文案',
        'pending': '🔵 待分配',
        'designing': '🟣 设计中',
        'review': '⭕️ 待内审',
        'client': '🟢 提交客户',
        'revise': '🟠 客户修改',
        'done': '✅ 正稿交付',
        'cancelled': '❌ 已取消'
    }
    return mapping.get(status, status)

def _map_internal_status(status: str) -> str:
    """飞书内审状态 → 系统内审状态（保留emoji+中文）"""
    if not status:
        return ""
    clean = status.strip()
    if '待审核' in clean or '待审' in clean:
        return 'pending'
    if '修改' in clean:
        return 'revising'
    if '通过' in clean:
        return 'approved'
    if '免审' in clean:
        return 'exempt'
    return clean

def _map_internal_status_to_feishu(status: str) -> str:
    """系统内审状态 → 飞书内审状态（带emoji前缀）"""
    mapping = {
        'pending': '🟡 内部待审核',
        'revising': '🔴 内部修改',
        'approved': '🟢 内部通过',
        'exempt': '⚪️ 内部免审'
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


# ========== 记录转换 ==========

def _record_to_order(record: dict) -> dict:
    """将飞书记录转换为系统订单格式"""
    fields = record.get("fields", {})
    return {
        "recordId": record.get("record_id", ""),
        "id": _extract_text(fields.get("项目编号", "")),
        "projectName": _extract_text(fields.get("项目简述", "")),
        "workType": _extract_text(fields.get("工作性质", "")),
        "customer": _extract_text(fields.get("客户", "")),
        "dept": _extract_text(fields.get("部门", "")),
        "orderPerson": _extract_text(fields.get("下单人", "")),
        "orderDate": _extract_date(fields.get("下单日期", "")),
        "planDate": _extract_date(fields.get("计划交付日期", "")),
        "makeDate": _extract_date(fields.get("制作日期", "")),
        "priority": _extract_text(fields.get("优先级", "P1")),
        "deliverType": _extract_text(fields.get("交付物类型", "")),
        "size": _extract_text(fields.get("规格尺寸", "")),
        "quantity": fields.get("数量", 1) if isinstance(fields.get("数量"), (int, float)) else 1,
        "unit": _extract_text(fields.get("单位", "个")),
        "desc": _extract_text(fields.get("说明", "")),
        "driveLink": _extract_text(fields.get("网盘链接", "")),
        "designer": _extract_user(fields.get("设计师 (人员 )", "")),
        "needCopy": _extract_text(fields.get("需要前策|文案", "否")) == "是",
        "copywriter": _extract_user(fields.get("前策|文案 (人员 )", "")),
        "copyContent": _extract_text(fields.get("文案内容", "")),
        "status": _map_status_from_feishu(_extract_text(fields.get("进度状态", ""))),
        "internalStatus": _map_internal_status(_extract_text(fields.get("内审状态", ""))),
        "version": fields.get("版本号", 1) if isinstance(fields.get("版本号"), (int, float)) else _parse_version(_extract_text(fields.get("版本号", "v1"))),
        "createDate": _extract_date(fields.get("下单日期", "")),
        "ae": _extract_user(fields.get("AE-创建人", "")),
        "fonts": _extract_list(fields.get("使用字体", "")),
        "materialSource": _extract_list(fields.get("素材来源", "")),
        "materialDesc": _extract_text(fields.get("素材说明", "")),
        "portrait": _extract_option(fields.get("肖像权", "")),
        "designerSubmitted": _extract_text(fields.get("设计师提交", "")) == "是",
        "actualDate": _extract_date(fields.get("实际交付日期", "")),
        "reviewer": _extract_user(fields.get("指定内审员", ""))
    }

def _date_to_timestamp(date_str: str) -> int:
    """将日期字符串转为飞书需要的Unix时间戳（毫秒）"""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return int(dt.timestamp() * 1000)
    except:
        return None

def _order_to_fields(order: dict) -> dict:
    """将系统订单转换为飞书字段格式"""
    fields = {
        "项目编号": order.get("id", ""),
        "项目简述": order.get("projectName", ""),
        "工作性质": order.get("workType", ""),
        "客户": order.get("customer", ""),
        "部门": order.get("dept", ""),
        "下单人": order.get("orderPerson", ""),
        "下单日期": _date_to_timestamp(order.get("orderDate", "")),
        "计划交付日期": _date_to_timestamp(order.get("planDate", "")),
        "制作日期": _date_to_timestamp(order.get("makeDate", "")),
        "优先级": order.get("priority", "P1"),
        "交付物类型": order.get("deliverType", ""),
        "规格尺寸": order.get("size", ""),
        "数量": order.get("quantity", 1),
        "单位": order.get("unit", "个"),
        "说明": order.get("desc", ""),
        "网盘链接": order.get("driveLink", ""),
        "设计师": feishu.get_user_field_value(order.get("designer", "")),
        "需要前策|文案": "是" if order.get("needCopy") else "否",
        "前策|文案 (人员 )": feishu.get_user_field_value(order.get("copywriter", "")),
        "文案内容": order.get("copyContent", ""),  # 可能不存在，会被过滤
        "进度状态": _map_status_to_feishu(order.get("status", "")),
        "内审状态": _map_internal_status_to_feishu(order.get("internalStatus", "")),
        "版本号": order.get('version', 1),
        "AE-创建人": feishu.get_user_field_value(order.get("ae", "")),
        "使用字体": _extract_list(order.get("fonts", [])),
        "素材来源": _extract_list(order.get("materialSource", [])),
        "素材说明": order.get("materialDesc", ""),
        "肖像权": order.get("portrait", ""),
        "设计师提交": "是" if order.get("designerSubmitted") else "否",
        "实际交付日期": _date_to_timestamp(order.get("actualDate", "")),
        "指定内审员": feishu.get_user_field_value(order.get("reviewer", ""))
    }
    # 过滤空值（但保留0和False）
    return {k: v for k, v in fields.items() if v is not None and v != "" and v != []}


# ========== API 路由 ==========

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
        date_str = datetime.now().strftime("%Y%m%d")
        short = order.customer[:4] if order.customer else "NEW"
        
        # 获取当前记录数用于序号
        records = await feishu.list_records(settings.ORDERS_TABLE_ID)
        seq = len(records) + 1 if records else 1
        order_id = f"{short}-{date_str}-{seq:03d}"
        
        # 确定初始状态
        initial_status = 'pending_copy' if order.needCopy else ('designing' if order.designer else 'pending')
        
        # 构建字段（跳过级联单选字段，这些需要在飞书表格中手动设置）
        fields = {
            "项目编号": order_id,
            "项目简述": order.projectName,
            "工作性质": order.workType,
            "客户": order.customer,
            # "部门": order.dept or "",  # 级联单选，API不支持直接写入
            "下单人": order.orderPerson or "",
            "下单日期": _date_to_timestamp(str(order.orderDate)),
            "计划交付日期": _date_to_timestamp(str(order.planDate)),
            "制作日期": _date_to_timestamp(str(order.makeDate)) if order.makeDate else None,
            "优先级": order.priority,
            "交付物类型": order.deliverType or "",
            "规格尺寸": order.size or "",
            "数量": order.quantity,
            "单位": order.unit or "个",
            "说明": order.desc or "",
            "设计师 (人员 )": feishu.get_user_field_value(order.designer or ""),
            "需要前策|文案": "是" if order.needCopy else "否",
            "前策|文案 (人员 )": feishu.get_user_field_value(order.copywriter or ""),
            "进度状态": _map_status_to_feishu(initial_status),
            "版本号": 1,
            "AE-创建人": feishu.get_user_field_value("当前AE"),
            "指定内审员": feishu.get_user_field_value(order.reviewer or "")
        }
        
        # 过滤空值（但保留0和False）
        fields = {k: v for k, v in fields.items() if v is not None and v != "" and v != []}
        
        result = await feishu.create_record(settings.ORDERS_TABLE_ID, fields)
        
        # 发送通知
        designer_name = order.designer or ""
        designer_id = feishu.get_user_id(designer_name) if designer_name else None
        
        if order.designer:
            await feishu.send_webhook(
                f"📋 新工单分配给你\n项目：【{order.workType}】{order.projectName}\n"
                f"客户：{order.customer} · {order.dept or ''}\n"
                f"交付日期：{order.planDate}\n请尽快开始设计工作",
                at_users=[designer_id] if designer_id else None,
                title="📋 新工单分配"
            )
        
        return _record_to_order(result)
    except Exception as e:
        import traceback
        print(f"[ERROR] create_order: {str(e)}\n{traceback.format_exc()}")
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
                fields["内审状态"] = "🟡 内部待审核"
                fields["设计师提交"] = True  # Checkbox字段需要布尔值
            elif update.status == 'client':
                fields["内审状态"] = "🟢 内部通过"
            elif update.status == 'done':
                # 实际交付日期字段不存在，跳过
                pass
            elif update.status == 'revise':
                # 版本号+1
                current_version = current_order.get("version", 1)
                fields["版本号"] = current_version + 1
        
        if update.internalStatus is not None:
            fields["内审状态"] = _map_internal_status_to_feishu(update.internalStatus)
        
        if update.designer is not None:
            fields["设计师 (人员 )"] = feishu.get_user_field_value(update.designer)
        
        if update.makeDate is not None:
            fields["制作日期"] = _date_to_timestamp(str(update.makeDate))
        
        if update.priority is not None:
            fields["优先级"] = update.priority
        
        if update.desc is not None:
            fields["说明"] = update.desc
        
        if update.planDate is not None:
            fields["计划交付日期"] = _date_to_timestamp(str(update.planDate))
        
        if update.driveLink is not None:
            fields["网盘链接"] = update.driveLink
        
        if update.fonts is not None:
            fields["使用字体"] = _extract_list(update.fonts)
        
        if update.materialSource is not None:
            fields["素材来源"] = _extract_list(update.materialSource)
        
        if update.materialDesc is not None:
            fields["素材说明"] = update.materialDesc
        
        if update.portrait is not None:
            fields["肖像权"] = update.portrait
        
        if update.copyContent is not None:
            # 文案内容字段不存在于表格中，跳过
            # 文案提交后状态变为待设计
            fields["进度状态"] = "🔵 待分配" if not current_order.get("designer") else "🟣 设计中"
        
        if update.designerSubmitted is not None:
            fields["设计师提交"] = True if update.designerSubmitted else False
        
        # 实际交付日期字段不存在，跳过
        # if update.actualDate is not None:
        #     fields["实际交付日期"] = _date_to_timestamp(str(update.actualDate))
        
        # 过滤空值（但保留0和False）
        fields = {k: v for k, v in fields.items() if v is not None and v != "" and v != []}
        
        result = await feishu.update_record(settings.ORDERS_TABLE_ID, record_id, fields)
        
        # 发送状态变更通知 - 根据状态@下一步办理者
        if update.status and update.status != current_order.get("status"):
            new_status_label = STATUS_LABELS.get(update.status, update.status)
            
            # 确定需要@谁
            at_user_id = None
            notify_text = ""
            title = "📢 工单状态变更"
            
            if update.status == 'review':
                # 设计师提交内审 → @内审员
                reviewer_name = current_order.get('reviewer', '')
                reviewer_id = feishu.get_user_id(reviewer_name) if reviewer_name else None
                at_user_id = reviewer_id
                notify_text = (f"⭕️ 待内审\n项目：{current_order.get('projectName')}\n"
                              f"设计师：{current_order.get('designer', '未分配')}\n"
                              f"请尽快审核")
                title = "⭕️ 工单待内审"
                
            elif update.status == 'client':
                # 内审通过提交客户 → @AE
                ae_name = current_order.get('ae', '')
                ae_id = feishu.get_user_id(ae_name) if ae_name else None
                at_user_id = ae_id
                notify_text = (f"🟢 已内审通过，请提交客户\n"
                              f"项目：{current_order.get('projectName')}\n"
                              f"设计师：{current_order.get('designer', '未分配')}")
                title = "🟢 内审通过"
                
            elif update.status == 'revise':
                # 客户反馈修改 → @设计师
                designer_name = current_order.get('designer', '')
                designer_id = feishu.get_user_id(designer_name) if designer_name else None
                at_user_id = designer_id
                notify_text = (f"🟠 客户要求修改\n"
                              f"项目：{current_order.get('projectName')}\n"
                              f"请查看修改意见并调整")
                title = "🟠 客户修改"
                
            elif update.status == 'done':
                # 正稿交付 → @AE
                ae_name = current_order.get('ae', '')
                ae_id = feishu.get_user_id(ae_name) if ae_name else None
                at_user_id = ae_id
                notify_text = (f"✅ 正稿已交付\n"
                              f"项目：{current_order.get('projectName')}\n"
                              f"请归档并发送给客户")
                title = "✅ 正稿交付"
                
            elif update.status == 'designing':
                # 文案完成/分配设计师 → @设计师
                designer_name = current_order.get('designer', '')
                designer_id = feishu.get_user_id(designer_name) if designer_name else None
                at_user_id = designer_id
                notify_text = (f"🟣 可以开始设计\n"
                              f"项目：{current_order.get('projectName')}\n"
                              f"请查看需求并开始设计")
                title = "🟣 开始设计"
            
            if notify_text:
                await feishu.send_webhook(
                    notify_text,
                    at_users=[at_user_id] if at_user_id else None,
                    title=title
                )
        
        return _record_to_order(result)
    except Exception as e:
        import traceback
        print(f"[ERROR] update_order: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{record_id}")
async def delete_order(record_id: str):
    """删除工单"""
    try:
        await feishu.delete_record(settings.ORDERS_TABLE_ID, record_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
