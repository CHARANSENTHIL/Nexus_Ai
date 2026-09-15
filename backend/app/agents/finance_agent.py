"""Financial & Market Intelligence Sentinel Agent for Nexus AI.

Fetches real-time market data, historical OHLCV, calculates technical indicators,
renders candlestick charts with moving averages via mplfinance/matplotlib,
and generates local AI technical analysis via Ollama.
"""
import os
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
FINANCE_MODEL = os.getenv("FINANCE_MODEL", "phi4-mini:latest")
CHARTS_DIR = Path("D:/nexus_ai/backend/finance_output/charts")
CHARTS_DIR.mkdir(parents=True, exist_ok=True)


class FinanceAgent:
    """Agent for automated financial market analysis, technical indicators, and charting."""

    def __init__(self, ollama_url: str = OLLAMA_BASE_URL, model: str = FINANCE_MODEL):
        self.ollama_url = ollama_url
        self.model = model

    async def get_market_analysis(
        self,
        symbol: str,
        period: str = "1mo",
        interval: str = "1d",
        generate_chart: bool = True
    ) -> Dict[str, Any]:
        """Fetches market data for a symbol (stocks, crypto, forex, commodities), builds charts and analysis."""
        # Clean symbol (e.g. bitcoin -> BTC-USD, ethereum -> ETH-USD, apple -> AAPL)
        clean_symbol = self._normalize_symbol(symbol)
        logger.info(f"[FinanceAgent] Fetching analysis for '{clean_symbol}' (period={period})...")

        # Run yfinance extraction in executor (blocking I/O)
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None,
                self._fetch_and_render,
                clean_symbol,
                period,
                interval,
                generate_chart
            )
        except Exception as e:
            logger.error(f"[FinanceAgent] Data fetch failed: {e}", exc_info=True)
            return {"success": False, "error": f"Failed to fetch market data for {symbol}: {str(e)}"}

        if not data.get("success"):
            return data

        # AI Technical Commentary with local LLM
        commentary = await self._generate_commentary_with_llm(data)
        data["ai_analysis"] = commentary
        
        # Build human-friendly formatted summary
        formatted_summary = (
            f"📈 **Market Report: {data.get('symbol')} ({data.get('name')})**\n"
            f"• **Current Price**: {data.get('currency', '$')}{data.get('current_price'):,.2f} "
            f"({data.get('change_percent', 0):+.2f}%)\n"
            f"• **Day Range**: {data.get('day_low', 'N/A')} - {data.get('day_high', 'N/A')}\n"
            f"• **52-Week Range**: {data.get('fifty_two_week_low', 'N/A')} - {data.get('fifty_two_week_high', 'N/A')}\n"
            f"• **Market Cap / Volume**: {data.get('market_cap_str', 'N/A')} | Vol: {data.get('volume_str', 'N/A')}\n\n"
            f"📊 **Technical Insights**:\n{commentary}"
        )
        data["formatted_summary"] = formatted_summary
        return data

    def _normalize_symbol(self, sym: str) -> str:
        s = sym.strip().upper()
        mapping = {
            "BITCOIN": "BTC-USD",
            "BTC": "BTC-USD",
            "ETHEREUM": "ETH-USD",
            "ETH": "ETH-USD",
            "SOLANA": "SOL-USD",
            "SOL": "SOL-USD",
            "DOGE": "DOGE-USD",
            "DOGECOIN": "DOGE-USD",
            "NIFTY": "^NSEI",
            "SENSEX": "^BSESN",
            "GOLD": "GC=F",
            "SILVER": "SI=F",
            "CRUDE": "CL=F",
            "APPLE": "AAPL",
            "MICROSOFT": "MSFT",
            "GOOGLE": "GOOGL",
            "ALPHABET": "GOOGL",
            "AMAZON": "AMZN",
            "TESLA": "TSLA",
            "NVIDIA": "NVDA",
            "META": "META"
        }
        return mapping.get(s, s)

    def _fetch_and_render(self, symbol: str, period: str, interval: str, generate_chart: bool) -> Dict[str, Any]:
        import yfinance as yf
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        ticker = yf.Ticker(symbol)
        history = ticker.history(period=period, interval=interval)

        if history.empty:
            return {"success": False, "error": f"No market history found for symbol '{symbol}'."}

        info = ticker.info if hasattr(ticker, "info") else {}
        current_price = history["Close"].iloc[-1]
        prev_close = history["Close"].iloc[-2] if len(history) > 1 else current_price
        change_pct = ((current_price - prev_close) / prev_close) * 100.0 if prev_close else 0.0

        day_high = history["High"].iloc[-1]
        day_low = history["Low"].iloc[-1]
        volume = history["Volume"].iloc[-1]

        mcap = info.get("marketCap", 0)
        mcap_str = f"${mcap / 1e9:.2f}B" if mcap > 1e9 else (f"${mcap / 1e6:.2f}M" if mcap > 1e6 else "N/A")
        vol_str = f"{volume / 1e6:.2f}M" if volume > 1e6 else f"{volume:,}"

        chart_path = None
        if generate_chart and len(history) >= 2:
            try:
                import mplfinance as mpf
                chart_filename = f"{symbol.replace('^', '').replace('=', '').replace('-', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                full_chart_path = CHARTS_DIR / chart_filename

                # Dark modern theme style
                mc = mpf.make_marketcolors(up='#00F0FF', down='#FF0055', inherit=True)
                s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridcolor='#222233')

                # Calculate MA lines if enough data
                mav_args = (5, 20) if len(history) >= 20 else (3,)
                mpf.plot(
                    history,
                    type='candle',
                    style=s,
                    title=f"{symbol} ({period.upper()}) Technical Chart",
                    ylabel='Price',
                    ylabel_lower='Volume',
                    volume=True,
                    mav=mav_args,
                    savefig=str(full_chart_path)
                )
                chart_path = str(full_chart_path)
            except Exception as chart_err:
                logger.warning(f"[FinanceAgent] mplfinance render failed, falling back to matplotlib: {chart_err}")
                try:
                    plt.figure(figsize=(10, 5), facecolor="#121218")
                    ax = plt.axes()
                    ax.set_facecolor("#181824")
                    plt.plot(history.index, history["Close"], color="#00E5FF", linewidth=2, label="Close Price")
                    plt.title(f"{symbol} Price Chart", color="white", fontsize=14)
                    plt.grid(True, color="#28283c", linestyle="--", alpha=0.5)
                    plt.tick_params(colors="white")
                    chart_filename = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_line.png"
                    full_chart_path = CHARTS_DIR / chart_filename
                    plt.savefig(str(full_chart_path), facecolor="#121218", bbox_inches="tight")
                    plt.close()
                    chart_path = str(full_chart_path)
                except Exception as ex:
                    logger.error(f"[FinanceAgent] Chart fallback failed: {ex}")

        return {
            "success": True,
            "symbol": symbol,
            "name": info.get("shortName", symbol),
            "currency": info.get("currency", "$"),
            "current_price": float(current_price),
            "change_percent": float(change_pct),
            "day_high": float(day_high),
            "day_low": float(day_low),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh", "N/A"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow", "N/A"),
            "market_cap_str": mcap_str,
            "volume_str": vol_str,
            "chart_path": chart_path,
            "recent_closes": [float(c) for c in history["Close"].tail(5).tolist()]
        }

    async def _generate_commentary_with_llm(self, data: Dict[str, Any]) -> str:
        """Generates concise technical market commentary using local Ollama model."""
        prompt = (
            f"You are a CFA Charterholder financial analyst. "
            f"Analyze this market data for {data.get('symbol')} ({data.get('name')}):\n"
            f"- Current Price: {data.get('currency', '$')}{data.get('current_price'):.2f}\n"
            f"- 24h Change: {data.get('change_percent'):+.2f}%\n"
            f"- Day High/Low: {data.get('day_high')} / {data.get('day_low')}\n"
            f"- 52w Range: {data.get('fifty_two_week_low')} - {data.get('fifty_two_week_high')}\n"
            f"- Recent 5 Close Trend: {data.get('recent_closes')}\n\n"
            f"Provide a 3-bullet point technical breakdown: 1) Trend Momentum, 2) Key Support/Resistance, 3) Short-term Outlook. "
            f"Keep it professional, data-driven, and concise."
        )

        for model in [self.model, "qwen3:4b", "phi4-mini:latest", "qwen3:1.7b"]:
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(
                        f"{self.ollama_url}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False}
                    )
                    if resp.status_code == 200:
                        return resp.json().get("response", "").strip()
            except Exception as e:
                logger.warning(f"[FinanceAgent] Commentary model {model} failed: {e}")
                continue

        trend = "Bullish" if data.get("change_percent", 0) > 0 else "Bearish"
        return f"• Price Action: {trend} momentum ({data.get('change_percent', 0):+.2f}%).\n• Day Range: Oscillating between {data.get('day_low')} and {data.get('day_high')}.\n• Monitor key psychological levels near current price."


finance_agent = FinanceAgent()
