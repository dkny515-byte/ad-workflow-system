from fastapi import APIRouter, HTTPException
from typing import List, Optional
from datetime import datetime
import re
from models import OrderCreate, OrderUpdate, OrderResponse
from feishu_client import feishu
from config import settings
import json

router = APIRouter()

# ========== v5 状态机定义 ==========

# 8个状态
STATUS_NEW = 'new'
STATUS_PENDING_COPY = 'pending_copy'
STATUS_COPY_CONFIRM = 'copy_confirm'
STATUS_PENDING_DESIGN = 'pending_design'
STATUS_PENDING_REVIEW = 'pending_review'
STATUS_NEEDS_REVISE = 'needs_revise'
STATUS_PENDING_CLIENT = 'pending_client'
STATUS_DONE = 'done'
STATUS_CANCELLED = 'cancelled'

ALL_STATUSES = [
    STATUS_NEW, STATUS_PENDING_COPY, STATUS_COPY_CONFIRM,
    STATUS_PENDING_DESIGN, STATUS_PENDING_REVIEW, STATUS_NEEDS_REVISE,
    STATUS_PENDING_CLIENT, STATUS_DONE, STATUS_CANCELLED
]

# 状态流转规则：从当前状态可以流转到哪些状态
STATUS_FLOW = {
    STATUS_NEW: [STATUS_PENDING_COPY, STATUS_PENDING_DESIGN, STATUS_CANCELLED],
    STATUS_PENDING_COPY: [STATUS_COPY_CONFIRM, STATUS_CANCELLED],
    STATUS_COPY_CONFIRM: [STATUS_PENDING_DESIGN, STATUS_PENDING_COPY, STATUS_CANCELLED],
    STATUS_PENDING_DESIGN: [STATUS_PENDING_REVIEW, STATUS_CANCELLED],
    STATUS_PENDING_REVIEW: [STATUS_PENDING_CLIENT, STATUS_NEEDS_REVISE, STATUS_CANCELLED],
    STATUS_NEEDS_REVISE: [STATUS_PENDING_REVIEW, STATUS_CANCELLED],
    STATUS_PENDING_CLIENT: [STATUS_DONE, STATUS_NEEDS_REVISE, STATUS_CANCELLED],
    STATUS_DONE: [],
    STATUS_CANCELLED: []
}

STATUS_LABELS = {
    STATUS_NEW: '新建',
    STATUS_PENDING_COPY: '待文案',
    STATUS_COPY_CONFIRM: '文案待确认',
    STATUS_PENDING_DESIGN: '待设计',
    STATUS_PENDING_REVIEW: '待内审',
    STATUS_NEEDS_REVISE: '需修改',
    STATUS_PENDING_CLIENT: '待客户反馈',
    STATUS_DONE: '已完稿',
    STATUS_CANCELLED: '已取消'
}

STATUS_EMOJI = {
    STATUS_NEW: '⚪️',
    STATUS_PENDING_COPY: '🟡',
    STATUS_COPY_CONFIRM: '🟡',
    STATUS_PENDING_DESIGN: '🔵',
    STATUS_PENDING_REVIEW: '🟠',
    STATUS_NEEDS_REVISE: '🔴',
    STATUS_PENDING_CLIENT: '🟢',
    STATUS_DONE: '✅',
    STATUS_CANCELLED: '❌'
}

# ========== 字段提取辅助函数 ==========

def _strip_emoji(text: str) -> str:
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
    return feishu.extract_user_name(value)

def _extract_option(value):
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
    if not status:
        return ""
    clean = _strip_emoji(status.strip())
    # v5 状态匹配
    if clean == '新建':
        return STATUS_NEW
    if '文案' in clean and '确认' not in clean:
        return STATUS_PENDING_COPY
    if '文案' in clean and '确认' in clean:
        return STATUS_COPY_CONFIRM
    if '设计' in clean:
        return STATUS_PENDING_DESIGN
    if '内审' in clean:
        return STATUS_PENDING_REVIEW
    if '修改' in clean and '客户' not in clean:
        return STATUS_NEEDS_REVISE
    if '客户' in clean or '反馈' in clean:
        return STATUS_PENDING_CLIENT
    if '交付' in clean or '完成' in clean or '正稿' in clean or '完稿' in clean:
        return STATUS_DONE
    if '取消' in clean:
        return STATUS_CANCELLED
    return clean

