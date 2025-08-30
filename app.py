from __future__ import annotations
"""
Binance Futures Bot - Web Application v10.5
Production-ready Flask web application for server deployment
"""
import os, time, math, logging, threading
import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json

from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, FUTURE_ORDER_TYPE_MARKET, FUTURE_ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC
from binance.exceptions import BinanceAPIException

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS

from sqlalchemy import desc, func
from database import SessionLocal, Trade, PerformanceMetrics

# -------------------- CONFIGURATION -------------------- #
@dataclass
class CONFIG:
    # Global Configuration (Editable from web)
    LEVERAGE: int = 50
    MAX_CONCURRENT_POS: int = 30
    FIXED_MARGIN_PER_TRADE_USDT: float = 4.0
    NUM_SYMBOLS_TO_SCAN: int = 300
    # Strategy Configuration (Editable from web)
    ATR_MULT_SL: float = 3.0
    ATR_MULT_TP: float = 7.0
    # Trailing Stop Configuration
    TRAILING_STOP_ACTIVATION: float = 0.9  # % de ganancia para activar trailing stop
    TRAILING_STOP_PERCENTAGE: float = 0.6  # % de retroceso para cerrar
    # Fixed SL/TP Configuration
    USE_FIXED_SL_TP: bool = True  # Enable fixed stop loss and take profit
    STOP_LOSS_PERCENT: float = 2.0  # % stop loss from entry price
    TAKE_PROFIT_PERCENT: float = 3.0  # % take profit from entry price
    # Fixed Configuration
    MARGIN_TYPE: str = "CROSSED"
    MIN_24H_VOLUME: float = 20_000_000
    EXCLUDE_SYMBOLS: tuple = ("BTCDOMUSDT", "DEFIUSDT", "USDCUSDT", "TUSDUSDT")
    TIMEFRAME: str = "5m"
    CANDLES_LIMIT: int = 100
    FAST_EMA: int = 9
    SLOW_EMA: int = 21
    RSI_PERIOD: int = 14
    POLL_SEC: float = 10.0
    DRY_RUN: bool = False
    MAX_WORKERS_KLINE: int = 20
    LOG_LEVEL: str = "DEBUG"
    LOG_FILE: str = "bot_v10.log"
    LOG_FORMAT: str = "%(asctime)s - %(levelname)s - %(message)s"
    SIGNAL_COOLDOWN_CYCLES: int = 30
    # Balance monitoring
    MIN_BALANCE_THRESHOLD: float = 10.0  # Minimum USDT balance before stopping trades
    RISK_PER_TRADE_PERCENT: float = 1.0  # Max risk per trade as % of balance

config = CONFIG()

# -------------------- STRATEGY OPTIMIZER CONFIG -------------------- #
@dataclass
class STRATEGY_OPTIMIZER:
    OPTIMIZATION_INTERVAL: int = 24  # horas
    MIN_TRADES_FOR_ANALYSIS: int = 10
    LEVERAGE_ADJUSTMENT_STEP: int = 5
    MAX_LEVERAGE: int = 100
    MIN_LEVERAGE: int = 5
    VOLATILITY_THRESHOLD: float = 2.0  # ATR porcentual

strategy_optimizer = STRATEGY_OPTIMIZER()

# -------------------- FLASK APP SETUP -------------------- #
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
CORS(app)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# -------------------- LOGGING SETUP -------------------- #
class SocketIOHandler(logging.Handler):
    def emit(self, record):
        try:
            log_entry = self.format(record)
            level = record.levelname.lower()
            socketio.emit('log_update', {'message': log_entry, 'level': level})
        except Exception:
            pass

