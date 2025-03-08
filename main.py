from fastapi.exception_handlers import (
    request_validation_exception_handler,
)
from pprint import pprint
from fastapi import FastAPI, Request, status, BackgroundTasks
from fastapi.responses import ORJSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
import httpx
from exchange.stock.kis import KoreaInvestment
from exchange.model import MarketOrder, PriceRequest, HedgeData, OrderRequest
from exchange.utility import (
    settings,
    log_order_message,
    log_alert_message,
    print_alert_message,
    logger_test,
    log_order_error_message,
    log_validation_error_message,
    log_hedge_message,
    log_error_message,
    log_message,
)
import traceback
from exchange import get_exchange, log_message, db, settings, get_bot, pocket
import ipaddress
import os
import sys
from devtools import debug

VERSION = "0.1.8"
app = FastAPI(default_response_class=ORJSONResponse)


def get_error(e):
    tb = traceback.extract_tb(e.__traceback__)
    target_folder = os.path.abspath(os.path.dirname(tb[0].filename))
    error_msg = []

    for tb_info in tb:
        # if target_folder in tb_info.filename:
        error_msg.append(
            f"File {tb_info.filename}, line {tb_info.lineno}, in {tb_info.name}"
        )
        error_msg.append(f"  {tb_info.line}")

    error_msg.append(str(e))

    return error_msg


@app.on_event("startup")
async def startup():
    log_message(f"POABOT 실행 완료! - 버전:{VERSION}")


@app.on_event("shutdown")
async def shutdown():
    db.close()


whitelist = [    
    "127.0.0.1",
]
whitelist = whitelist + settings.WHITELIST


# @app.middleware("http")
# async def add_process_time_header(request: Request, call_next):
#     start_time = time.perf_counter()
#     response = await call_next(request)
#     process_time = time.perf_counter() - start_time
#     response.headers["X-Process-Time"] = str(process_time)
#     return response


@app.middleware("http")
async def whitelist_middleware(request: Request, call_next):
    try:
        if (
            request.client.host not in whitelist
            and not ipaddress.ip_address(request.client.host).is_private
        ):
            msg = f"{request.client.host}는 안됩니다"
            print(msg)
            return ORJSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content=f"{request.client.host}는 허용되지 않습니다",
            )
    except:
        log_error_message(traceback.format_exc(), "미들웨어 에러")
    else:
        response = await call_next(request)
        return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    msgs = [
        f"[에러{index+1}] " + f"{error.get('msg')} \n{error.get('loc')}"
        for index, error in enumerate(exc.errors())
    ]
    message = "[Error]\n"
    for msg in msgs:
        message = message + msg + "\n"

    log_validation_error_message(f"{message}\n {exc.body}")
    return await request_validation_exception_handler(request, exc)



@app.get("/hi")
async def welcome():
    return "hi!!"


@app.post("/price")
async def price(price_req: PriceRequest, background_tasks: BackgroundTasks):
    exchange = get_exchange(price_req.exchange)
    price = exchange.dict()[price_req.exchange].fetch_price(
        price_req.base, price_req.quote
    )
    return price


def log(exchange_name, result, order_info):
    log_order_message(exchange_name, result, order_info)
    print_alert_message(order_info)


def log_error(error_message, order_info):
    log_order_error_message(error_message, order_info)
    log_alert_message(order_info, "실패")


@app.post("/order")
@app.post("/")
async def order(order_info: MarketOrder, background_tasks: BackgroundTasks):
    order_result = None
    try:
        exchange_name = order_info.exchange
        bot = get_bot(exchange_name, order_info.kis_number)
        bot.init_info(order_info)

        if bot.order_info.is_crypto:
            if bot.order_info.is_entry:
                order_result = bot.market_entry(bot.order_info)
            elif bot.order_info.is_close:
                order_result = bot.market_close(bot.order_info)
            elif bot.order_info.is_buy:
                order_result = bot.market_buy(bot.order_info)
            elif bot.order_info.is_sell:
                order_result = bot.market_sell(bot.order_info)
            background_tasks.add_task(log, exchange_name, order_result, order_info)
        elif bot.order_info.is_stock:
            order_result = bot.create_order(
                bot.order_info.exchange,
                bot.order_info.base,
                order_info.type.lower(),
                order_info.side.lower(),
                order_info.amount,
            )
            background_tasks.add_task(log, exchange_name, order_result, order_info)

    except TypeError as e:
        error_msg = get_error(e)
        background_tasks.add_task(
            log_order_error_message, "\n".join(error_msg), order_info
        )

    except Exception as e:
        error_msg = get_error(e)
        background_tasks.add_task(log_error, "\n".join(error_msg), order_info)

    else:
        return {"result": "success"}

    finally:
        pass