def _map_status_to_feishu(status: str) -> str:
    mapping = {
        STATUS_NEW: '⚪️ 新建',
        STATUS_PENDING_COPY: '🟡 待文案',
        STATUS_COPY_CONFIRM: '🟡 文案待确认',
        STATUS_PENDING_DESIGN: '🔵 待设计',
        STATUS_PENDING_REVIEW: '🟠 待内审',
        STATUS_NEEDS_REVISE: '🔴 需修改',
        STATUS_PENDING_CLIENT: '🟢 待客户反馈',
        STATUS_DONE: '✅ 已完稿',
        STATUS_CANCELLED: '❌ 已取消'
    }
    return mapping.get(status, status)

def _parse_version(version_str: str) -> int:
    if not version_str:
        return 1
    try:
        return int(version_str.replace("v", "").replace("V", ""))
    except:
        return 1

# ========== 记录转换 ==========

def _record_to_order(record: dict) -> dict:
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
        "driveLink": _extract_text(fields.get("链接", "")),
        "designer": _extract_user(fields.get("设计师 (人员 )", "")),
        "needCopy": _extract_text(fields.get("需要前策|文案", "否")) == "是",
        "copywriter": _extract_user(fields.get("前策|文案 (人员 )", "")),
        "copyContent": _extract_text(fields.get("文案内容", "")),
        "status": _map_status_from_feishu(_extract_text(fields.get("进度状态", ""))),
        "version": fields.get("版本号", 1) if isinstance(fields.get("版本号"), (int, float)) else _parse_version(_extract_text(fields.get("版本号", "v1"))),
        "createDate": _extract_date(fields.get("下单日期", "")),
        "ae": _extract_user(fields.get("AE-创建人", "")),
        "fonts": _extract_list(fields.get("使用字体", [])),
        "materialSource": _extract_list(fields.get("素材来源", [])),
        "materialDesc": _extract_text(fields.get("素材说明", "")),
        "portrait": _extract_option(fields.get("肖像权", "")),
        "designerSubmitted": _extract_text(fields.get("设计师提交", "")) == "是",
        "actualDate": _extract_date(fields.get("实际交付日期", "")),
        "reviewer": _extract_user(fields.get("指定内审员", "")),
        # v5 新增字段
        "internalReviseCount": fields.get("内部修改次数", 0) if isinstance(fields.get("内部修改次数"), (int, float)) else 0,
        "reviewHistory": _extract_text(fields.get("内审历史", "")),
    }

def _date_to_timestamp(date_str: str) -> int:
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return int(dt.timestamp() * 1000)
    except:
        return None

def _order_to_fields(order: dict) -> dict:
    fields = {
        "项目编号": order.get("id", ""),
        "项目简述": order.get("projectName", ""),
        "工作性质": order.get("workType", ""),
        "客户": order.get("customer", ""),
        "部门": order.get("dept", ""),
        "下单人": order.get("orderPerson", ""),
        "下单日期": _date_to_timestamp(order.get("orderDate", "")),
        "计划交付日期": _date_to_timestamp(order.get("planDate", "")),
        "制作日期": _date_to_timestamp(order.get("makeDate", "")) if order.get("makeDate") else None,
        "优先级": order.get("priority", "P1"),
        "交付物类型": order.get("deliverType", ""),
        "规格尺寸": order.get("size", ""),
        "数量": order.get("quantity", 1),
        "单位": order.get("unit", "个"),
        "说明": order.get("desc", ""),
        "链接": order.get("driveLink", ""),
        "设计师": feishu.get_user_field_value(order.get("designer", "")),
        "需要前策|文案": "是" if order.get("needCopy") else "否",
        "前策|文案 (人员 )": feishu.get_user_field_value(order.get("copywriter", "")),
        "文案内容": order.get("copyContent", ""),
        "进度状态": _map_status_to_feishu(order.get("status", "")),
        "版本号": order.get('version', 1),
        "AE-创建人": feishu.get_user_field_value(order.get("ae", "")),
        "指定内审员": feishu.get_user_field_value(order.get("reviewer", "")),
        "使用字体": _extract_list(order.get("fonts", [])),
        "素材来源": _extract_list(order.get("materialSource", [])),
        "素材说明": order.get("materialDesc", ""),
        "肖像权": order.get("portrait", ""),
        "设计师提交": "是" if order.get("designerSubmitted") else "否",
        "实际交付日期": _date_to_timestamp(order.get("actualDate", "")) if order.get("actualDate") else None,
        # v5 新增
        "内部修改次数": order.get("internalReviseCount", 0),
        "内审历史": order.get("reviewHistory", ""),
    }
    return {k: v for k, v in fields.items() if v is not None and v != "" and v != []}

