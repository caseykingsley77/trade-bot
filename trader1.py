import websocket
import json
import numpy as np
from datetime import datetime
import time

class DerivTradingBot:
    def __init__(self, api_token, symbol='frxEURUSD'):
        """
        Initialize Deriv trading bot
        
        Args:
            api_token: Your Deriv API token
            symbol: Currency pair to trade (default: EUR/USD)
        """
        self.api_token = api_token
        self.symbol = symbol
        self.ws_url = "wss://ws.derivws.com/websockets/v3?app_id=1089"
        self.ws = None
        self.candles = []
        self.position = None
        
        # Pattern parameters
        self.lookback_period = 50  # Candles to analyze
        self.tolerance = 0.002  # 0.2% tolerance for peak/trough matching
        self.min_candles_between = 10  # Minimum candles between peaks/troughs
        
        # Risk management
        self.risk_percent = 2  # Risk 2% per trade
        self.profit_target_ratio = 2  # Risk:Reward = 1:2
        
    def connect(self):
        """Connect to Deriv WebSocket API"""
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )
        
    def on_open(self, ws):
        """Authenticate and subscribe to candles"""
        print(f"Connected to Deriv API - Trading {self.symbol}")
        
        # Authorize
        auth_request = {
            "authorize": self.api_token
        }
        ws.send(json.dumps(auth_request))
        
    def on_message(self, ws, message):
        """Handle incoming messages"""
        data = json.loads(message)
        
        if 'authorize' in data:
            print(f"Authorized - Account: {data['authorize']['loginid']}")
            # Subscribe to candles
            self.subscribe_candles()
            
        elif 'candles' in data:
            self.process_candles(data['candles'])
            
        elif 'ohlc' in data:
            self.update_candle(data['ohlc'])
            
        elif 'error' in data:
            print(f"Error: {data['error']['message']}")
            
    def subscribe_candles(self):
        """Subscribe to candlestick data"""
        request = {
            "ticks_history": self.symbol,
            "adjust_start_time": 1,
            "count": self.lookback_period,
            "end": "latest",
            "start": 1,
            "style": "candles",
            "granularity": 300,  # 5-minute candles
            "subscribe": 1
        }
        self.ws.send(json.dumps(request))
        print("Subscribed to 5-minute candles")
        
    def process_candles(self, candles):
        """Process historical candles"""
        self.candles = []
        for candle in candles:
            self.candles.append({
                'time': candle['epoch'],
                'open': float(candle['open']),
                'high': float(candle['high']),
                'low': float(candle['low']),
                'close': float(candle['close'])
            })
        print(f"Loaded {len(self.candles)} candles")
        self.analyze_patterns()
        
    def update_candle(self, ohlc):
        """Update with new candle"""
        new_candle = {
            'time': ohlc['epoch'],
            'open': float(ohlc['open']),
            'high': float(ohlc['high']),
            'low': float(ohlc['low']),
            'close': float(ohlc['close'])
        }
        
        # Update or append candle
        if self.candles and self.candles[-1]['time'] == new_candle['time']:
            self.candles[-1] = new_candle
        else:
            self.candles.append(new_candle)
            if len(self.candles) > self.lookback_period:
                self.candles.pop(0)
            self.analyze_patterns()
            
    def find_peaks(self, data, order=3):
        """Find local peaks in price data"""
        peaks = []
        for i in range(order, len(data) - order):
            if all(data[i] >= data[i-j] for j in range(1, order+1)) and \
               all(data[i] >= data[i+j] for j in range(1, order+1)):
                peaks.append(i)
        return peaks
        
    def find_troughs(self, data, order=3):
        """Find local troughs in price data"""
        troughs = []
        for i in range(order, len(data) - order):
            if all(data[i] <= data[i-j] for j in range(1, order+1)) and \
               all(data[i] <= data[i+j] for j in range(1, order+1)):
                troughs.append(i)
        return troughs
        
    def detect_double_top(self):
        """Detect double top pattern"""
        if len(self.candles) < 20:
            return None
            
        highs = [c['high'] for c in self.candles]
        peaks = self.find_peaks(highs)
        
        if len(peaks) < 2:
            return None
            
        # Check last two peaks
        for i in range(len(peaks) - 2, -1, -1):
            peak1_idx = peaks[i]
            peak2_idx = peaks[i + 1]
            
            # Check distance between peaks
            if peak2_idx - peak1_idx < self.min_candles_between:
                continue
                
            peak1_price = highs[peak1_idx]
            peak2_price = highs[peak2_idx]
            
            # Check if peaks are similar
            price_diff = abs(peak1_price - peak2_price) / peak1_price
            if price_diff <= self.tolerance:
                # Find neckline (lowest point between peaks)
                between_lows = [self.candles[j]['low'] for j in range(peak1_idx, peak2_idx + 1)]
                neckline = min(between_lows)
                
                # Check if price broke neckline
                current_price = self.candles[-1]['close']
                if current_price < neckline:
                    return {
                        'pattern': 'double_top',
                        'peak1': peak1_price,
                        'peak2': peak2_price,
                        'neckline': neckline,
                        'entry': current_price,
                        'stop_loss': max(peak1_price, peak2_price),
                        'take_profit': neckline - (max(peak1_price, peak2_price) - neckline)
                    }
        return None
        
    def detect_double_bottom(self):
        """Detect double bottom pattern"""
        if len(self.candles) < 20:
            return None
            
        lows = [c['low'] for c in self.candles]
        troughs = self.find_troughs(lows)
        
        if len(troughs) < 2:
            return None
            
        # Check last two troughs
        for i in range(len(troughs) - 2, -1, -1):
            trough1_idx = troughs[i]
            trough2_idx = troughs[i + 1]
            
            # Check distance between troughs
            if trough2_idx - trough1_idx < self.min_candles_between:
                continue
                
            trough1_price = lows[trough1_idx]
            trough2_price = lows[trough2_idx]
            
            # Check if troughs are similar
            price_diff = abs(trough1_price - trough2_price) / trough1_price
            if price_diff <= self.tolerance:
                # Find neckline (highest point between troughs)
                between_highs = [self.candles[j]['high'] for j in range(trough1_idx, trough2_idx + 1)]
                neckline = max(between_highs)
                
                # Check if price broke neckline
                current_price = self.candles[-1]['close']
                if current_price > neckline:
                    return {
                        'pattern': 'double_bottom',
                        'trough1': trough1_price,
                        'trough2': trough2_price,
                        'neckline': neckline,
                        'entry': current_price,
                        'stop_loss': min(trough1_price, trough2_price),
                        'take_profit': neckline + (neckline - min(trough1_price, trough2_price))
                    }
        return None
        
    def analyze_patterns(self):
        """Analyze for double top/bottom patterns"""
        current_time = datetime.fromtimestamp(self.candles[-1]['time'])
        print(f"\n[{current_time}] Analyzing patterns...")
        
        # Check for double top (bearish)
        double_top = self.detect_double_top()
        if double_top:
            print(f"🔴 DOUBLE TOP DETECTED!")
            print(f"   Peak 1: {double_top['peak1']:.5f}")
            print(f"   Peak 2: {double_top['peak2']:.5f}")
            print(f"   Neckline: {double_top['neckline']:.5f}")
            print(f"   Entry: {double_top['entry']:.5f} (SELL)")
            print(f"   Stop Loss: {double_top['stop_loss']:.5f}")
            print(f"   Take Profit: {double_top['take_profit']:.5f}")
            self.execute_trade('PUT', double_top)
            
        # Check for double bottom (bullish)
        double_bottom = self.detect_double_bottom()
        if double_bottom:
            print(f"🟢 DOUBLE BOTTOM DETECTED!")
            print(f"   Trough 1: {double_bottom['trough1']:.5f}")
            print(f"   Trough 2: {double_bottom['trough2']:.5f}")
            print(f"   Neckline: {double_bottom['neckline']:.5f}")
            print(f"   Entry: {double_bottom['entry']:.5f} (BUY)")
            print(f"   Stop Loss: {double_bottom['stop_loss']:.5f}")
            print(f"   Take Profit: {double_bottom['take_profit']:.5f}")
            self.execute_trade('CALL', double_bottom)
            
    def execute_trade(self, trade_type, signal):
        """Execute trade on Deriv"""
        # Prevent multiple positions
        if self.position:
            print("   ⚠️  Already in position, skipping trade")
            return
            
        print(f"   📊 Executing {trade_type} trade...")
        
        # Calculate position size based on risk
        risk_amount = abs(signal['entry'] - signal['stop_loss'])
        
        # For demo: just log the trade
        # In production, send buy/sell request via API
        trade_request = {
            "buy": 1,
            "price": 10,  # Stake amount in USD
            "parameters": {
                "amount": 10,
                "basis": "stake",
                "contract_type": trade_type,
                "currency": "USD",
                "duration": 15,
                "duration_unit": "m",
                "symbol": self.symbol
            }
        }
        
        # Uncomment to execute real trades:
        # self.ws.send(json.dumps(trade_request))
        
        self.position = {
            'type': trade_type,
            'entry': signal['entry'],
            'stop_loss': signal['stop_loss'],
            'take_profit': signal['take_profit']
        }
        print(f"   ✅ Trade logged (enable real trading to execute)")
        
    def on_error(self, ws, error):
        """Handle errors"""
        print(f"Error: {error}")
        
    def on_close(self, ws, close_status_code, close_msg):
        """Handle connection close"""
        print("Connection closed")
        
    def run(self):
        """Start the bot"""
        print("=" * 60)
        print("Deriv Double Top/Bottom Trading Bot")
        print("=" * 60)
        self.connect()
        self.ws.run_forever()


if __name__ == "__main__":
    # IMPORTANT: Get your API token from https://app.deriv.com/account/api-token
    API_TOKEN = "YOUR_DERIV_API_TOKEN_HERE"
    
    # Choose currency pair
    # Options: frxEURUSD, frxGBPUSD, frxUSDJPY, frxAUDUSD, etc.
    SYMBOL = "frxEURUSD"
    
    # Create and run bot
    bot = DerivTradingBot(api_token=API_TOKEN, symbol=SYMBOL)
    
    print("\n⚠️  IMPORTANT NOTES:")
    print("1. Replace API_TOKEN with your actual Deriv API token")
    print("2. This bot logs trades but doesn't execute them by default")
    print("3. Test thoroughly with demo account before live trading")
    print("4. Uncomment trade execution code when ready for real trading")
    print("\nStarting bot...\n")
    
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\nBot stopped by user")