log = logging.getLogger("BinanceFuturesBot")
log.setLevel(getattr(logging, config.LOG_LEVEL))
if not log.handlers:
    formatter = logging.Formatter(config.LOG_FORMAT)
    
    # File handler
    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler(f'logs/{config.LOG_FILE}', encoding='utf-8', mode='a')
    file_handler.setFormatter(formatter)
    
    # Socket handler for real-time updates
    socket_handler = SocketIOHandler()
    socket_handler.setFormatter(formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    log.addHandler(file_handler)
    log.addHandler(socket_handler)
    log.addHandler(console_handler)

# Suppress verbose logging from external libraries
for logger_name in ['binance', 'engineio', 'socketio', 'werkzeug', 'urllib3']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# -------------------- GLOBAL STATE -------------------- #
bot_thread = None
_trailing_monitor_thread = None
app_state = {
    "running": False,
    "status_message": "Stopped",
    "open_positions": {},
    "trailing_stop_data": {},
    "sl_tp_data": {},
    "config": asdict(config),
    "performance_stats": {
        "realized_pnl": 0.0,
        "trades_count": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "profit_factor": 0.0
    },
    "balance": 0.0,
    "total_investment_usd": 0.0,
    "trades_history": [],
    "balance_history": [],
    "risk_metrics": {
        "max_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "profit_per_day": 0.0,
        "exposure_ratio": 0.0
    }
}
state_lock = threading.Lock()

# -------------------- BINANCE CLIENT -------------------- #
class BinanceFutures:
    def __init__(self):
        load_dotenv()
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")
        testnet = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
        
        if not api_key or not api_secret:
            raise ValueError("API keys not configured. Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables")
        
        self.client = Client(api_key, api_secret, testnet=testnet)
        log.info(f"🔧 CONNECTED TO BINANCE FUTURES {'TESTNET' if testnet else 'MAINNET'}")
        
        try:
            self.exchange_info = self.client.futures_exchange_info()
            log.info("✅ Exchange information loaded successfully")
        except Exception as e:
            log.error(f"❌ Error connecting to Binance: {e}")
            raise

    def ensure_symbol_settings(self, symbol: str):
        try:
            _ = self._safe_api_call(self.client.futures_change_leverage, symbol=symbol, leverage=int(config.LEVERAGE))
        except Exception as e:
            log.warning(f"Leverage set issue for {symbol}: {e}")
        
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType=config.MARGIN_TYPE)
        except BinanceAPIException as e:
            if e.code == -4046 or "No need to change margin type" in e.message:
                pass
            else:
                log.warning(f"Margin type set warning for {symbol}: {e}")
        except Exception as e:
            log.error(f"An unexpected error occurred setting margin type for {symbol}: {e}")

    def _safe_api_call(self, func, *args, **kwargs):
        for attempt in range(3):
            try:
                time.sleep(0.1)
                return func(*args, **kwargs)
            except BinanceAPIException as e:
                if e.code == -4131:
                    log.warning("PERCENT_PRICE error (-4131) in order. Volatile or illiquid market. Skipping.")
                    return None
                log.warning(f"API non-critical error: {e.message}")
                if attempt == 2:
                    log.error(f"Final API error: {e.code} - {e.message}")
                time.sleep(1 * (attempt + 1))
            except Exception as e:
                log.warning(f"General API call error: {e}")
                if attempt == 2:
                    log.error(f"Final general error: {e}")
                time.sleep(1 * (attempt + 1))
        return None

    def get_symbol_filters(self, symbol: str) -> Optional[Dict[str, float]]:
        s_info = next((s for s in self.exchange_info['symbols'] if s['symbol'] == symbol), None)
        if not s_info:
            return None
        
        filters = {f['filterType']: f for f in s_info['filters']}
        return {
            "stepSize": float(filters['LOT_SIZE']['stepSize']),
            "minQty": float(filters['LOT_SIZE']['minQty']),
            "tickSize": float(filters['PRICE_FILTER']['tickSize']),
            "minNotional": float(filters.get('MIN_NOTIONAL', {}).get('notional', 5.0))
        }

    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, 
                   price: Optional[float] = None, reduce_only: bool = False) -> Optional[Dict]:
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity
        }
        
        if order_type == FUTURE_ORDER_TYPE_LIMIT:
            if price is None:
                log.error("Price required for LIMIT orders.")
                return None
            params.update({
                'price': str(price),
                'timeInForce': TIME_IN_FORCE_GTC
            })
        
        if reduce_only:
            params['reduceOnly'] = 'true'
        
        if config.DRY_RUN:
            log.info(f"[DRY_RUN] place_order: {params}")
            return {'mock': True}
            
        return self._safe_api_call(self.client.futures_create_order, **params)

    def close_position(self, symbol: str, position_amt: float) -> Optional[Dict]:
        side = SIDE_SELL if position_amt > 0 else SIDE_BUY
        if config.DRY_RUN:
            log.info(f"[DRY_RUN] close_position {symbol} {position_amt}")
            return {'mock': True}
        return self.place_order(symbol, side, FUTURE_ORDER_TYPE_MARKET, abs(position_amt), reduce_only=True)

    def cancel_order(self, symbol: str, orderId: int) -> Optional[Dict]:
        if config.DRY_RUN:
            log.info(f"[DRY_RUN] cancel_order: {orderId} for {symbol}")
            return {'mock': True}
            
        try:
            return self._safe_api_call(self.client.futures_cancel_order, symbol=symbol, orderId=orderId)
        except Exception as e:
            log.warning(f"Could not cancel order {orderId} for {symbol}: {e}")
            return None

    @staticmethod
    def round_value(value: float, step: float) -> float:
        if step == 0:
            return value
        precision = max(0, int(round(-math.log10(step))))
        return round(math.floor(value / step) * step, precision)

