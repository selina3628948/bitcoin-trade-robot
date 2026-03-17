import ccxt
import time
import os
import json
from datetime import datetime

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY', 'YOUR_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET', 'YOUR_SECRET'),
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'},
})


symbol = 'BTC/USDT'
timeframe = '1h'
ma_period = 99
TIMEOUT_HOURS = 72

HEARTBEAT_FILE = 'bot_heartbeat.json'
ERROR_LOG_FILE = 'bot_error.log'

lines = {
    'a': {'offset': 0.01, 'usdt_amount': 100, 'profit_ratio': 0.015,
          'occupied': False, 'buy_price': None, 'buy_time': None,
          'buy_amount': None, 'sell_order_id': None},
    'b': {'offset': 0.02, 'usdt_amount': 200, 'profit_ratio': 0.025,
          'occupied': False, 'buy_price': None, 'buy_time': None,
          'buy_amount': None, 'sell_order_id': None},
    'c': {'offset': 0.03, 'usdt_amount': 300, 'profit_ratio': 0.035,
          'occupied': False, 'buy_price': None, 'buy_time': None,
          'buy_amount': None, 'sell_order_id': None},
}


def log(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"{timestamp} - {message}")


def calculate_ma():
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=ma_period)
    closes = [candle[4] for candle in ohlcv]
    return sum(closes) / ma_period


def get_current_price():
    return exchange.fetch_ticker(symbol)['last']


def cancel_order_if_exists(order_id):
    if order_id:
        try:
            exchange.cancel_order(order_id, symbol)
            log(f"成功取消旧卖单 {order_id}")
        except Exception as e:
            if "order not exists" not in str(e).lower():
                log(f"取消订单失败: {e}")


# ==================== strategy ====================

def process_lines(ma, current_price):
    for line_name, params in lines.items():
        if not params['occupied']:
            _try_place_buy(line_name, params, ma, current_price)
        else:
            _check_sell_or_timeout(line_name, params, current_price)


def _try_place_buy(line_name, params, ma, current_price):
    trigger_price = ma * (1 - params['offset'])
    if current_price > trigger_price:  
        return

    amount = params['usdt_amount'] / current_price
    buy_order = _create_buy_order(line_name, amount, current_price)
    if not buy_order:
        return

    actual_price, actual_amount = _wait_buy_filled(buy_order['id'])
    if actual_price is None:
        log(f"{line_name} 买入超时或取消，放弃")
        return

    params['occupied'] = True
    params['buy_price'] = actual_price
    params['buy_time'] = datetime.now()
    params['buy_amount'] = actual_amount

    target_price = actual_price * (1 + params['profit_ratio'])
    sell_order = exchange.create_limit_sell_order(symbol, actual_amount, target_price)
    params['sell_order_id'] = sell_order['id']

    log(f"{line_name} 买入成功 @ {actual_price:.2f}，挂止盈 @ {target_price:.2f} "
        f"(+{params['profit_ratio']*100:.1f}%)")


def _create_buy_order(line_name, amount, current_price):
    try:
        order = exchange.create_limit_buy_order(symbol, amount, current_price * 0.999)
        log(f"{line_name} 触发买入 ≈ {amount:.6f} BTC，订单ID: {order['id']}")
        return order
    except Exception as e:
        log(f"{line_name} 下单失败: {e}")
        return None


def _wait_buy_filled(order_id, max_wait=60):
    #only place limit orders
    start = time.time()
    while time.time() - start < max_wait:
        try:
            status = exchange.fetch_order(order_id, symbol)
            if status['status'] == 'closed':
                return float(status['average'] or status['price']), float(status['filled'])
            if status['status'] in ['canceled', 'expired']:
                return None, None
        except Exception as e:
            log(f"查询买入订单失败: {e}")
        time.sleep(3)
    return None, None


def _check_sell_or_timeout(line_name, params, current_price):
    hours_held = (datetime.now() - params['buy_time']).total_seconds() / 3600

    if params['sell_order_id'] and _is_sell_closed(params['sell_order_id']):
        log(f"{line_name} 止盈卖出成功！释放线")
        _reset_line(params)
        return

    if hours_held >= TIMEOUT_HOURS:
        log(f"{line_name} 持仓超 {TIMEOUT_HOURS}h，启动保本卖出")
        cancel_order_if_exists(params['sell_order_id'])
        params['sell_order_id'] = None

        breakeven_price = params['buy_price'] * 1.0001
        sell_price = max(breakeven_price, current_price * 1.001)

        try:
            new_sell = exchange.create_limit_sell_order(symbol, params['buy_amount'], sell_price)
            params['sell_order_id'] = new_sell['id']
            log(f"{line_name} 挂保本卖单 @ {sell_price:.2f}")
        except Exception as e:
            log(f"{line_name} 保本卖单失败: {e}")


def _is_sell_closed(order_id):
    try:
        status = exchange.fetch_order(order_id, symbol)
        return status['status'] == 'closed'
    except:
        return False  # closed = deal 


def _reset_line(params):
    params.update({
        'occupied': False,
        'buy_price': None,
        'buy_time': None,
        'buy_amount': None,
        'sell_order_id': None
    })


# ==================== main ====================
log("交易机器人启动")
while True:
    try:
        ma = calculate_ma()
        current_price = get_current_price()
        log(f"MA({ma_period}): {ma:.2f} | 当前价: {current_price:.2f}")

        process_lines(ma, current_price)

        # normal
        heartbeat = {
            "last_alive": datetime.now().isoformat(),
            "status": "running",
            "price": current_price,
            "ma": ma,
            "active_lines": [k for k, v in lines.items() if v['occupied']]
        }
        with open(HEARTBEAT_FILE, 'w', encoding='utf-8') as f:
            json.dump(heartbeat, f, ensure_ascii=False, indent=2)

        time.sleep(60)

    except Exception as e:
        error_msg = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 错误: {e}\n"
        log(f"严重错误: {e}")
        with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(error_msg)

        # error
        heartbeat = {
            "last_alive": datetime.now().isoformat(),
            "status": "error",
            "error": str(e)
        }
        with open(HEARTBEAT_FILE, 'w', encoding='utf-8') as f:
            json.dump(heartbeat, f, ensure_ascii=False, indent=2)

        time.sleep(30)