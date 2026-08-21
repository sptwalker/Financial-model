import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.permissions import PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.models.financial import Scenario, ModelVersion, Cell
from app.schemas.scenario import (
    ScenarioCreate, ScenarioUpdate, ScenarioOut, CellWrite, CellWriteBatch,
    RecalcRequest,
)
from app.services.operation_log_service import OperationLogService
from app.services.recalc_service import recalc

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


# ---------- 情景 ----------

@router.get("", response_model=list[ScenarioOut])
def list_scenarios(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """情景列表（全部角色可见）"""
    return db.query(Scenario).order_by(Scenario.id).all()


@router.post("", response_model=ScenarioOut)
def create_scenario(body: ScenarioCreate, db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    """新建情景（admin/editor）"""
    PermissionChecker.require_edit(current_user)
    if db.query(Scenario).filter(Scenario.name == body.name).first():
        raise HTTPException(status_code=400, detail="情景名称已存在")
    scenario = Scenario(name=body.name, description=body.description,
                        created_by=current_user.id)
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    OperationLogService.log(db, action="scenario.create", description=f"创建情景 {scenario.name}",
                            user_id=current_user.id)
    return scenario


@router.patch("/{scenario_id}", response_model=ScenarioOut)
def update_scenario(scenario_id: int, body: ScenarioUpdate, db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    """更新情景（admin/editor）"""
    PermissionChecker.require_edit(current_user)
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="情景不存在")
    if body.name is not None and body.name != scenario.name:
        if db.query(Scenario).filter(Scenario.name == body.name).first():
            raise HTTPException(status_code=400, detail="情景名称已存在")
        scenario.name = body.name
    if body.description is not None:
        scenario.description = body.description
    if body.is_active is not None:
        if body.is_active:
            # 同一时刻只有一个默认情景
            db.query(Scenario).filter(Scenario.is_active.is_(True)).update(
                {Scenario.is_active: False})
        scenario.is_active = body.is_active
    db.commit()
    db.refresh(scenario)
    OperationLogService.log(db, action="scenario.update", description=f"更新情景 {scenario.name}",
                            user_id=current_user.id)
    return scenario


@router.delete("/{scenario_id}")
def delete_scenario(scenario_id: int, db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    """删除情景及其全部版本、单元格（仅 admin）"""
    PermissionChecker.require_admin(current_user)
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="情景不存在")
    db.query(Cell).filter(Cell.scenario_id == scenario_id).delete()
    db.query(ModelVersion).filter(ModelVersion.scenario_id == scenario_id).delete()
    db.delete(scenario)
    db.commit()
    OperationLogService.log(db, action="scenario.delete",
                            description=f"删除情景 {scenario.name}", user_id=current_user.id)
    return {"ok": True}


# ---------- 版本 ----------

@router.get("/{scenario_id}/versions")
def list_versions(scenario_id: int, db: Session = Depends(get_db),
                  current_user=Depends(get_current_user)):
    """情景的模型版本列表（最新在前），附最新版参数快照与已发布状态"""
    latest = (db.query(ModelVersion)
              .filter(ModelVersion.scenario_id == scenario_id)
              .order_by(ModelVersion.version_no.desc()).first())
    versions = [
        {"version_no": v.version_no, "comment": v.comment, "source": v.source,
         "created_at": v.created_at.isoformat() if v.created_at else None,
         "released_at": v.released_at.isoformat() if v.released_at else None,
         "released_by": v.released_by}
        for v in db.query(ModelVersion)
        .filter(ModelVersion.scenario_id == scenario_id)
        .order_by(ModelVersion.version_no.desc()).all()
    ]
    return {"scenario_id": scenario_id, "versions": versions,
            "params": json.loads(latest.params_json) if latest and latest.params_json else None}


@router.post("/{scenario_id}/versions/{version_no}/release")
def release_version(scenario_id: int, version_no: int, db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    """发布版本（仅 admin）——软冻结：标记已发布，可复盘可撤销，不阻断编辑"""
    PermissionChecker.require_admin(current_user)
    version = (db.query(ModelVersion)
               .filter(ModelVersion.scenario_id == scenario_id,
                       ModelVersion.version_no == version_no).first())
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    from datetime import datetime
    version.released_at = datetime.now()
    version.released_by = current_user.id
    db.commit()
    OperationLogService.log(db, action="version.release",
                            description=f"发布情景 {scenario_id} 版本 v{version_no}",
                            user_id=current_user.id)
    return {"ok": True, "version_no": version_no, "released": True}


@router.post("/{scenario_id}/versions/{version_no}/unrelease")
def unrelease_version(scenario_id: int, version_no: int, db: Session = Depends(get_db),
                      current_user=Depends(get_current_user)):
    """撤销发布（仅 admin）——恢复为草稿状态"""
    PermissionChecker.require_admin(current_user)
    version = (db.query(ModelVersion)
               .filter(ModelVersion.scenario_id == scenario_id,
                       ModelVersion.version_no == version_no).first())
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    version.released_at = None
    version.released_by = None
    db.commit()
    OperationLogService.log(db, action="version.unrelease",
                            description=f"撤销发布 情景 {scenario_id} 版本 v{version_no}",
                            user_id=current_user.id)
    return {"ok": True, "version_no": version_no, "released": False}


# ---------- 重算 ----------

@router.post("/{scenario_id}/recalc")
def recalc_scenario(scenario_id: int, body: RecalcRequest, db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    """改参数/覆盖后触发引擎重算 → 生成新版本（admin/editor）

    body.params 传引擎参数增量（如 {"price_online": "1999"}），不传则沿用上一版参数。
    返回新版本号与完整网格摘要，前端可据此刷新图表。
    """
    PermissionChecker.require_edit(current_user)
    try:
        result = recalc(db, scenario_id, params_override=body.params,
                        comment=body.comment, user_id=current_user.id)
    except (ValueError, TypeError) as e:
        if str(e) == "scenario_not_found":
            raise HTTPException(status_code=404, detail="情景不存在")
        if str(e) == "no_version":
            raise HTTPException(status_code=404, detail="该情景尚未计算，请先导入或重算")
        if str(e) == "no_cells":
            raise HTTPException(status_code=404, detail="该版本没有可重算的单元格")
        if str(e) in ("version_conflict_retry", "db_locked_retry"):
            raise HTTPException(status_code=409, detail="并发重算冲突，请重试")
        raise HTTPException(status_code=400, detail=f"重算失败: {e}")
    OperationLogService.log(db, action="scenario.recalc",
                            description=f"情景 {scenario_id} 重算 → 版本 {result['version_no']}",
                            detail={"scenario_id": scenario_id,
                                    "version_no": result["version_no"],
                                    "cell_count": result["cell_count"]},
                            user_id=current_user.id)
    return result


# ---------- 单元格网格 ----------

def _get_grid(scenario_id: int, version_no: int | None, db: Session) -> tuple[int, list[Cell]]:
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="情景不存在")
    if version_no is None:
        latest = (db.query(ModelVersion)
                  .filter(ModelVersion.scenario_id == scenario_id)
                  .order_by(ModelVersion.version_no.desc()).first())
        if not latest:
            raise HTTPException(status_code=404, detail="该情景尚未计算，请先导入或重算")
        version_no = latest.version_no
    cells = (db.query(Cell)
             .filter(Cell.scenario_id == scenario_id, Cell.model_version == version_no)
             .all())
    return version_no, cells


@router.get("/{scenario_id}/grid")
def get_grid(scenario_id: int, version_no: int | None = None, db: Session = Depends(get_db),
             current_user=Depends(get_current_user)):
    """读取某版本的完整行×期网格（全部角色可读）"""
    version_no, cells = _get_grid(scenario_id, version_no, db)
    grid: dict[str, dict] = {}
    for c in cells:
        grid.setdefault(c.row_key, {})[c.period] = {"value": c.value, "source": c.source}
    return {
        "scenario_id": scenario_id,
        "version_no": version_no,
        "cells": grid,
    }


@router.put("/{scenario_id}/cells")
def write_cells(scenario_id: int, body: CellWriteBatch, db: Session = Depends(get_db),
                current_user=Depends(get_current_user)):
    """批量覆盖单元格（admin/editor）——写后触发重算由前端调用 recalc 完成"""
    PermissionChecker.require_edit(current_user)
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="情景不存在")
    latest = (db.query(ModelVersion)
              .filter(ModelVersion.scenario_id == scenario_id)
              .order_by(ModelVersion.version_no.desc()).first())
    if not latest:
        raise HTTPException(status_code=404, detail="该情景尚未计算，请先导入或重算")
    count = 0
    missing: list[dict] = []
    for row_key, periods in body.cells.items():
        for period, value in periods.items():
            cell = (db.query(Cell)
                    .filter(Cell.scenario_id == scenario_id,
                            Cell.model_version == latest.version_no,
                            Cell.period == period, Cell.row_key == row_key)
                    .first())
            if cell:
                cell.value = value
                cell.source = "override"
                count += 1
            else:
                missing.append({"row_key": row_key, "period": period})
    db.commit()
    OperationLogService.log(db, action="cell.override",
                            description=f"覆盖 {count} 个单元格",
                            detail={"scenario_id": scenario_id}, user_id=current_user.id)
    result = {"ok": True, "updated": count}
    if missing:
        # 行×期不在最新版本网格中：不静默丢失，明确回报给调用方
        result["warning"] = f"{len(missing)} 个单元格不在当前版本网格中，已跳过"
        result["missing"] = missing
    return result
