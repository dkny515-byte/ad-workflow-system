from pydantic import BaseModel
from typing import Optional, List
from datetime import date

class OrderCreate(BaseModel):
    workType: str  # 原创/延展/修改
    projectName: str
    customer: str
    dept: Optional[str] = None
    orderPerson: Optional[str] = None
    orderDate: date
    planDate: date
    makeDate: Optional[date] = None
    priority: str  # P0/P1/P2/P3/可能来/当天新增
    deliverType: Optional[str] = None
    size: Optional[str] = None
    quantity: int = 1
    unit: Optional[str] = "个"
    desc: Optional[str] = None
    designer: Optional[str] = None
    needCopy: bool = False
    copywriter: Optional[str] = None
    reviewer: Optional[str] = None

class OrderUpdate(BaseModel):
    status: Optional[str] = None
    internalStatus: Optional[str] = None
    designer: Optional[str] = None
    reviewer: Optional[str] = None
    makeDate: Optional[date] = None
    priority: Optional[str] = None
    desc: Optional[str] = None
    planDate: Optional[date] = None
    driveLink: Optional[str] = None
    fonts: Optional[List[str]] = None
    materialSource: Optional[List[str]] = None
    materialDesc: Optional[str] = None
    portrait: Optional[str] = None
    copyContent: Optional[str] = None
    designerSubmitted: Optional[bool] = None
    actualDate: Optional[date] = None
    # v5新增
    internalReviseCount: Optional[int] = None
    reviewHistory: Optional[str] = None  # JSON字符串

class OrderResponse(BaseModel):
    recordId: str
    id: str
    projectName: str
    workType: str
    customer: str
    dept: Optional[str]
    orderPerson: Optional[str]
    orderDate: str
    planDate: str
    makeDate: Optional[str]
    priority: str
    deliverType: Optional[str]
    size: Optional[str]
    quantity: int
    unit: Optional[str]
    desc: Optional[str]
    driveLink: Optional[str]
    designer: Optional[str]
    needCopy: bool
    copywriter: Optional[str]
    copyContent: Optional[str]
    status: str
    internalStatus: Optional[str]
    version: int
    createDate: str
    ae: str
    fonts: List[str]
    materialSource: List[str]
    materialDesc: Optional[str]
    portrait: Optional[str]
    designerSubmitted: bool
    actualDate: Optional[str]
    reviewer: Optional[str]
    # v5新增
    internalReviseCount: int
    reviewHistory: Optional[str]

class CustomerCreate(BaseModel):
    name: str
    depts: List[str]

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    depts: Optional[List[str]] = None

class FontCreate(BaseModel):
    name: str

class WebhookMessage(BaseModel):
    text: str
