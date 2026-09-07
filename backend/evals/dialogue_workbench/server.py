"""只在 loopback 提供的实验工作台 FastAPI 服务。"""

from __future__ import annotations

from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from evals.dialogue_workbench.runtime import WorkbenchRuntime

COOKIE_NAME = "grove_experiment_session"


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnCreate(StrictRequest):
    message: str = Field(min_length=1, max_length=16_000)
    request_id: str = Field(min_length=8, max_length=100)


class FeedbackCreate(StrictRequest):
    kind: str
    note: str = Field(default="", max_length=2_000)


def create_app(runtime: WorkbenchRuntime, static_dir: Path) -> FastAPI:
    if not (static_dir / "workbench.html").is_file():
        raise RuntimeError(f"缺少工作台前端构建产物：{static_dir / 'workbench.html'}")
    app = FastAPI(title="Grove 知识 Agent 实验工作台", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def loopback_origin_guard(request: Request, call_next):
        host = request.client.host if request.client else ""
        if host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse({"detail": "实验服务只接受本机请求"}, status_code=403)
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin and origin != expected_origin:
            return JSONResponse({"detail": "实验服务拒绝非本机来源"}, status_code=403)
        return await call_next(request)

    def require_session(token: str | None) -> None:
        if not runtime.authorize(token):
            raise HTTPException(status_code=401, detail="实验会话无效，请刷新页面")

    @app.get("/healthz")
    async def health() -> dict:
        return {"status": "ok", "service": "knowledge-agent-experiment-workbench"}

    @app.post("/api/workbench/bootstrap")
    async def bootstrap(response: Response) -> dict:
        token = runtime.issue_browser_session()
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return runtime.public_state()

    @app.get("/api/workbench/state")
    async def state(grove_experiment_session: str | None = Cookie(default=None)) -> dict:
        require_session(grove_experiment_session)
        return runtime.public_state()

    @app.post("/api/workbench/conversations", status_code=201)
    async def create_conversation(
        grove_experiment_session: str | None = Cookie(default=None),
    ) -> dict:
        require_session(grove_experiment_session)
        try:
            return await runtime.create_conversation()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/api/workbench/conversations/{conversation_id}/turns", status_code=202)
    async def submit_turn(
        conversation_id: str,
        payload: TurnCreate,
        grove_experiment_session: str | None = Cookie(default=None),
    ) -> dict:
        require_session(grove_experiment_session)
        try:
            return await runtime.submit_turn(conversation_id, payload.message, payload.request_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="对话不存在") from None
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/api/workbench/conversations/{conversation_id}/turns/{turn_id}/cancel")
    async def cancel_turn(
        conversation_id: str,
        turn_id: str,
        grove_experiment_session: str | None = Cookie(default=None),
    ) -> dict:
        require_session(grove_experiment_session)
        try:
            return await runtime.cancel_turn(conversation_id, turn_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="对话或轮次不存在") from None
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.put("/api/workbench/conversations/{conversation_id}/turns/{turn_id}/feedback")
    async def save_feedback(
        conversation_id: str,
        turn_id: str,
        payload: FeedbackCreate,
        grove_experiment_session: str | None = Cookie(default=None),
    ) -> dict:
        require_session(grove_experiment_session)
        try:
            return await runtime.save_feedback(conversation_id, turn_id, payload.kind, payload.note)
        except KeyError:
            raise HTTPException(status_code=404, detail="对话或轮次不存在") from None
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @app.get("/api/workbench/export")
    async def export(grove_experiment_session: str | None = Cookie(default=None)):
        require_session(grove_experiment_session)
        return JSONResponse(
            runtime.export_payload(),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="grove-dialogue-workbench-{runtime.session_id}.json"'
                )
            },
        )

    @app.get("/")
    @app.get("/workbench")
    async def workbench() -> FileResponse:
        return FileResponse(static_dir / "workbench.html")

    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
    return app