# ========== 状态机校验 ==========

def _validate_status_transition(current_status: str, new_status: str) -> bool:
    if current_status == new_status:
        return True
    allowed = STATUS_FLOW.get(current_status, [])
    return new_status in allowed

# ========== 内审历史记录 ==========

def _build_review_history_entry(order: dict, result: str, comment: str = "") -> dict:
    return {
        "round": (order.get("internalReviseCount", 0) + 1),
        "submittedAt": datetime.now().isoformat(),
        "fonts": order.get("fonts", []),
        "materialSource": order.get("materialSource", []),
        "materialDesc": order.get("materialDesc", ""),
        "portrait": order.get("portrait", ""),
        "reviewer": order.get("reviewer", ""),
        "result": result,
        "comment": comment,
        "reviewedAt": datetime.now().isoformat() if result else None
    }

def _append_review_history(current_history: str, entry: dict) -> str:
    history = []
    if current_history:
        try:
            history = json.loads(current_history)
        except:
            history = []
    if not isinstance(history, list):
        history = []
    history.append(entry)
    return json.dumps(history, ensure_ascii=False)

# ========== 推送消息构建 ==========

def _build_form_url(view: str, role: str, record_id: str) -> str:
    base = "https://ad-workflow-system.onrender.com/"
    return f"{base}?view=form&role={role}&orderId={record_id}"

def _build_webhook_post(title: str, content_lines: list, at_users: list = None, buttons: list = None) -> dict:
    """构建飞书Post消息"""
    content_items = []
    for line in content_lines:
        content_items.append({"tag": "text", "text": line + "\n"})
    
    if at_users:
        for user_id in at_users:
            if user_id:
                content_items.append({"tag": "at", "user_id": user_id})
    
    if buttons:
        # 飞书Post消息不支持按钮，我们在文本中加入链接
        content_items.append({"tag": "text", "text": "\n"})
        for btn in buttons:
            content_items.append({"tag": "a", "text": f"[{btn['text']}] ", "href": btn['url']})
    
    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": [content_items]
                }
            }
        }
    }

# ========== API 路由 ==========

