from fastapi import APIRouter, HTTPException
from typing import List
from models import FontCreate, WebhookMessage
from feishu_client import feishu
from config import settings
import json

router = APIRouter()

@router.get("/")
async def list_fonts():
    """获取字体列表"""
    try:
        if not settings.FONTS_TABLE_ID:
            # 如果没有配置字体表，返回环境变量中的默认数据
            default_fonts = json.loads(settings.FONTS) if hasattr(settings, 'FONTS') else []
            if not default_fonts:
                # 返回内置默认字体列表
                return [
                    "汉仪大宋", "汉仪中宋", "汉仪书宋二", "汉仪长美黑", "汉仪昌黎宋刻本精修版简",
                    "汉仪大黑", "汉仪中黑", "汉仪中等线", "汉仪典雅体简", "汉仪黑方简",
                    "汉仪中楷", "汉仪行楷", "汉仪楷体", "汉仪劲楷简", "汉仪魁肃",
                    "汉仪许静行楷简", "汉仪颜楷简", "汉仪风骨楷体简", "汉仪心海行楷简",
                    "汉仪粗圆", "汉仪雪君体", "汉仪书魂体简", "汉仪魏碑", "汉仪中隶书",
                    "汉仪程行简", "汉仪国强行书简", "汉仪老字号简", "汉仪颐和仙境简",
                    "汉仪杰龙游子吟简", "汉仪魁穆简", "汉仪杰龙行云简", "汉仪妙草简",
                    "汉仪心海行书简", "汉仪北魏写经简", "汉仪金陵刻经简", "汉仪金陵美宋简",
                    "汉仪大椿手绘宋简", "汉仪瑞兽简", "汉仪福满堂简", "汉仪空山楷简",
                    "汉仪仕杰墨榜简", "汉仪瑞鹤简", "汉仪碰碰车简", "汉仪大白兔简",
                    "汉仪孙尚香简", "汉仪破浪体简", "汉仪新人文宋65简", "汉仪瑞意宋50简",
                    "汉仪瑞意宋80简", "汉仪玄宋95简", "汉仪雅酷黑-85简", "汉仪雅酷黑-65简",
                    "汉仪文黑-75简", "汉仪文黑-45简", "汉仪元隆黑75简", "汉仪风尚黑85简",
                    "汉仪润圆-75简", "汉仪铸字木头人简", "汉仪铸字乐天派简", "汉仪铸字树袋熊简",
                    "汉仪铸字儿童乐园简", "汉仪铸字海底世界简", "汉仪晓波画报黑简",
                    "汉仪晓波暖宋简", "汉仪晓波美妍体简", "汉仪晓波手写简", "汉仪尚巍朴拙简",
                    "汉仪尚巍沧海简", "汉仪唐美人85简", "汉仪赤云隶85简", "汉仪花冠75简",
                    "汉仪花冠85简", "汉仪婉风宋75简", "汉仪书仿75简", "汉仪书仿95简",
                    "汉仪大风吹可变版", "汉仪永字舞狮简", "汉仪永字龙虎榜简", "汉仪永字小剑客简",
                    "汉仪懒黑黑简", "汉仪松阳体简", "汉仪小松茸简", "汉仪风波龙行简",
                    "汉仪风波便利店简", "汉仪菱心体力量版85简", "汉仪盈宋45简", "汉仪盈宋65简",
                    "汉仪范笑歌喜隶简", "汉仪新蒂蜡笔体", "汉仪新蒂赵孟頫体", "汉仪新蒂牌楼体",
                    "汉仪新蒂佛塔书", "汉仪新蒂语文体", "汉仪为你写诗体简", "汉仪旗黑-105简",
                    "汉仪旗黑-85简", "汉仪旗黑-55简", "汉仪将军75简", "汉仪将军95简",
                    "汉仪粗宋繁", "汉仪中宋繁", "汉仪报宋繁", "汉仪行楷繁", "汉仪老字号繁",
                    "汉仪旗黑-105繁", "汉仪旗黑-80繁", "汉仪旗黑-55繁",
                    "演示新手书", "演示镇魂行楷", "演示少年行", "演示宁缺体", "演示汉楷宋",
                    "演示流云楷", "波西米亚狂想黑", "艾迪鹅演示引擎标题体", "演示逍遥黑",
                    "演示踏歌行", "演示白菜体", "演示古风宋", "演示综艺黑", "演示芳华细圆",
                    "演示青年黑", "演示光华楷", "演示光芒体", "演示落月楷", "演示墩墩黑",
                    "演示诗歌宋", "演示多福体", "演示写意楷", "演示青花楷", "演示霸榜",
                    "演示创黑", "演示非宋", "演示刀刻黑", "演示晚风楷", "演示秀宋",
                    "演示天真宋", "演示真楷", "演示鲲榜", "演示童真体", "演示经集楷",
                    "演示复古基本宋", "演示拙黑", "演示开门隶", "演示祥云", "演示心情体",
                    "演示追光隶", "演示云顶黑", "演示金字招牌", "演示文艺宋", "演示通义楷",
                    "演示金刚体", "演示温暖隶", "演示决胜体", "演示舍得楷", "演示秋鸿楷",
                    "演示悠然小楷", "演示夏行楷", "演示魁本楷书", "演示佛系体", "演示春风楷",
                    "思源黑体", "思源宋体", "阿里巴巴普惠体", "OPPO Sans", "鸿蒙 HarmonyOS Sans",
                    "站酷高端黑", "抖音美好体", "优设标题黑"
                ]
            return [{"name": f} for f in default_fonts]
        
        records = await feishu.list_records(settings.FONTS_TABLE_ID)
        return [{"recordId": r.get("record_id"), "name": r.get("fields", {}).get("字体名称", "")} for r in records]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
async def create_font(font: FontCreate):
    """创建字体"""
    try:
        if not settings.FONTS_TABLE_ID:
            raise HTTPException(status_code=400, detail="未配置字体表ID")
        
        result = await feishu.create_record(settings.FONTS_TABLE_ID, {"字体名称": font.name})
        return {"recordId": result.get("record", {}).get("record_id"), "name": font.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{record_id}")
async def delete_font(record_id: str):
    """删除字体"""
    try:
        if not settings.FONTS_TABLE_ID:
            raise HTTPException(status_code=400, detail="未配置字体表ID")
        
        await feishu.delete_record(settings.FONTS_TABLE_ID, record_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/staff")
async def get_staff():
    """获取人员配置"""
    try:
        designers = json.loads(settings.DESIGNERS)
        other_staff = json.loads(settings.OTHER_STAFF)
        reviewers = json.loads(settings.REVIEWERS)
        return {
            "designers": designers,
            "otherStaff": other_staff,
            "reviewers": reviewers,
            "allStaff": designers + other_staff
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
