import logging
from binance_f import SubscriptionClient
from binance_f.constant.test import *
from binance_f.model import *
from binance_f.exception.binanceapiexception import BinanceApiException
import json
from binance_f import RequestClient
import numpy as np
import talib
import sys
from scipy.stats import norm
import pandas as pd
import os
import psutil


DATA_FILENAME = 'btcusdt_candles.json'
from binance_f.base.printobject import *

logger = logging.getLogger("binance-futures")
logger.setLevel(level=logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

api_key = 'YOUR_API_KEY_HERE'
api_secret = 'YOUR_API_SECRET_HERE'

sub_client = SubscriptionClient(api_key=api_key, secret_key=api_secret)
request_client = RequestClient(api_key=api_key, secret_key=api_secret)

### PARAMETERS ###
# symbol to trade
symbol = 'ETCUSDT'
# order quantity
order_quantity = 7.77
# states
IDLE = 0
INVESTED = 1
state = IDLE

# cooldown time between last sell
wait_time = 5 * 1000
# last sell cooldown flag
sell_execute = False
# binance API precision parameters
quote_precision = 0
price_precision = 2
# time of last order sell
last_sell_time = 0

# misc parameters
ticker_list = []
profit = 0
profit_bound = 0
loss_bound = 0
margin_amount = 0
stop_loss_increment = 0.015
stop_loss_increment_mult = 2.8
original_position = None

def append_to_json(_dict, path):
    with open(path, 'ab+') as f:
        f.seek(0, 2)  # Go to the end of file
        if os.stat(path).st_size == 0:  # Check if file is empty
            f.write(json.dumps([_dict]).encode())  # If empty, write an array
        else:
            f.seek(-1, 2)
            f.truncate()  # Remove the last character, open the array
            f.write(' , '.encode())  # Write the separator
            f.write(json.dumps(_dict).encode())  # Dump the dictionary
            f.write(']'.encode())


# Disable stdout
def blockPrint():
    sys.stdout = open(os.devnull, 'w')


# Restore stdout
def enablePrint():
    sys.stdout = sys.__stdout__

def restart_program():
    """Restarts the current program, with file objects and descriptors
       cleanup
    """

    try:
        p = psutil.Process(os.getpid())
        for handler in p.get_open_files() + p.connections():
            os.close(handler.fd)
    except Exception as e:
        logging.error(e)

    python = sys.executable
    os.execl(python, python, *sys.argv)


def check_position(request_client, symbol, order_quantity):
    position = request_client.get_position()
    ret = None
    for j in position:
        if j.symbol == symbol and j.positionAmt == order_quantity:
            ret = j
            break

    return ret


def callback(data_type: 'SubscribeMessageType', event: 'any'):

    global state, profit_bound, loss_bound
    global order_quantity, profit, margin_amount
    global symbol, stop_loss_increment, original_position
    global sell_execute, last_sell_time, wait_time, price_precision

    ### *** ###
    DEBUG = False

    if data_type == SubscribeMessageType.RESPONSE:
        #print("Event ID: ", event)
        pass
    elif data_type == SubscribeMessageType.PAYLOAD:
        '''
        print("Event type: ", event.eventType)
        print("Event time: ", event.eventTime)
        print("Symbol: ", event.symbol)
        print("Data:")
        PrintBasic.print_obj(event.data)
        '''
        print("Event type: ", event.eventType)
        print("Event time: ", event.eventTime)

        # STATE EXECUTION AND TRADING BLOCK

        entry = event.data.__dict__
        blockPrint()

        cdls = request_client.get_candlestick_data(
            symbol=symbol,
            interval=CandlestickInterval.MIN1,
            startTime=None,
            endTime=None,
            limit=100)

        cdls_close = [float(x.close) for x in cdls]
        cdls_high = [float(x.high) for x in cdls]
        cdls_low = [float(x.low) for x in cdls]
        cdls_vol = [float(x.volume) for x in cdls]

        upperband, middleband, lowerband = talib.BBANDS(np.array(cdls_close),
                                                        timeperiod=20,
                                                        nbdevup=2,
                                                        nbdevdn=2,
                                                        matype=0)
        mfi = talib.MFI(np.array(cdls_high),
                        np.array(cdls_low),
                        np.array(cdls_close),
                        np.array(cdls_vol),
                        timeperiod=14)

        mfi_thresh = 20
        ticker = [
            x.__dict__
            for x in request_client.get_symbol_price_ticker(symbol=symbol)
        ][0]

        # get VaR of symbol
        rets_15min = (
            pd.DataFrame(cdls_close) / pd.DataFrame(cdls_close).shift(1) -
            1).dropna().values
        mean = np.mean(rets_15min)
        stddev = np.std(rets_15min)

        var_95 = norm.ppf(1 - 0.95, mean, stddev)
        var_68 = norm.ppf(1 - 0.68, mean, stddev)

        symb = request_client.get_exchange_information().symbols
        for k in symb:
            if k.baseAsset in symbol:
                symb = k

        quote_precision = symb.quotePrecision

        # check for postion close cooldown
        if sell_execute:
            if (event.eventTime - last_sell_time) >= wait_time:
                last_sell_time = None
                sell_execute = False
                state = IDLE

        try:
            from subprocess import Popen, PIPE, time

            foo = ticker.update({'time': event.eventTime})
            append_to_json(foo, symbol + '_TICKER.json')

            diff_mfi = np.diff(mfi)
            diff_mfi_2nd = np.diff(diff_mfi)

            enablePrint()
            tz_convert = 25200000
            ts = time.strftime(
                '%Y-%m-%d %H:%M:%S',
                time.gmtime((event.eventTime - tz_convert) / 1000.0))

            print(
                '%s mfi:%12.6f mfi_1_d % 12.6f mfi_2_d %12.6f lower %12.6f ticker %12.6f state %2d'
                % (ts, mfi[-1], diff_mfi[-1], diff_mfi_2nd[-1], lowerband[-1],
                   ticker['price'], state))
            blockPrint()

            ### TODO: modify buying rules here!
            if (np.abs(diff_mfi[-1]) < 1.0 and diff_mfi_2nd[-1] > 0 \
                and not sell_execute \
                and mfi[-1] < 100-mfi_thresh) or DEBUG:

                if state == IDLE:

                    cdls_close = np.array(cdls_close)

                    # check 1st and 2nd diff of 3min close to local min
                    diff_1min = np.diff(cdls_close)
                    abs_last_value = np.abs(diff_1min[-1])

                    diff_1min_2nd = np.diff(diff_1min)
                    abs_last_value_2nd = np.abs(diff_1min_2nd[-1])
                    if True or DEBUG:
                        # place buy order

                        amount_str = "{:0.0{}f}".format(
                            order_quantity, quote_precision)
                        ord_qty = amount_str

                        result = request_client.post_order(
                            symbol=symbol,
                            side=OrderSide.BUY,
                            ordertype=OrderType.MARKET,
                            quantity=ord_qty)

                        position = check_position(request_client, symbol,
                                                  order_quantity)
                        original_position = position

                        margin_amount = position.positionAmt * position.entryPrice / position.leverage

                        # place initial trailing stop limit sell

                        stop_loss_price = position.entryPrice * (
                            1 - np.abs(var_95))
                        stop_loss_price = np.round(stop_loss_price,
                                                   price_precision)

                        stop_loss_price = "{:0.0{}f}".format(
                            stop_loss_price, quote_precision)

                        result = request_client.post_order(
                            symbol=symbol,
                            side=OrderSide.SELL,
                            ordertype=OrderType.STOP_MARKET,
                            quantity=ord_qty,
                            stopPrice=stop_loss_price,
                            workingType='MARK_PRICE')

                        enablePrint()
                        if not DEBUG:
                            pass
                            #Process = Popen('./send_sms_bot.sh %s' % (str(ticker['price'])), shell=True)
                        print('***bought %s at %12.4f. stop loss %10.4f' %
                              (symbol, position.entryPrice,
                               float(stop_loss_price)))
                        blockPrint()

                        state = INVESTED

            if state == INVESTED and sell_execute is False:

                blockPrint()

                # check if position already hit a stop limit
                position_check = check_position(request_client, symbol,
                                                order_quantity)

                if position_check is not None:

                    order = request_client.get_open_orders()

                    # find previous stop limit order
                    for k in order:
                        if k.symbol == symbol and k.origQty == order_quantity and k.workingType == 'MARK_PRICE':
                            order = k
                            break

                    ### TODO: modify selling rules here!
                    if (np.abs(diff_mfi[-1]) < 1.0 and diff_mfi_2nd[-1] < 0)  \
                        and (ticker['price'] > original_position.entryPrice) \
                        and mfi[-1] > mfi_thresh \
                            or DEBUG==True:
                        # cancel previous stop
                        try:
                            request_client.cancel_order(
                                symbol, order.orderId, order.clientOrderId)
                        except:
                            pass

                        amount_str = "{:0.0{}f}".format(
                            order_quantity, quote_precision)
                        ord_qty = amount_str

                        margin_amount = original_position.positionAmt * original_position.entryPrice / original_position.leverage

                        # place initial trailing stop limit sell
                        stop_loss_price = ticker['price']
                        stop_loss_price = np.round(stop_loss_price,
                                                   price_precision)

                        stop_loss_price = "{:0.0{}f}".format(
                            stop_loss_price, quote_precision)

                        result = request_client.post_order(
                            symbol=symbol,
                            side=OrderSide.SELL,
                            ordertype=OrderType.STOP_MARKET,
                            quantity=ord_qty,
                            stopPrice=stop_loss_price,
                            workingType='MARK_PRICE')
                        enablePrint()
                        if not DEBUG:
                            print(
                                '***trailing stop loss %s at %12.4f. stop loss %10.4f'
                                % (symbol, ticker['price'],
                                   float(stop_loss_price)))
                        blockPrint()
                        STATE = INVESTED
                else:
                    order = request_client.get_open_orders()

                    # cancel stop orders without positions
                    for k in order:
                        if k.symbol == symbol and k.origQty == order_quantity and k.workingType == 'MARK_PRICE':
                            try:
                                request_client.cancel_order(
                                    symbol, k.orderId, k.clientOrderId)
                            except:
                                pass
                            break

                    # stop was executed while in INVESTED state
                    sell_execute = True
                    last_sell_time = event.eventTime
                    enablePrint()
                    if not DEBUG:
                        print('***position closed')
                    blockPrint()

        except Exception as e:
            enablePrint()
            print(str(e))
            blockPrint()
            exit(1)
            pass

        #sub_client.unsubscribe_all()
    else:
        print("Unknown Data:")


############


def error(e: 'BinanceApiException'):
    print(e.error_code + e.error_message)
    restart_program()


from threading import Timer


class RepeatTimer(Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)


blockPrint()
# check for existing position routine
order = request_client.get_open_orders()
stop_limit_exists = None
for k in order:
    if k.symbol == symbol and k.origQty == order_quantity and k.workingType == 'MARK_PRICE':
        stop_limit_exists = k
        break

if stop_limit_exists is not None:
    original_position = check_position(request_client, symbol, order_quantity)
    if original_position is not None:
        state = INVESTED
else:
    original_position = check_position(request_client, symbol, order_quantity)
    if original_position is not None:
        state = INVESTED

enablePrint()
print('***')
print(symbol, 'quantity', order_quantity)

print(original_position)

sub_client.subscribe_candlestick_event(symbol.lower(),
                                       CandlestickInterval.MIN1, callback,
                                       error)
