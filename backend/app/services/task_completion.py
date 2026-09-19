"""任务完成判定与完成率口径（全系统单一来源）。

任务列表、绿地档案、总览看板的完成率一律从这里取数，不允许各自再算。

统一口径
--------

- **应完成（分母）**：全部任务中剔除「已取消」；已取消的任务分子分母都不计入。
- **已完成（分子）**：任务状态为「已完成」。
- **完成率** = 已完成 / 应完成 × 100，保留 1 位小数；应完成为 0 时完成率为 0.0。

质量结论对任务状态的推导（养护记录联动与手动标记完成共用）：

- 存在「不合格」记录 → 进行中（待整改），不得完成；
- 存在「待复检」记录 → 进行中（等待复检结论），不得完成；
- 有「合格」记录且无待复检、无不合格 → 已完成；
- 没有任何养护记录 → 待执行。

历史数据原则
------------

本规则只约束生效之后的**状态流转与实时统计**：不做历史数据的批量重算，
已落库的任务状态与完成时间保持原样，历史月份的完成率不随规则调整而回溯变化；
只有某条任务的养护记录再次发生增删改时，该任务才按新规则重新推导。
"""

from sqlalchemy import func

from ..constants import ENUM_GROUPS
from ..extensions import db
from ..models import MaintenanceTask

#: 不参与完成率统计的任务状态（分子分母都剔除）
EXCLUDED_STATUSES = ("cancelled",)


def derive_task_status(records):
    """按质量结论推导任务状态（纯函数，records 为该任务的全部养护记录）。"""

    if not records:
        return "pending"
    results = {item.quality_result for item in records}
    if "unqualified" in results or "pending" in results:
        # 有不合格待整改，或有记录待复检，都不能算完成
        return "in_progress"
    return "completed"


def completion_blockers(records):
    """手动标记完成的拦截项：返回 (不合格条数, 待复检条数)，全为 0 才允许完成。"""

    unqualified = sum(1 for item in records if item.quality_result == "unqualified")
    pending = sum(1 for item in records if item.quality_result == "pending")
    return unqualified, pending


def completion_summary(query=None):
    """按统一口径汇总任务完成率。

    query 可按需预过滤（如限定某处绿地）；默认统计全部任务。
    """

    if query is None:
        query = db.session.query(MaintenanceTask)
    rows = query.with_entities(MaintenanceTask.status, func.count(MaintenanceTask.id)) \
        .group_by(MaintenanceTask.status).all()

    by_status = {code: 0 for code in ENUM_GROUPS["task_status"].values}
    for status, count in rows:
        by_status[status] = count

    total = sum(by_status.values())
    excluded = sum(by_status.get(status, 0) for status in EXCLUDED_STATUSES)
    countable = total - excluded
    completed = by_status.get("completed", 0)
    return {
        "total": total,
        "by_status": by_status,
        "countable": countable,
        "completed": completed,
        "cancelled": by_status.get("cancelled", 0),
        "rate": round(completed / countable * 100, 1) if countable else 0.0,
    }
