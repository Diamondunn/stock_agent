from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from app.portfolio_store import get_holdings
from app.portfolio_analytics import calculate_portfolio_metrics

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"request": request})


@router.get("/dashboard")
async def dashboard(request: Request):
    holdings = get_holdings()
    metrics = calculate_portfolio_metrics()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "holdings": holdings,
            "metrics": metrics,
        },
    )


@router.get("/api/portfolio-data")
async def portfolio_data():
    return JSONResponse(calculate_portfolio_metrics())
