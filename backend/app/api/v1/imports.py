# -*- coding: utf-8 -*-
"""导入 API：上传现金流表格 → 重建基础数据（中性 v1 + 乐观/悲观克隆）

生产环境数据置空的恢复途经：管理员/编辑者在「设置」页上传三件套即可重建，无需
容器命令行或挂载 docs。破坏性操作：就地重建「中性」并克隆三方案。
错误映射：校验失败 → 400/422；引擎/解析异常 → 400（事务回滚，不留半重建态）。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.permissions import PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.services.import_service import rebuild_from_excel
from app.services.operation_log_service import OperationLogService

router = APIRouter(prefix="/imports", tags=["imports"])

_XLS_EXTS = (".xls",)
_XLSX_EXTS = (".xlsx",)


@router.post("/rebuild")
def rebuild(file_main_xls: UploadFile = File(...),
            file_report_xlsx: UploadFile = File(...),
            db: Session = Depends(get_db),
            current_user: User = Depends(get_current_user)):
    """上传现金流测算.xls + 财务报表__202607期.xlsx → 重建基础数据（admin/editor）"""
    PermissionChecker.require_edit(current_user, action="导入重建", entity="基础数据")

    main_name = file_main_xls.filename or ""
    report_name = file_report_xlsx.filename or ""
    if not main_name.lower().endswith(_XLS_EXTS):
        raise HTTPException(status_code=400, detail="主表应为 .xls 文件（现金流测算 2026.8.xls）")
    if not report_name.lower().endswith(_XLSX_EXTS):
        raise HTTPException(status_code=400, detail=f"{report_name or '财务报表'} 应为 .xlsx 文件")

    # 事务边界：rebuild_from_excel 内部只 flush，全部写入在成功末尾单次 commit，
    # 任一步异常即整体回滚，不会留下「中性已清空但克隆未重建」的半重建态。
    # xlrd 只接受真实文件路径 → 主表写临时文件；xlsx 直接交给 openpyxl 读流
    try:
        with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
            tmp.write(file_main_xls.file.read())
            xls_path = Path(tmp.name)
        try:
            result = rebuild_from_excel(db, xls_path,
                                        file_report_xlsx.file,
                                        user_id=current_user.id)
        finally:
            xls_path.unlink(missing_ok=True)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"导入失败：{e}")
    except Exception as e:  # noqa: BLE001 — 解析/校验异常统一回滚并给出可读信息
        db.rollback()
        raise HTTPException(status_code=400, detail=f"导入失败：{e}")

    OperationLogService.log(db, action="scenario.import",
                            description=f"导入重建基础数据（{main_name}）",
                            detail=result, user_id=current_user.id)
    return {"ok": True, **result}