# -------------------- TRADING BOT -------------------- #
class TradingBot:
    def __init__(self):
        self.api = BinanceFutures()
        self.recently_signaled = set()
        self.cycle_count = 0

    def get_top_symbols(self) -> List[str]:
        tickers = self.api._safe_api_call(self.api.client.futures_ticker)
        if not tickers:
            return []
        
        valid_tickers = [
            t for t in tickers
            if t['symbol'].endswith('USDT')
            and t['symbol'] not in config.EXCLUDE_SYMBOLS
            and float(t['quoteVolume']) > config.MIN_24H_VOLUME
        ]
        
        sorted_tickers = sorted(valid_tickers, key=lambda x: float(x['quoteVolume']), reverse=True)
        return [t['symbol'] for t in sorted_tickers[:config.NUM_SYMBOLS_TO_SCAN]]

    def get_klines_for_symbol(self, symbol: str) -> Optional[pd.DataFrame]:
        klines = self.api._safe_api_call(
            self.api.client.futures_klines,
            symbol=symbol,
            interval=config.TIMEFRAME,
            limit=config.CANDLES_LIMIT
        )
        
        if not klines:
            return None
        
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df.dropna(subset=['close'], inplace=True)
        return df

    def calculate_indicators(self, df: pd.DataFrame):
        df['fast_ema'] = df['close'].ewm(span=config.FAST_EMA, adjust=False).mean()
        df['slow_ema'] = df['close'].ewm(span=config.SLOW_EMA, adjust=False).mean()
        
        delta = df['close'].diff()
        up = np.maximum(delta, 0)
        down = -np.minimum(delta, 0)
        
        roll_up = pd.Series(up).ewm(span=config.RSI_PERIOD, adjust=False).mean()
        roll_down = pd.Series(down).ewm(span=config.RSI_PERIOD, adjust=False).mean()
        
        rs = roll_up / roll_down.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        df['rsi'] = rsi.fillna(50)

    def check_signal(self, df: pd.DataFrame) -> Optional[str]:
        if len(df) < 2:
            return None
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        if (last['fast_ema'] > last['slow_ema'] and 
            prev['fast_ema'] <= prev['slow_ema'] and 
            last['rsi'] > 50):
            return 'LONG'
        
        if (last['fast_ema'] < last['slow_ema'] and 
            prev['fast_ema'] >= prev['slow_ema'] and 
            last['rsi'] < 50):
            return 'SHORT'
        
        return None

    def check_trailing_stop(self, symbol: str, position: Dict, current_price: float):
        with state_lock:
            trailing_data = app_state["trailing_stop_data"].get(symbol, {})
            position_side = 'LONG' if float(position['positionAmt']) > 0 else 'SHORT'
            entry_price = float(position['entryPrice'])
            
            if symbol not in app_state["trailing_stop_data"]:
                app_state["trailing_stop_data"][symbol] = {
                    'activated': False,
                    'best_price': entry_price,
                    'current_stop': entry_price,
                    'side': position_side,
                    'last_stop_price': 0.0,
                    'stop_order_id': None
                }
                # BUG FIX: Re-assign the local variable after initialization
                trailing_data = app_state["trailing_stop_data"][symbol]
            
            if position_side == 'LONG':
                if current_price > trailing_data['best_price']:
                    trailing_data['best_price'] = current_price
                    log.info(f"📈 Nuevo mejor precio para {symbol}: {current_price}")
                
                profit_percentage = ((current_price - entry_price) / entry_price) * 100 * config.LEVERAGE
                
                if not trailing_data['activated'] and profit_percentage >= config.TRAILING_STOP_ACTIVATION:
                    trailing_data['activated'] = True
                    trailing_data['current_stop'] = trailing_data['best_price'] * (1 - config.TRAILING_STOP_PERCENTAGE / 100)
                    log.info(f"🔔 Trailing stop activado para {symbol} @ {trailing_data['current_stop']}")
                
                if trailing_data['activated']:
                    new_stop = trailing_data['best_price'] * (1 - config.TRAILING_STOP_PERCENTAGE / 100)
                    if new_stop > trailing_data['current_stop']:
                        trailing_data['current_stop'] = new_stop
                        log.info(f"🔄 Trailing stop actualizado para {symbol}: {new_stop}")
                
                if trailing_data['activated'] and current_price <= trailing_data['current_stop']:
                    log.info(f"🔴 Cierre por trailing stop: {symbol} @ {current_price} (Stop: {trailing_data['current_stop']})")
                    return True
            else: # SHORT position
                if current_price < trailing_data['best_price']:
                    trailing_data['best_price'] = current_price
                    log.info(f"📉 Nuevo mejor precio para {symbol}: {current_price}")
                
                profit_percentage = ((entry_price - current_price) / entry_price) * 100 * config.LEVERAGE
                
                if not trailing_data['activated'] and profit_percentage >= config.TRAILING_STOP_ACTIVATION:
                    trailing_data['activated'] = True
                    trailing_data['current_stop'] = trailing_data['best_price'] * (1 + config.TRAILING_STOP_PERCENTAGE / 100)
                    log.info(f"🔔 Trailing stop activado para {symbol} @ {trailing_data['current_stop']}")
                
                if trailing_data['activated']:
                    new_stop = trailing_data['best_price'] * (1 + config.TRAILING_STOP_PERCENTAGE / 100)
                    if new_stop < trailing_data['current_stop']:
                        trailing_data['current_stop'] = new_stop
                        log.info(f"🔄 Trailing stop actualizado para {symbol}: {new_stop}")
                
                if trailing_data['activated'] and current_price >= trailing_data['current_stop']:
                    log.info(f"🔴 Cierre por trailing stop: {symbol} @ {current_price} (Stop: {trailing_data['current_stop']})")
                    return True
            
            return False

    def check_fixed_sl_tp(self, symbol: str, position: Dict, current_price: float):
        if not config.USE_FIXED_SL_TP:
            return False
            
        with state_lock:
            sl_tp_data = app_state["sl_tp_data"].get(symbol, {})
            position_side = 'LONG' if float(position['positionAmt']) > 0 else 'SHORT'
            entry_price = float(position['entryPrice'])
            
            if 'sl_price' not in sl_tp_data:
                if position_side == 'LONG':
                    sl_price = entry_price * (1 - config.STOP_LOSS_PERCENT / 100)
                    tp_price = entry_price * (1 + config.TAKE_PROFIT_PERCENT / 100)
                else:
                    sl_price = entry_price * (1 + config.STOP_LOSS_PERCENT / 100)
                    tp_price = entry_price * (1 - config.TAKE_PROFIT_PERCENT / 100)
                
                app_state["sl_tp_data"][symbol] = {
                    'sl_price': sl_price,
                    'tp_price': tp_price,
                    'side': position_side,
                    'entry_price': entry_price
                }
                sl_tp_data = app_state["sl_tp_data"][symbol]
                log.info(f"Initialized SL/TP for {symbol}: SL @ {sl_price:.4f}, TP @ {tp_price:.4f}")

            sl_price = sl_tp_data.get('sl_price')
            tp_price = sl_tp_data.get('tp_price')

            if not sl_price or not tp_price:
                log.warning(f"SL/TP prices not found for {symbol} after initialization attempt.")
                return False

            if position_side == 'LONG':
                if current_price <= sl_price:
                    log.info(f"🔴 Cierre por STOP LOSS: {symbol} @ {current_price} (SL: {sl_price})")
                    return 'SL'
                elif current_price >= tp_price:
                    log.info(f"🟢 Cierre por TAKE PROFIT: {symbol} @ {current_price} (TP: {tp_price})")
                    return 'TP'
            else:
                if current_price >= sl_price:
                    log.info(f"🔴 Cierre por STOP LOSS: {symbol} @ {current_price} (SL: {sl_price})")
                    return 'SL'
                elif current_price <= tp_price:
                    log.info(f"🟢 Cierre por TAKE PROFIT: {symbol} @ {current_price} (TP: {tp_price})")
                    return 'TP'
            
            return False

    def check_balance_risk(self, account_info):
        if not account_info:
            return False
            
        usdt_balance = next((float(a.get('walletBalance', 0) or 0) for a in account_info.get('assets', []) if a.get('asset') == 'USDT'), 0.0)
        
        if usdt_balance < config.MIN_BALANCE_THRESHOLD:
            log.warning(f"⚠️ Balance bajo: {usdt_balance} USDT (mínimo: {config.MIN_BALANCE_THRESHOLD} USDT)")
            return True
            
        open_positions = {p['symbol']: p for p in account_info['positions'] if float(p['positionAmt']) != 0}
        total_investment = sum(float(p.get('initialMargin', 0) or 0) for p in open_positions.values())
        exposure_ratio = total_investment / usdt_balance if usdt_balance > 0 else 0
        
        with state_lock:
            app_state["risk_metrics"]["exposure_ratio"] = exposure_ratio
            if len(app_state["balance_history"]) > 0:
                peak = max(app_state["balance_history"])
                current = usdt_balance
                drawdown = (peak - current) / peak * 100 if peak > 0 else 0
                app_state["risk_metrics"]["max_drawdown"] = max(app_state["risk_metrics"]["max_drawdown"], drawdown)
            
            app_state["balance_history"].append(usdt_balance)
            if len(app_state["balance_history"]) > 100:
                app_state["balance_history"].pop(0)
        
        return False

    def analyze_trading_performance(self, symbol: str):
        try:
            db = SessionLocal()
            
            recent_trades = db.query(Trade).filter(
                Trade.symbol == symbol,
                Trade.timestamp >= datetime.now() - timedelta(hours=strategy_optimizer.OPTIMIZATION_INTERVAL)
            ).all()
            
            if len(recent_trades) < strategy_optimizer.MIN_TRADES_FOR_ANALYSIS:
                return None
                
            winning_trades = [t for t in recent_trades if t.pnl > 0]
            losing_trades = [t for t in recent_trades if t.pnl < 0]
            
            win_rate = len(winning_trades) / len(recent_trades) if recent_trades else 0
            avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
            avg_loss = abs(sum(t.pnl for t in losing_trades) / len(losing_trades)) if losing_trades else 0
            profit_factor = (avg_win * len(winning_trades)) / (avg_loss * len(losing_trades)) if losing_trades else float('inf')
            
            klines = self.get_klines_for_symbol(symbol)
            if klines is not None:
                high_low = klines['high'] - klines['low']
                high_close = abs(klines['high'] - klines['close'].shift())
                low_close = abs(klines['low'] - klines['close'].shift())
                true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
                atr = true_range.rolling(14).mean().iloc[-1] / klines['close'].iloc[-1] * 100
            else:
                atr = 0
                
            if win_rate > 0.7 and profit_factor > 2.0:
                recommended_leverage = min(config.LEVERAGE + strategy_optimizer.LEVERAGE_ADJUSTMENT_STEP, 
                                         strategy_optimizer.MAX_LEVERAGE)
            elif win_rate < 0.3 or profit_factor < 1.0:
                recommended_leverage = max(config.LEVERAGE - strategy_optimizer.LEVERAGE_ADJUSTMENT_STEP, 
                                         strategy_optimizer.MIN_LEVERAGE)
            else:
                recommended_leverage = config.LEVERAGE
                
            if atr > strategy_optimizer.VOLATILITY_THRESHOLD:
                recommended_leverage = max(recommended_leverage - strategy_optimizer.LEVERAGE_ADJUSTMENT_STEP, 
                                         strategy_optimizer.MIN_LEVERAGE)
                
            strategy_effectiveness = win_rate * profit_factor if profit_factor != float('inf') else win_rate * 10
            
            metrics = PerformanceMetrics(
                symbol=symbol,
                win_rate=win_rate,
                profit_factor=profit_factor,
                avg_win=avg_win,
                avg_loss=avg_loss,
                recommended_leverage=recommended_leverage,
                strategy_effectiveness=strategy_effectiveness,
                market_volatility=atr
            )
            
            db.add(metrics)
            db.commit()
            
            log.info(f"📊 Análisis de rendimiento para {symbol}: "
                    f"Win Rate: {win_rate:.2%}, "
                    f"Profit Factor: {profit_factor:.2f}, "
                    f"Leverage Recomendado: {recommended_leverage}x")
                    
            return {
                'recommended_leverage': recommended_leverage,
                'win_rate': win_rate,
                'profit_factor': profit_factor,
                'strategy_effectiveness': strategy_effectiveness
            }
            
        except Exception as e:
            log.error(f"Error analizando rendimiento para {symbol}: {e}")
            return None
        finally:
            db.close()

    def optimize_strategy_based_on_losses(self):
        try:
            db = SessionLocal()
            
            losing_trades = db.query(Trade).filter(
                Trade.pnl < 0,
                Trade.timestamp >= datetime.now() - timedelta(hours=strategy_optimizer.OPTIMIZATION_INTERVAL)
            ).all()
            
            if not losing_trades:
                return
                
            losing_symbols = [t.symbol for t in losing_trades]
            symbol_loss_count = {symbol: losing_symbols.count(symbol) for symbol in set(losing_symbols)}
            
            total_trades_by_symbol = {}
            for symbol in set(losing_symbols):
                total_trades = db.query(Trade).filter(
                    Trade.symbol == symbol,
                    Trade.timestamp >= datetime.now() - timedelta(hours=strategy_optimizer.OPTIMIZATION_INTERVAL)
                ).count()
                total_trades_by_symbol[symbol] = total_trades
                
            problem_symbols = {
                symbol: loss_count / total_trades_by_symbol[symbol]
                for symbol, loss_count in symbol_loss_count.items()
                if total_trades_by_symbol[symbol] > 0 and loss_count / total_trades_by_symbol[symbol] > 0.7
            }
            
            for symbol, loss_ratio in problem_symbols.items():
                log.warning(f"⚠️ Símbolo problemático detectado: {symbol} con {loss_ratio:.2%} de trades perdedores")
                
        except Exception as e:
            log.error(f"Error optimizando estrategia basada en pérdidas: {e}")
        finally:
            db.close()

    def run(self):
        log.info(f"🚀 STARTING TRADING BOT v10.5 (DRY RUN: {config.DRY_RUN})")
        
        while True:
            with state_lock:
                if not app_state["running"]:
                    break
            
            try:
                self.cycle_count += 1
                log.info(f"--- 🔄 New scanning cycle ({self.cycle_count}) ---")

                if self.cycle_count % config.SIGNAL_COOLDOWN_CYCLES == 1 and self.cycle_count > 1:
                    log.info("🧹 Cleaning recent signals memory (cooldown).")
                    self.recently_signaled.clear()
                
                account_info = self.api._safe_api_call(self.api.client.futures_account)
                if not account_info:
                    time.sleep(config.POLL_SEC)
                    continue
                
                low_balance = self.check_balance_risk(account_info)
                if low_balance:
                    log.warning("⏸️ Pausando nuevas operaciones por balance bajo")
                
                open_positions = {p['symbol']: p for p in account_info['positions'] if float(p['positionAmt']) != 0}
                
                for symbol, position in open_positions.items():
                    try:
                        ticker = self.api._safe_api_call(self.api.client.futures_symbol_ticker, symbol=symbol)
                        if not ticker:
                            continue
                        
                        current_price = float(ticker['price'])
                        should_close_trailing = self.check_trailing_stop(symbol, position, current_price)
                        sl_tp_signal = self.check_fixed_sl_tp(symbol, position, current_price)
                        should_close = should_close_trailing or (sl_tp_signal in ['SL', 'TP'])
                        
                        if should_close and not config.DRY_RUN:
                            result = self.api.close_position(symbol, float(position['positionAmt']))
                            
                            if result:
                                pnl_records = self.api._safe_api_call(self.api.client.futures_account_trades, symbol=symbol, limit=10)
                                realized_pnl = 0.0
                                if pnl_records:
                                    realized_pnl = sum(float(trade.get('realizedPnl', 0)) for trade in pnl_records if trade.get('orderId') == result.get('orderId'))
                                
                                close_type = "trailing_stop" if should_close_trailing else sl_tp_signal.lower()
                                
                                with state_lock:
                                    stats = app_state["performance_stats"]
                                    stats["realized_pnl"] += realized_pnl
                                    stats["trades_count"] += 1
                                    
                                    trade_record = {
                                        "symbol": symbol,
                                        "side": 'LONG' if float(position['positionAmt']) > 0 else 'SHORT',
                                        "quantity": abs(float(position['positionAmt'])),
                                        "entryPrice": float(position['entryPrice']),
                                        "exitPrice": current_price,
                                        "pnl": realized_pnl,
                                        "roe": (realized_pnl / (abs(float(position['positionAmt'])) * float(position['entryPrice']))) * 100 * config.LEVERAGE if float(position['entryPrice']) else 0.0,
                                        "closeType": close_type,
                                        "timestamp": time.time(),
                                        "date": datetime.now().isoformat()
                                    }
                                    app_state["trades_history"].append(trade_record)
                                    
                                    if realized_pnl >= 0:
                                        stats["wins"] += 1
                                    else:
                                        stats["losses"] += 1
                                    
                                    if symbol in app_state["trailing_stop_data"]:
                                        del app_state["trailing_stop_data"][symbol]
                                    
                                    if symbol in app_state["sl_tp_data"]:
                                        del app_state["sl_tp_data"][symbol]
                                
                                log.info(f"✅ Position closed: {symbol}, PnL: {realized_pnl:.2f} USDT, Reason: {close_type}")
                    
                    except Exception as e:
                        log.error(f"Error checking stops for {symbol}: {e}", exc_info=True)
                
                if open_positions:
                    socketio.emit('pnl_update', {
                        p['symbol']: float(p.get('unrealizedProfit', 0) or 0)
                        for p in open_positions.values()
                    })

                if self.cycle_count % 6 == 0:
                    try:
                        self.optimize_strategy_based_on_losses()
                        for symbol in open_positions.keys():
                            self.analyze_trading_performance(symbol)
                    except Exception as e:
                        log.error(f"Error en análisis de rendimiento: {e}")

                num_open_pos = len(open_positions)
                if num_open_pos < config.MAX_CONCURRENT_POS and not low_balance:
                    symbols_to_scan = [s for s in self.get_top_symbols() if s not in open_positions and s not in self.recently_signaled]
                    log.info(f"🔍 Scanning {len(symbols_to_scan)} symbols for new signals.")
                    
                    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS_KLINE) as executor:
                        futures = {executor.submit(self.get_klines_for_symbol, s): s for s in symbols_to_scan}
                        
                        for future in futures:
                            symbol = futures[future]
                            df = future.result()
                            
                            if df is None or len(df) < config.SLOW_EMA:
                                continue
                            
                            self.calculate_indicators(df)
                            signal = self.check_signal(df)
                            
                            if signal:
                                log.info(f"🔥 Signal found! {signal} on {symbol}")
                                self.recently_signaled.add(symbol)
                                self.open_trade(symbol, signal, df.iloc[-1])
                                if len(open_positions) + 1 >= config.MAX_CONCURRENT_POS:
                                    log.info("🚫 Concurrent positions limit reached.")
                                    break
                
                with state_lock:
                    stats = app_state["performance_stats"]
                    if stats["trades_count"] > 0:
                        stats["win_rate"] = (stats["wins"] / stats["trades_count"]) * 100
                        winning_trades = [t for t in app_state["trades_history"] if t.get('pnl', 0) > 0]
                        stats["avg_win"] = sum(t.get('pnl', 0) for t in winning_trades) / len(winning_trades) if winning_trades else 0
                        losing_trades = [t for t in app_state["trades_history"] if t.get('pnl', 0) < 0]
                        stats["avg_loss"] = abs(sum(t.get('pnl', 0) for t in losing_trades) / len(losing_trades)) if losing_trades else 0
                        total_win = sum(t.get('pnl', 0) for t in app_state["trades_history"] if t.get('pnl', 0) > 0)
                        total_loss = abs(sum(t.get('pnl', 0) for t in app_state["trades_history"] if t.get('pnl', 0) < 0))
                        stats["profit_factor"] = total_win / total_loss if total_loss > 0 else float('inf')

                    usdt_balance = next((float(a.get('walletBalance', 0) or 0) for a in account_info.get('assets', []) if a.get('asset') == 'USDT'), 0.0)
                    
                    app_state.update({
                        "status_message": "Running",
                        "balance": usdt_balance,
                        "open_positions": open_positions,
                        "total_investment_usd": sum(float(p.get('initialMargin', 0) or 0) for p in open_positions.values()),
                        "performance_stats": stats
                    })
                    socketio.emit('status_update', app_state)

            except Exception as e:
                log.error(f"Error in main loop: {e}", exc_info=True)
            
            time.sleep(config.POLL_SEC)
        
        log.info("🛑 Bot stopped.")

    def open_trade(self, symbol: str, side: str, last_candle):
        if config.DRY_RUN:
            log.info(f"[DRY RUN] Would open {side} on {symbol}")
            return

        self.api.ensure_symbol_settings(symbol)
        filters = self.api.get_symbol_filters(symbol)
        if not filters:
            log.error(f"No filters for {symbol}")
            return

        price = float(last_candle['close'])
        
        with state_lock:
            balance = app_state.get("balance", 0)
        
        if balance > 0 and config.RISK_PER_TRADE_PERCENT > 0:
            risk_amount = balance * (config.RISK_PER_TRADE_PERCENT / 100)
            quantity = (risk_amount * config.LEVERAGE) / price
        else:
            quantity = (config.FIXED_MARGIN_PER_TRADE_USDT * config.LEVERAGE) / price
            
        quantity = self.api.round_value(quantity, filters['stepSize'])

        if quantity < filters['minQty'] or (quantity * price) < filters['minNotional']:
            log.warning(f"Quantity {quantity} for {symbol} is below minimum allowed.")
            return

        order_side = SIDE_BUY if side == 'LONG' else SIDE_SELL
        tick_size = filters['tickSize']
        
        limit_price = price + tick_size * 5 if side == 'LONG' else price - tick_size * 5
        limit_price = self.api.round_value(limit_price, tick_size)
        
        log.info(f"Attempting to place LIMIT order for {side} {symbol} @ {limit_price}")
        order = self.api.place_order(symbol, order_side, FUTURE_ORDER_TYPE_LIMIT, quantity, price=limit_price)

        if order and order.get('orderId'):
            log.info(f"✅ LIMIT ORDER CREATED: {side} {quantity} {symbol} @ {limit_price}")
            
            with state_lock:
                if symbol not in app_state["sl_tp_data"]:
                    app_state["sl_tp_data"][symbol] = {
                        'entry_price': limit_price,
                        'side': side
                    }
        else:
            log.error(f"❌ Could not create limit order for {symbol}. Response: {order}")

