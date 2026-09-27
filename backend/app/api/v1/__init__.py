from fastapi import APIRouter

from app.api.v1 import auth, budget_reports, entities, imports, settings, txns

router = APIRouter()
for module in (auth, settings, entities, txns, budget_reports, imports):
    router.include_router(module.router)
