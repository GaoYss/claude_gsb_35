"""统计看板接口测试。"""

from datetime import date, timedelta


def test_completion_rate_excludes_cancelled_tasks(api, make_task):
    """统一口径：已取消任务不计入完成率分子分母。"""

    make_task(status="completed")
    make_task(status="completed")
    make_task(status="in_progress")
    make_task(status="cancelled")

    task = api.data(api.get("/api/v1/statistics/overview"))["task"]
    assert task["total"] == 4
    assert task["countable"] == 3
    assert task["completion_rate"] == round(2 / 3 * 100, 1)


def test_completion_rate_consistent_across_list_profile_and_dashboard(api, make_space, make_task):
    """任务列表、绿地档案、总览看板同一批数据必须出同一个完成率。"""

    space = make_space()
    make_task(space=space, status="completed")
    make_task(space=space, status="in_progress")
    make_task(space=space, status="cancelled")

    overview_task = api.data(api.get("/api/v1/statistics/overview"))["task"]
    listing = api.data(api.get("/api/v1/maintenance-tasks"))
    profile = api.data(api.get(f"/api/v1/green-spaces/{space.id}/profile"))

    assert overview_task["completion_rate"] == 50.0
    assert listing["summary"]["completion_rate"] == overview_task["completion_rate"]
    assert listing["summary"]["countable"] == overview_task["countable"] == 2
    assert profile["statistics"]["task_completion_rate"] == overview_task["completion_rate"]
    assert profile["statistics"]["task_countable"] == 2


def test_reads_do_not_recompute_historical_task_status(api, app, make_task, make_record):
    """历史月份已落库的任务状态不被查询接口重算，仅记录增删改才触发重推导。"""

    from app.extensions import db

    task = make_task()
    make_record(task=task, quality_result="qualified")
    make_record(task=task, quality_result="pending", record_date=date(2026, 3, 20))
    # 模拟口径调整前已落库的「已完成」状态（按现行推导应为进行中）
    task.status = "completed"
    db.session.commit()

    api.data(api.get("/api/v1/statistics/overview"))
    api.data(api.get("/api/v1/maintenance-tasks"))
    api.data(api.get(f"/api/v1/green-spaces/{task.green_space_id}/profile"))
    assert api.data(api.get(f"/api/v1/maintenance-tasks/{task.id}"))["status"] == "completed"


def test_overview_reflects_seeded_data(api, seeded):
    data = api.data(api.get("/api/v1/statistics/overview"))
    assert data["green_space"]["total"] == seeded["green_space"]
    assert data["green_space"]["total_area"] > 0
    assert data["green_space"]["by_status"]["archived"] == 1

    assert data["task"]["total"] == seeded["maintenance_task"]
    assert data["task"]["by_status"]["cancelled"] == 1
    assert 0 <= data["task"]["completion_rate"] <= 100

    assert data["record"]["total"] == seeded["maintenance_record"]
    assert data["record"]["total_work_hours"] > 0
    assert data["replacement"]["total"] == seeded["plant_replacement"]
    assert data["replacement"]["total_amount"] > 0


def test_overdue_and_due_soon_reminders(api, make_space, make_task):
    space = make_space()
    make_task(space=space, plan_date=date.today() - timedelta(days=3), status="pending")
    make_task(space=space, plan_date=date.today() + timedelta(days=2), status="pending")
    make_task(space=space, plan_date=date.today() - timedelta(days=3), status="completed")

    overview = api.data(api.get("/api/v1/statistics/overview"))
    assert overview["task"]["overdue_count"] == 1
    assert overview["task"]["due_soon_count"] == 1

    reminders = api.data(api.get("/api/v1/statistics/reminders"))
    assert len(reminders["overdue"]) == 1
    assert reminders["overdue"][0]["is_overdue"] is True
    assert len(reminders["upcoming"]) == 1


def test_distributions_cover_all_dimensions(api, make_task, make_replacement, make_record):
    task = make_task()
    record = make_record(task=task)
    make_replacement(record=record, plant_category="shrub", reason="aging", quantity=30, unit_price=10)

    data = api.data(api.get("/api/v1/statistics/distributions"))
    assert {item["value"] for item in data["green_space_by_type"]} == {"park"}
    assert {item["value"] for item in data["green_space_by_grade"]} == {"level2"}
    assert data["green_space_by_district"][0]["value"] == "西湖区"
    assert {item["value"] for item in data["task_by_type"]} == {"prune"}
    assert data["replacement_by_category"][0]["amount"] == 300.0
    assert data["replacement_by_reason"][0]["quantity"] == 30.0


def test_trends_return_requested_month_window(api, seeded):
    data = api.data(api.get("/api/v1/statistics/trends", months=6))
    items = data["items"]
    assert len(items) == 6
    assert items[-1]["month"] == f"{date.today():%Y-%m}"
    assert sum(item["record_count"] for item in items) == seeded["maintenance_record"]
    for item in items:
        assert set(item) == {
            "month", "record_count", "work_hours",
            "replacement_count", "replacement_quantity", "replacement_amount",
        }


def test_ranking_orders_by_record_count(api, make_space, make_record):
    busy = make_space(name="高频养护绿地")
    quiet = make_space(name="低频养护绿地")
    make_record(space=busy)
    make_record(space=busy, record_date=date(2026, 4, 2))
    make_record(space=quiet)

    items = api.data(api.get("/api/v1/statistics/ranking"))["items"]
    assert items[0]["name"] == "高频养护绿地"
    assert items[0]["record_count"] == 2
    assert items[0]["green_space_id"] == busy.id


def test_dashboard_returns_all_sections(api, seeded):
    data = api.data(api.get("/api/v1/statistics/dashboard"))
    assert set(data) == {
        "overview", "distributions", "trends", "ranking",
        "overdue_tasks", "upcoming_tasks", "recent_activity",
    }
    assert len(data["trends"]) == 6
    assert data["recent_activity"]["records"]
    assert data["recent_activity"]["replacements"]