# -------------------- EXCHANGE TRAILING STOP + MONITOR -------------------- #
def apply_exchange_trailing_stop(binance_api: BinanceFutures, symbol: str):
    """Apply trailing stop using exchange STOP_MARKET orders"""
    try:
        with state_lock:
            trailing_data = app_state["trailing_stop_data"].get(symbol)
        if not trailing_data:
            return
            
        if not trailing_data.get("activated", False):
            return
            
        stop_price = float(trailing_data.get("current_stop", 0) or 0)
        last_stop = float(trailing_data.get("last_stop_price", 0) or 0)
        
        if last_stop != 0 and math.isclose(last_stop, stop_price, rel_tol=1e-9):
            return

        filters = binance_api.get_symbol_filters(symbol)
        if not filters:
            log.warning(f"Could not get filters for {symbol} to place trailing stop.")
            return
        
        stop_price = binance_api.round_value(stop_price, filters['tickSize'])

        acct = binance_api._safe_api_call(binance_api.client.futures_account)
        if not acct:
            log.debug(f"No account info to place stop for {symbol}")
            return
            
        pos = next((p for p in acct.get("positions", []) if p["symbol"] == symbol), None)
        if not pos or float(pos.get("positionAmt", 0)) == 0:
            return
            
        qty = abs(float(pos["positionAmt"]))
        side = SIDE_SELL if float(pos["positionAmt"]) > 0 else SIDE_BUY
        
        prev_order_id = trailing_data.get("stop_order_id")
        if prev_order_id:
            canceled = binance_api.cancel_order(symbol, prev_order_id)
            if canceled:
                log.info(f"Canceled previous stop order {prev_order_id} for {symbol}")
        
        params = {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "stopPrice": str(stop_price),
            "closePosition": "true"
        }
        
        if config.DRY_RUN:
            log.info(f"[DRY RUN] Would place STOP_MARKET for {symbol} @ {stop_price}")
            with state_lock:
                td = app_state["trailing_stop_data"].setdefault(symbol, {})
                td["last_stop_price"] = stop_price
                td["stop_order_id"] = "DRY_RUN"
            socketio.emit('trailing_update', {"symbol": symbol, "stop_price": stop_price, "dry_run": True})
            return
            
        result = binance_api._safe_api_call(binance_api.client.futures_create_order, **params)
        
        if result:
            with state_lock:
                td = app_state["trailing_stop_data"].setdefault(symbol, {})
                td["last_stop_price"] = stop_price
                td["stop_order_id"] = result.get("orderId")
            log.info(f"🛡️ STOP_MARKET placed for {symbol} @ {stop_price} (orderId={result.get('orderId')})")
            socketio.emit('trailing_update', {"symbol": symbol, "stop_price": stop_price, "orderId": result.get('orderId')})
        else:
            log.warning(f"❌ Failed to place STOP_MARKET for {symbol} @ {stop_price} (result={result})")
            
    except Exception as e:
        log.error(f"Error placing exchange trailing stop for {symbol}: {e}", exc_info=True)