@router.get("/", response_model=List[OrderResponse])
async def list_orders(
    status: Optional[str] = None,
    customer: Optional[str] = None,
    designer: Optional[str] = None,
    copywriter: Optional[str] = None,
    reviewer: Optional[str] = None,
    ae: Optional[str] = None,
    active: Optional[bool] = None
):
    """查询工单列表"""
    try:
        records = await feishu.list_records(settings.ORDERS_TABLE_ID)
        orders = [_record_to_order(r) for r in records]
        
        if status:
            orders = [o for o in orders if o["status"] == status]
        if customer:
            orders = [o for o in orders if o["customer"] == customer]
        if designer:
            orders = [o for o in orders if o["designer"] == designer]
        if copywriter:
            orders = [o for o in orders if o["copywriter"] == copywriter]
        if reviewer:
            orders = [o for o in orders if o["reviewer"] == reviewer]
        if ae:
            orders = [o for o in orders if o["ae"] == ae]
        if active:
            orders = [o for o in orders if o["status"] not in [STATUS_DONE, STATUS_CANCELLED]]
            
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
        date_str = datetime.now().strftime("%Y%m%d")
        short = order.customer[:4] if order.customer else "NEW"
        
        records = await feishu.list_records(settings.ORDERS_TABLE_ID)
        seq = len(records) + 1 if records else 1
        order_id = f"{short}-{date_str}-{seq:03d}"
        
        # v5: 初始状态
        if order.needCopy and order.copywriter:
            initial_status = STATUS_PENDING_COPY
        elif order.designer:
            initial_status = STATUS_PENDING_DESIGN
        else:
            initial_status = STATUS_NEW
        
        fields = {
            "项目编号": order_id,
            "项目简述": order.projectName,
            "工作性质": order.workType,
            "客户": order.customer,
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
            "设计师": feishu.get_user_field_value(order.designer or ""),
            "需要前策|文案": "是" if order.needCopy else "否",
            "前策|文案 (人员 )": feishu.get_user_field_value(order.copywriter or ""),
            "进度状态": _map_status_to_feishu(initial_status),
            "版本号": 1,
            "AE-创建人": feishu.get_user_field_value("当前AE"),
            "指定内审员": feishu.get_user_field_value(order.reviewer or ""),
            "内部修改次数": 0,
            "对客修改次数": 0,
        }
        
        fields = {k: v for k, v in fields.items() if v is not None and v != "" and v != []}
        
        result = await feishu.create_record(settings.ORDERS_TABLE_ID, fields)
        return _record_to_order(result)
    except Exception as e:
        import traceback
        print(f"[ERROR] create_order: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{record_id}", response_model=OrderResponse)
async def update_order(record_id: str, update: OrderUpdate):
    """更新工单 - v5状态机"""
    try:
        current = await feishu.get_record(settings.ORDERS_TABLE_ID, record_id)
        current_order = _record_to_order(current)
        current_status = current_order.get("status", STATUS_NEW)
        
        # 状态机校验
        if update.status is not None and update.status != current_status:
            if not _validate_status_transition(current_status, update.status):
                raise HTTPException(
                    status_code=400, 
                    detail=f"非法状态流转: {STATUS_LABELS.get(current_status, current_status)} → {STATUS_LABELS.get(update.status, update.status)}"
                )
        
        fields = {}
        
        if update.status is not None:
            fields["进度状态"] = _map_status_to_feishu(update.status)
        
        if update.designer is not None:
            fields["设计师"] = feishu.get_user_field_value(update.designer)
        
        if update.copywriter is not None:
            fields["前策|文案 (人员 )"] = feishu.get_user_field_value(update.copywriter)
        
        if update.reviewer is not None:
            fields["指定内审员"] = feishu.get_user_field_value(update.reviewer)
        
        if update.makeDate is not None:
            fields["制作日期"] = _date_to_timestamp(str(update.makeDate))
        
        if update.priority is not None:
            fields["优先级"] = update.priority
        
        if update.desc is not None:
            fields["说明"] = update.desc
        
        if update.planDate is not None:
            fields["计划交付日期"] = _date_to_timestamp(str(update.planDate))
        
        if update.driveLink is not None:
            fields["链接"] = update.driveLink
        
        if update.fonts is not None:
            fields["使用字体"] = _extract_list(update.fonts)
        
        if update.materialSource is not None:
            fields["素材来源"] = _extract_list(update.materialSource)
        
        if update.materialDesc is not None:
            fields["素材说明"] = update.materialDesc
        
        if update.portrait is not None:
            fields["肖像权"] = update.portrait
        
        if update.copyContent is not None:
            fields["文案内容"] = update.copyContent
        
        if update.designerSubmitted is not None:
            fields["设计师提交"] = True if update.designerSubmitted else False
        
        if update.internalReviseCount is not None:
            fields["内部修改次数"] = update.internalReviseCount
        
        if update.reviewHistory is not None:
            fields["内审历史"] = update.reviewHistory
        
        # 过滤空值（但保留0和False）
        fields = {k: v for k, v in fields.items() if v is not None and v != "" and v != []}
        
        result = await feishu.update_record(settings.ORDERS_TABLE_ID, record_id, fields)
        updated_order = _record_to_order(result)
        
        # ========== v5 推送逻辑 ==========
        if update.status and update.status != current_status:
            await _send_status_notification(current_order, updated_order, update)
        
        return updated_order
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[ERROR] update_order: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

