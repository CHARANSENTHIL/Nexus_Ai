"""Financial tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.finance_agent import finance_agent

logger = logging.getLogger(__name__)


@tool
def get_market_analysis(
    symbol: str,
    period: str = "1mo",
    interval: str = "1d",
    generate_chart: bool = True
) -> Dict[str, Any]:
    """
    Fetches real-time price action for stocks, crypto, commodities, indices,
    generates technical candlestick charts with moving averages, and provides AI market analysis.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    finance_agent.get_market_analysis(
                        symbol=symbol,
                        period=period,
                        interval=interval,
                        generate_chart=generate_chart
                    )
                ).result()
        else:
            return asyncio.run(
                finance_agent.get_market_analysis(
                    symbol=symbol,
                    period=period,
                    interval=interval,
                    generate_chart=generate_chart
                )
            )
    except Exception as e:
        logger.error(f"[FinanceTools] get_market_analysis failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
