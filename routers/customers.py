from fastapi import APIRouter, HTTPException
from typing import List
from models import CustomerCreate, CustomerUpdate
from feishu_client import feishu
from config import settings

router = APIRouter()

def _record_to_customer(record: dict) -> dict:
    """飞书记录转客户对象"""
    fields = record.get("fields", {})
    depts_str = fields.get("部门", "")
    depts = [d.strip() for d in str(depts_str).split("、") if d.strip()] if depts_str else []
    return {
        "recordId": record.get("record_id", ""),
        "name": fields.get("客户", ""),
        "depts": depts
    }

def _merge_customers(records: List[dict]) -> List[dict]:
    """合并同名客户的部门"""
    customer_map = {}
    for r in records:
        c = _record_to_customer(r)
        name = c["name"]
        if not name:
            continue
        if name not in customer_map:
            customer_map[name] = {
                "recordId": c["recordId"],
                "name": name,
                "depts": set(c["depts"]),
                "recordIds": [c["recordId"]] if c["recordId"] else []
            }
        else:
            customer_map[name]["depts"].update(c["depts"])
            if c["recordId"]:
                customer_map[name]["recordIds"].append(c["recordId"])
    
    return [
        {
            "recordId": c["recordId"],
            "name": c["name"],
            "depts": sorted(list(c["depts"])),
            "recordIds": c["recordIds"]
        }
        for c in customer_map.values()
    ]

def _customer_to_fields(customer: dict) -> dict:
    """客户对象转飞书字段"""
    return {
        "客户": customer.get("name", ""),
        "部门": "、".join(customer.get("depts", []))
    }

@router.get("/")
async def list_customers():
    """获取客户列表（已合并去重）"""
    try:
        if not settings.CUSTOMERS_TABLE_ID:
            # 如果没有配置客户表，返回环境变量中的默认数据
            return [
                {"name": "兴业成都分行", "depts": ["成都订阅号","成都收单工单","成都财富客户规划","成都财富客群","成都消保","成都代发","成都财富工单","成都安愉+网点运营","成都成都私行","成都法律合规","成都个贷","成都客户经营","成都品牌宣传","成都财富群","成都信用卡中心","成都品牌"]},
                {"name": "兴业宁德分行", "depts": ["宁德零售设计","宁德工单","宁德私行","宁德蕉城支行","宁德公众号","宁德办公室"]},
                {"name": "兴业重庆分行", "depts": ["重庆信用卡宣传","重庆零售金融","重庆财富宣传","重庆养老金融","重庆私行","重庆零售信贷"]},
                {"name": "四川银行", "depts": ["四川银行信用卡","文旅一卡通","蜀农一卡通","八大工程","人才卡","社保卡","家庭分忧卡"]},
                {"name": "兴业总行", "depts": ["总行办公室","总行零售"]},
                {"name": "兴业基金", "depts": ["兴业基金"]},
                {"name": "兴业龙岩分行", "depts": ["龙岩私行"]},
                {"name": "兴业宁波分行", "depts": ["宁波私行"]},
                {"name": "兴业厦门分行", "depts": ["厦门财富"]},
                {"name": "兴业南昌分行", "depts": ["南昌分行"]},
                {"name": "兴业合肥分行", "depts": ["合肥私行"]},
                {"name": "兴业广州分行", "depts": ["广州分行"]},
                {"name": "兴业莆田分行", "depts": ["莆田私行"]},
                {"name": "兴业泉州分行", "depts": ["泉州私行"]}
            ]
        
        records = await feishu.list_records(settings.CUSTOMERS_TABLE_ID)
        return _merge_customers(records)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
async def create_customer(customer: CustomerCreate):
    """创建客户"""
    try:
        if not settings.CUSTOMERS_TABLE_ID:
            raise HTTPException(status_code=400, detail="未配置客户表ID")
        
        fields = _customer_to_fields({"name": customer.name, "depts": customer.depts})
        result = await feishu.create_record(settings.CUSTOMERS_TABLE_ID, fields)
        return _record_to_customer(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{record_id}")
async def update_customer(record_id: str, customer: CustomerUpdate):
    """更新客户"""
    try:
        if not settings.CUSTOMERS_TABLE_ID:
            raise HTTPException(status_code=400, detail="未配置客户表ID")
        
        fields = {}
        if customer.name is not None:
            fields["客户"] = customer.name
        if customer.depts is not None:
            fields["部门"] = "、".join(customer.depts)
        
        result = await feishu.update_record(settings.CUSTOMERS_TABLE_ID, record_id, fields)
        return _record_to_customer(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{record_id}")
async def delete_customer(record_id: str):
    """删除客户"""
    try:
        if not settings.CUSTOMERS_TABLE_ID:
            raise HTTPException(status_code=400, detail="未配置客户表ID")
        
        await feishu.delete_record(settings.CUSTOMERS_TABLE_ID, record_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