def monitor_positions(binance_api: BinanceFutures, interval: float = 15.0):
    """Monitor positions and update trailing stops on exchange"""
    log.info(f"🔎 Trailing monitor started (interval={interval}s)")
    
    while True:
        try:
            with state_lock:
                if not app_state.get("running"):
                    break
                symbols = list(app_state["trailing_stop_data"].keys())
                
            acct = binance_api._safe_api_call(binance_api.client.futures_account)
            acct_symbols = []
            if acct:
                acct_symbols = [p["symbol"] for p in acct.get("positions", []) if float(p.get('positionAmt', 0)) != 0]
                
            symbols_to_check = set(symbols) | set(acct_symbols)
            
            for symbol in symbols_to_check:
                try:
                    mark = binance_api._safe_api_call(binance_api.client.futures_mark_price, symbol=symbol)
                    if not mark:
                        continue
                    current_price = float(mark.get("markPrice", 0) or 0)
                    
                    with state_lock:
                        trailing_data = app_state["trailing_stop_data"].get(symbol)
                        
                    if not trailing_data:
                        if acct:
                            pos = next((p for p in acct.get("positions", []) if p["symbol"] == symbol), None)
                            if pos and float(pos.get('positionAmt', 0)) != 0:
                                entry_price = float(pos.get('entryPrice', current_price) or current_price)
                                side = "LONG" if float(pos["positionAmt"]) > 0 else "SHORT"
                                with state_lock:
                                    app_state["trailing_stop_data"][symbol] = {
                                        "activated": False,
                                        "best_price": entry_price,
                                        "current_stop": entry_price,
                                        "side": side,
                                        "last_stop_price": 0.0,
                                        "stop_order_id": None
                                    }
                                trailing_data = app_state["trailing_stop_data"].get(symbol)
                    
                    if trailing_data:
                        with state_lock:
                            td = app_state["trailing_stop_data"].get(symbol)
                            if not td:
                                continue
                                
                            if td.get("side") == "LONG":
                                if current_price > td.get("best_price", 0):
                                    td["best_price"] = current_price
                                    if td.get("activated"):
                                        td["current_stop"] = td["best_price"] * (1 - config.TRAILING_STOP_PERCENTAGE / 100)
                            else:
                                if current_price < td.get("best_price", float('inf')):
                                    td["best_price"] = current_price
                                    if td.get("activated"):
                                        td["current_stop"] = td["best_price"] * (1 + config.TRAILING_STOP_PERCENTAGE / 100)
                                        
                        if td and td.get("activated"):
                            apply_exchange_trailing_stop(binance_api, symbol)
                            
                except Exception as inner_e:
                    log.error(f"Error in monitor loop for {symbol}: {inner_e}", exc_info=True)
                    
        except Exception as e:
            log.error(f"Error in trailing monitor: {e}", exc_info=True)
            
        time.sleep(interval)