async def _send_status_notification(old_order: dict, new_order: dict, update: OrderUpdate):
    """发送状态变更通知"""
    new_status = update.status
    project = new_order.get('projectName', '')
    work_type = new_order.get('workType', '')
    customer = new_order.get('customer', '')
    dept = new_order.get('dept', '')
    deliver = f"{new_order.get('deliverType', '-')} {new_order.get('size', '')}"
    
    # ① 文案提交文案 → 推AE
    if new_status == STATUS_COPY_CONFIRM:
        ae_name = old_order.get('ae', '')
        ae_id = feishu.get_user_id(ae_name) if ae_name else None
        url = _build_form_url('form', 'ae_copy_confirm', new_order.get('recordId', ''))
        post_data = _build_webhook_post(
            title="📋 文案待确认",
            content_lines=[
                f"项目：【{work_type}】{project}",
                f"客户：{customer} · {dept}",
                f"文案：{new_order.get('copywriter', '')} 已提交文案，请确认是否可进入设计"
            ],
            at_users=[ae_id] if ae_id else None,
            buttons=[{"text": "确认文案", "url": url}]
        )
        await feishu.send_webhook_raw(post_data)
    
    # ② AE确认文案 → 推设计师
    elif new_status == STATUS_PENDING_DESIGN and old_order.get('status') == STATUS_COPY_CONFIRM:
        designer_name = new_order.get('designer', '')
        designer_id = feishu.get_user_id(designer_name) if designer_name else None
        url = _build_form_url('form', 'designer', new_order.get('recordId', ''))
        post_data = _build_webhook_post(
            title="🟣 可以开始设计",
            content_lines=[
                f"项目：【{work_type}】{project}",
                f"客户：{customer} · {dept}",
                f"文案已确认，请查看需求并开始设计"
            ],
            at_users=[designer_id] if designer_id else None,
            buttons=[{"text": "查看工单", "url": url}]
        )
        await feishu.send_webhook_raw(post_data)
    
    # ③ 设计师提交内审表 → 推AE
    elif new_status == STATUS_PENDING_REVIEW:
        ae_name = old_order.get('ae', '')
        ae_id = feishu.get_user_id(ae_name) if ae_name else None
        url = _build_form_url('form', 'ae_review', new_order.get('recordId', ''))
        fonts = ", ".join(new_order.get('fonts', [])) or '-'
        materials = ", ".join(new_order.get('materialSource', [])) or '-'
        post_data = _build_webhook_post(
            title="⭕️ 请安排内审",
            content_lines=[
                f"项目：【{work_type}】{project}",
                f"客户：{customer} · {dept}",
                f"设计师：{new_order.get('designer', '')} 已提交内审表",
                f"字体：{fonts}",
                f"素材来源：{materials}",
                f"肖像权：{new_order.get('portrait', '无')}"
            ],
            at_users=[ae_id] if ae_id else None,
            buttons=[{"text": "安排内审", "url": url}]
        )
        await feishu.send_webhook_raw(post_data)
    
    # ④ AE指定内审员 → 推内审员
    elif new_status == STATUS_PENDING_REVIEW and update.reviewer:
        # 这是AE指定内审员后的推送
        reviewer_name = update.reviewer
        reviewer_id = feishu.get_user_id(reviewer_name) if reviewer_name else None
        url = _build_form_url('form', 'reviewer', new_order.get('recordId', ''))
        post_data = _build_webhook_post(
            title="🔍 请审核",
            content_lines=[
                f"项目：【{work_type}】{project}",
                f"客户：{customer} · {dept}",
                f"设计师：{new_order.get('designer', '')}",
                f"请查看设计稿及版权信息"
            ],
            at_users=[reviewer_id] if reviewer_id else None,
            buttons=[{"text": "开始审核", "url": url}]
        )
        await feishu.send_webhook_raw(post_data)
    
    # ⑤ 内审不通过 → 推设计师
    elif new_status == STATUS_NEEDS_REVISE:
        designer_name = new_order.get('designer', '')
        designer_id = feishu.get_user_id(designer_name) if designer_name else None
        count = new_order.get('internalReviseCount', 0)
        url = _build_form_url('form', 'designer', new_order.get('recordId', ''))
        post_data = _build_webhook_post(
            title="🔴 需修改",
            content_lines=[
                f"项目：【{work_type}】{project}",
                f"内审意见：{update.materialDesc or '请查看系统详情'}",
                f"内部修改次数：第{count}次"
            ],
            at_users=[designer_id] if designer_id else None,
            buttons=[{"text": "修改并重新提交", "url": url}]
        )
        await feishu.send_webhook_raw(post_data)
    
    # ⑥ 客户要求修改 → 推设计师/文案
    elif new_status == STATUS_NEEDS_REVISE and old_order.get('status') == STATUS_PENDING_CLIENT:
        # 这是从"待客户反馈"回到"需修改"，说明客户要求修改
        designer_name = new_order.get('designer', '')
        designer_id = feishu.get_user_id(designer_name) if designer_name else None
        copywriter_name = new_order.get('copywriter', '')
        copywriter_id = feishu.get_user_id(copywriter_name) if copywriter_name else None
        count = new_order.get('version', 1) - 1  # 版本号-1 = 对客修改次数（初始版本为1）
        url = _build_form_url('form', 'designer', new_order.get('recordId', ''))
        at_list = []
        if designer_id:
            at_list.append(designer_id)
        if copywriter_id:
            at_list.append(copywriter_id)
        post_data = _build_webhook_post(
            title="🟠 客户要求修改",
            content_lines=[
                f"项目：【{work_type}】{project}",
                f"客户反馈需要修改，对客版本号+1（当前第{count}次）",
                f"请查看修改意见并调整"
            ],
            at_users=at_list,
            buttons=[{"text": "查看工单", "url": url}]
        )
        await feishu.send_webhook_raw(post_data)

