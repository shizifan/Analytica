from fastapi import FastAPI
from mock_server.routers import production, market, customer, asset, invest

app = FastAPI(title="Analytica Mock Server", version="1.0.0")

app.include_router(production.router)
app.include_router(market.router)
app.include_router(customer.router)
app.include_router(asset.router)
app.include_router(invest.router)


@app.get("/health")
def health_check():
    return {"status": "ok", "api_count": 27}