# -------------------- WEB ROUTES -------------------- #
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": time.time()})

@app.route('/api/status')
def get_status():
    with state_lock:
        return jsonify(app_state)

@app.route('/api/positions')
def api_positions():
    """Return open positions from exchange + local trailing stop data"""
    try:
        api = BinanceFutures()
        acct = api._safe_api_call(api.client.futures_account)
        positions = {}
        if acct:
            for p in acct.get('positions', []):
                if float(p.get('positionAmt', 0)) != 0:
                    positions[p['symbol']] = p
                    
        with state_lock:
            trailing = app_state['trailing_stop_data'].copy()
            sl_tp = app_state['sl_tp_data'].copy()
            
        return jsonify({"positions": positions, "trailing": trailing, "sl_tp": sl_tp})
    except Exception as e:
        log.error(f"Error fetching positions: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/start', methods=['POST'])
def start_bot():
    global bot_thread, _trailing_monitor_thread
    
    with state_lock:
        if app_state["running"]:
            return jsonify({"status": "error", "message": "Bot is already running"}), 400
        
        app_state["running"] = True
        app_state["status_message"] = "Starting..."
    
    bot_instance = TradingBot()
    bot_thread = threading.Thread(target=bot_instance.run, daemon=True)
    bot_thread.start()
    
    if _trailing_monitor_thread is None or not _trailing_monitor_thread.is_alive():
        _trailing_monitor_thread = threading.Thread(
            target=monitor_positions,
            args=(bot_instance.api, max(5.0, config.POLL_SEC)),
            daemon=True
        )
        _trailing_monitor_thread.start()
        log.info("▶️ Trailing monitor thread started.")
    
    log.info("▶️ Bot started from web interface.")
    return jsonify({"status": "success", "message": "Bot started successfully."})

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    with state_lock:
        if not app_state["running"]:
            return jsonify({"status": "error", "message": "Bot is not running"}), 400
        
        app_state["running"] = False
        app_state["status_message"] = "Stopping..."
    
    log.info("⏹️ Bot stopped from web interface.")
    return jsonify({"status": "success", "message": "Bot stopped."})

@app.route('/api/update_config', methods=['POST'])
def update_config():
    global config
    data = request.json
    
    def cast_value(current, value):
        if isinstance(current, bool):
            return str(value).lower() in ['true', '1', 'yes', 'on']
        if isinstance(current, int) and not isinstance(current, bool):
            return int(value)
        if isinstance(current, float):
            return float(value)
        if isinstance(current, tuple) and isinstance(value, (list, tuple)):
            return tuple(str(x).upper() for x in value)
        if isinstance(current, tuple) and isinstance(value, str):
            parts = [p.strip().upper() for p in value.split(',') if p.strip()]
            return tuple(parts)
        if isinstance(current, str):
            return str(value)
        return value
    
    with state_lock:
        for key, value in data.items():
            if hasattr(config, key):
                try:
                    cur = getattr(config, key)
                    setattr(config, key, cast_value(cur, value))
                except Exception as e:
                    log.warning(f"Failed to set config field {key}: {e}")
        
        app_state["config"] = asdict(config)
    
    log.info(f"⚙️ Configuration updated: {data}")
    socketio.emit('config_updated')
    return jsonify({
        "status": "success",
        "message": "Configuration saved.",
        "config": app_state["config"]
    })

@app.route('/api/close_position', methods=['POST'])
def close_position_api():
    symbol = request.json.get('symbol')
    if not symbol:
        return jsonify({"status": "error", "message": "Missing symbol"}), 400
    
    with state_lock:
        position = app_state["open_positions"].get(symbol)
    
    if not position:
        try: # Fallback to check directly with Binance
            api = BinanceFutures()
            acct = api._safe_api_call(api.client.futures_account)
            position = next((p for p in acct.get('positions', []) if p['symbol'] == symbol and float(p['positionAmt']) != 0), None)
            if not position:
                return jsonify({"status": "error", "message": f"No active position found for {symbol}"}), 404
        except Exception as e:
            log.error(f"API check failed for closing {symbol}: {e}")
            return jsonify({"status": "error", "message": f"No cached position and API check failed for {symbol}"}), 404

    try:
        api = BinanceFutures()
        result = api.close_position(symbol, float(position['positionAmt']))
        
        if result:
            pnl_records = api._safe_api_call(api.client.futures_account_trades, symbol=symbol, limit=10)
            realized_pnl = 0.0
            if pnl_records:
                order_id_to_match = result.get('orderId')
                if order_id_to_match:
                    realized_pnl = sum(float(trade.get('realizedPnl', 0)) for trade in pnl_records if str(trade.get('orderId')) == str(order_id_to_match))
            
            mark = api._safe_api_call(api.client.futures_mark_price, symbol=symbol)
            mark_price = float(mark['markPrice']) if mark else float(position['entryPrice'])
            
            entry_price = float(position['entryPrice'])
            position_size = abs(float(position['positionAmt']))
            roe = (realized_pnl / (position_size * entry_price)) * 100 * config.LEVERAGE if entry_price else 0.0
            
            with state_lock:
                stats = app_state["performance_stats"]
                stats["realized_pnl"] += realized_pnl
                stats["trades_count"] += 1
                
                trade_record = {
                    "symbol": symbol,
                    "side": 'LONG' if float(position['positionAmt']) > 0 else 'SHORT',
                    "quantity": position_size,
                    "entryPrice": entry_price,
                    "exitPrice": mark_price,
                    "pnl": realized_pnl,
                    "roe": roe,
                    "closeType": "manual",
                    "timestamp": time.time(),
                    "date": datetime.now().isoformat()
                }
                app_state["trades_history"].append(trade_record)
                
                if realized_pnl >= 0:
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1
                
                if symbol in app_state["trailing_stop_data"]:
                    del app_state["trailing_stop_data"][symbol]
                
                if symbol in app_state["sl_tp_data"]:
                    del app_state["sl_tp_data"][symbol]
                
                if symbol in app_state["open_positions"]:
                    del app_state["open_positions"][symbol]
            
            log.info(f"✅ Position on {symbol} closed. Realized PNL: {realized_pnl:.2f} USDT, ROE: {roe:.2f}%")
            socketio.emit('status_update', app_state)
            return jsonify({"status": "success", "message": f"Position on {symbol} closed."})
        else:
            return jsonify({"status": "error", "message": "Failed to send close order."}), 500
            
    except Exception as e:
        log.error(f"Error closing position {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/manual_trade', methods=['POST'])
def manual_trade():
    data = request.json
    symbol = data.get('symbol', '').upper()
    side = data.get('side')
    margin = float(data.get('margin', 10))
    
    if not all([symbol, side]):
        return jsonify({"status": "error", "message": "Missing parameters."}), 400
    
    try:
        api = BinanceFutures()
        api.ensure_symbol_settings(symbol)
        
        mark = api._safe_api_call(api.client.futures_mark_price, symbol=symbol)
        if not mark:
            return jsonify({"status": "error", "message": "Unable to fetch mark price."}), 500
        price = float(mark['markPrice'])
        
        filters = api.get_symbol_filters(symbol)
        if not filters:
            return jsonify({"status": "error", "message": f"Could not get filters for {symbol}"}), 500
        
        quantity = (margin * config.LEVERAGE) / price
        quantity = api.round_value(quantity, filters['stepSize'])
        
        if quantity < filters['minQty'] or (quantity * price) < filters['minNotional']:
            return jsonify({"status": "error", "message": f"Quantity ({quantity}) below minimum allowed."}), 400
        
        order_side = SIDE_BUY if side == 'LONG' else SIDE_SELL
        
        order = api.place_order(symbol, order_side, FUTURE_ORDER_TYPE_MARKET, quantity)
        
        if order and (order.get('orderId') or order.get('mock')):
            log.info(f"MANUAL TRADE CREATED: {side} {quantity} {symbol}")
            return jsonify({"status": "success", "message": f"Manual market order for {symbol} created."})
        else:
            return jsonify({"status": "error", "message": f"Manual order failed: {order}"}), 500
            
    except Exception as e:
        log.error(f"Error in manual trade: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/trade_history')
def get_trade_history():
    with state_lock:
        trades = app_state["trades_history"]
    
    sorted_trades = sorted(trades, key=lambda x: x.get('timestamp', 0), reverse=True)
    
    symbol_filter = request.args.get('symbol')
    date_filter = request.args.get('date')
    side_filter = request.args.get('side')
    
    filtered_trades = sorted_trades
    if symbol_filter:
        filtered_trades = [t for t in filtered_trades if t.get('symbol') == symbol_filter]
    if date_filter:
        try:
            from datetime import datetime as _dt
            filter_date = _dt.strptime(date_filter, '%Y-%m-%d').date()
            filtered_trades = [t for t in filtered_trades if _dt.fromtimestamp(t.get('timestamp', 0)).date() == filter_date]
        except Exception:
            pass
    if side_filter:
        filtered_trades = [t for t in filtered_trades if t.get('side') == side_filter]
    
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    
    paginated_trades = filtered_trades[start_idx:end_idx]
    
    return jsonify({
        "trades": paginated_trades,
        "total": len(filtered_trades),
        "page": page,
        "per_page": per_page,
        "total_pages": (len(filtered_trades) + per_page - 1) // per_page
    })

@app.route('/api/trailing_stop_data')
def get_trailing_stop_data():
    with state_lock:
        return jsonify(app_state["trailing_stop_data"])

@app.route('/api/sl_tp_data')
def get_sl_tp_data():
    with state_lock:
        return jsonify(app_state["sl_tp_data"])

@app.route('/api/risk_metrics')
def get_risk_metrics():
    with state_lock:
        return jsonify(app_state["risk_metrics"])

@app.route('/api/performance_metrics')
def get_performance_metrics():
    try:
        symbol = request.args.get('symbol')
        hours = int(request.args.get('hours', 24))
        
        db = SessionLocal()
        
        query = db.query(PerformanceMetrics)
        
        if symbol:
            query = query.filter(PerformanceMetrics.symbol == symbol)
            
        if hours:
            query = query.filter(PerformanceMetrics.timestamp >= datetime.now() - timedelta(hours=hours))
            
        metrics = query.order_by(desc(PerformanceMetrics.timestamp)).limit(50).all()
        
        return jsonify([{
            'timestamp': m.timestamp.isoformat(),
            'symbol': m.symbol,
            'win_rate': m.win_rate,
            'profit_factor': m.profit_factor,
            'avg_win': m.avg_win,
            'avg_loss': m.avg_loss,
            'recommended_leverage': m.recommended_leverage,
            'strategy_effectiveness': m.strategy_effectiveness,
            'market_volatility': m.market_volatility
        } for m in metrics])
        
    except Exception as e:
        log.error(f"Error fetching performance metrics: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route('/api/auto_adjust_leverage', methods=['POST'])
def auto_adjust_leverage():
    try:
        data = request.json
        symbol = data.get('symbol')
        
        bot = TradingBot()
        result = bot.analyze_trading_performance(symbol)
        
        if result and 'recommended_leverage' in result:
            with state_lock:
                config.LEVERAGE = result['recommended_leverage']
                app_state["config"] = asdict(config)
                
            bot.api.ensure_symbol_settings(symbol)
            
            return jsonify({
                "status": "success", 
                "message": f"Leverage ajustado a {result['recommended_leverage']}x para {symbol}",
                "new_leverage": result['recommended_leverage']
            })
        else:
            return jsonify({
                "status": "error", 
                "message": "No hay suficientes datos para ajustar el leverage"
            }), 400
            
    except Exception as e:
        log.error(f"Error ajustando leverage: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# -------------------- SOCKETIO EVENTS -------------------- #
@socketio.on('connect')
def handle_connect():
    log.info(f"🔌 Client connected: {request.sid}")
    with state_lock:
        socketio.emit('status_update', app_state, to=request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    log.info(f"🔌 Client disconnected: {request.sid}")

# -------------------- MAIN FUNCTION -------------------- #
if __name__ == '__main__':
    load_dotenv()
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    log.info("🚀 Starting Binance Futures Bot Web Application v10.5")
    log.info(f"🌐 Server will run on {host}:{port}")
    
    os.makedirs('logs', exist_ok=True)
    
    try:
        from database import init_db
        init_db()
        log.info("Database initialized successfully.")
    except ImportError:
        log.warning("Database module not found, continuing without it.")
    except Exception as e:
        log.error(f"Database initialization failed: {e}")

    socketio.run(
        app,
        debug=debug,
        host=host,
        port=port,
        use_reloader=False,
        allow_unsafe_werkzeug=True
    )