@router.delete("/{record_id}")
async def delete_order(record_id: str):
    """删除工单"""
    try:
        await feishu.delete_record(settings.ORDERS_TABLE_ID, record_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== 内审相关API ==========

@router.post("/{record_id}/review")
async def submit_review(record_id: str, review_data: dict):
    """设计师提交内审表"""
    try:
        current = await feishu.get_record(settings.ORDERS_TABLE_ID, record_id)
        current_order = _record_to_order(current)
        
        # 校验：只有待设计或需修改状态可以提交内审
        current_status = current_order.get("status", "")
        if current_status not in [STATUS_PENDING_DESIGN, STATUS_NEEDS_REVISE]:
            raise HTTPException(status_code=400, detail=f"当前状态{STATUS_LABELS.get(current_status)}不允许提交内审")
        
        # 构建内审历史记录
        entry = {
            "round": (current_order.get("internalReviseCount", 0) + 1),
            "submittedAt": datetime.now().isoformat(),
            "fonts": review_data.get("fonts", []),
            "materialSource": review_data.get("materialSource", []),
            "materialDesc": review_data.get("materialDesc", ""),
            "portrait": review_data.get("portrait", ""),
            "reviewer": current_order.get("reviewer", ""),
            "result": None,
            "comment": "",
            "reviewedAt": None
        }
        
        new_history = _append_review_history(current_order.get("reviewHistory", ""), entry)
        
        # 更新字段
        fields = {
            "进度状态": _map_status_to_feishu(STATUS_PENDING_REVIEW),
            "使用字体": review_data.get("fonts", []),
            "素材来源": review_data.get("materialSource", []),
            "素材说明": review_data.get("materialDesc", ""),
            "肖像权": review_data.get("portrait", ""),
            "设计师提交": True,
            "内审历史": new_history,
        }
        
        # 如果是从需修改状态提交，累加内部修改次数
        if current_status == STATUS_NEEDS_REVISE:
            fields["内部修改次数"] = current_order.get("internalReviseCount", 0) + 1
        
        fields = {k: v for k, v in fields.items() if v is not None and v != "" and v != []}
        
        result = await feishu.update_record(settings.ORDERS_TABLE_ID, record_id, fields)
        updated_order = _record_to_order(result)
        
        # 推送AE安排内审
        ae_name = updated_order.get('ae', '')
        ae_id = feishu.get_user_id(ae_name) if ae_name else None
        url = _build_form_url('form', 'ae_review', record_id)
        fonts = ", ".join(updated_order.get('fonts', [])) or '-'
        materials = ", ".join(updated_order.get('materialSource', [])) or '-'
        post_data = _build_webhook_post(
            title="⭕️ 请安排内审",
            content_lines=[
                f"项目：【{updated_order.get('workType', '')}】{updated_order.get('projectName', '')}",
                f"客户：{updated_order.get('customer', '')} · {updated_order.get('dept', '')}",
                f"设计师：{updated_order.get('designer', '')} 已提交内审表",
                f"字体：{fonts}",
                f"素材来源：{materials}",
                f"肖像权：{updated_order.get('portrait', '无')}"
            ],
            at_users=[ae_id] if ae_id else None,
            buttons=[{"text": "安排内审", "url": url}]
        )
        await feishu.send_webhook_raw(post_data)
        
        return updated_order
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[ERROR] submit_review: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{record_id}/review-result")
async def review_result(record_id: str, result_data: dict):
    """内审员审核结果"""
    try:
        current = await feishu.get_record(settings.ORDERS_TABLE_ID, record_id)
        current_order = _record_to_order(current)
        
        current_status = current_order.get("status", "")
        if current_status != STATUS_PENDING_REVIEW:
            raise HTTPException(status_code=400, detail=f"当前状态{STATUS_LABELS.get(current_status)}不允许审核")
        
        passed = result_data.get("passed", False)
        comment = result_data.get("comment", "")
        
        # 更新内审历史
        history_str = current_order.get("reviewHistory", "")
        history = []
        if history_str:
            try:
                history = json.loads(history_str)
            except:
                history = []
        if history and isinstance(history, list):
            history[-1]["result"] = "approved" if passed else "rejected"
            history[-1]["comment"] = comment
            history[-1]["reviewedAt"] = datetime.now().isoformat()
        
        if passed:
            new_status = STATUS_PENDING_CLIENT
            new_internal_status = "🟢 内部通过"
        else:
            new_status = STATUS_NEEDS_REVISE
            new_internal_status = "🔴 内部修改"
        
        fields = {
            "进度状态": _map_status_to_feishu(new_status),
            "内审历史": json.dumps(history, ensure_ascii=False) if history else "",
        }
        
        if passed:
            fields["内审状态"] = new_internal_status
        
        fields = {k: v for k, v in fields.items() if v is not None and v != "" and v != []}
        
        result = await feishu.update_record(settings.ORDERS_TABLE_ID, record_id, fields)
        updated_order = _record_to_order(result)
        
        # 推送
        if passed:
            # 内审通过 → 推AE
            ae_name = updated_order.get('ae', '')
            ae_id = feishu.get_user_id(ae_name) if ae_name else None
            url = _build_form_url('form', 'ae_client', record_id)
            post_data = _build_webhook_post(
                title="🟢 内审通过",
                content_lines=[
                    f"项目：【{updated_order.get('workType', '')}】{updated_order.get('projectName', '')}",
                    f"已内审通过，请提交客户确认"
                ],
                at_users=[ae_id] if ae_id else None,
                buttons=[{"text": "提交客户", "url": url}]
            )
            await feishu.send_webhook_raw(post_data)
        else:
            # 不通过 → 推设计师
            designer_name = updated_order.get('designer', '')
            designer_id = feishu.get_user_id(designer_name) if designer_name else None
            count = updated_order.get('internalReviseCount', 0)
            url = _build_form_url('form', 'designer', record_id)
            post_data = _build_webhook_post(
                title="🔴 需修改",
                content_lines=[
                    f"项目：【{updated_order.get('workType', '')}】{updated_order.get('projectName', '')}",
                    f"内审意见：{comment}",
                    f"内部修改次数：第{count + 1}次"
                ],
                at_users=[designer_id] if designer_id else None,
                buttons=[{"text": "修改并重新提交", "url": url}]
            )
            await feishu.send_webhook_raw(post_data)
        
        return updated_order
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[ERROR] review_result: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
