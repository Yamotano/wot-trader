### WoT-Trader v0.01

![](https://miro.medium.com/max/890/0*cAcircdzEscM4Rk9.jpg)

#### Trading bot for Binance Futures

A simple bot that tracks the Money Flow Index (MFI) technical indicator and
trades based on sub 1-minute timeframes. Executes longs only.

Implements the classic 'buy low sell high' strategy and looks at the value of the MFI, and its 1st and 
2nd finite differences to determine when an MFI minimum (buy) and MFI maximum (sell) has beem reached.

Also compute the Value-at-risk (VaR) for the last 100 minutes and set an initial stop loss at the 95% VaR
loss level.

#### Note:
1. You must provide your own Binance API key and API secret in the script file
2. You must also install the dependencies such as the Binance Futures Python API and TA-Lib
- https://github.com/Binance-docs/Binance_Futures_python
- https://mrjbq7.github.io/ta-lib/doc_index.html

If you wish to support the author please consider the Binance referral code: 
https://www.binance.com/en/register?ref=SJJHLU6M - You will receive a 5% kickback

To run the model: python mfi_bot.py

__For educational purposes only! Not to be used for actual investment. The author is 
not resposible for any misuse of the code contained within this repo.__
